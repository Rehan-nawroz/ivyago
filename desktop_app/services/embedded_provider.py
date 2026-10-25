"""Embedded llama.cpp provider selected by the Phase 2 compatibility gate.

Validated artifact:

* ``llama-cpp-python`` 0.3.19 (cp312 win_amd64 CPU wheel)
* Qwen2.5 1.5B Instruct Q4_K_M, 1,117,320,736 bytes

Gate limitation that shape this implementation: the runtime has no hard abort
API, so every generation streams tokens and the stop request is checked between
chunks. There is deliberately no ``stream=False`` path.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .model_provider import (
    GenerationError,
    GenerationRequest,
    ModelCorruptError,
    ModelLoadError,
    ModelMissingError,
    ModelStatus,
    ProviderStatus,
    RuntimeUnsupportedError,
    status_message,
)
from .model_verifier import ModelMetadata, resolve_model_path, verify_model_file
from .runtime_config import RuntimeConfig

DEFAULT_THREAD_LIMIT = 8

_STATUS_ERRORS = {
    ModelStatus.MODEL_MISSING: ModelMissingError,
    ModelStatus.MODEL_CORRUPT: ModelCorruptError,
    ModelStatus.UNSUPPORTED: RuntimeUnsupportedError,
    ModelStatus.ERROR: ModelLoadError,
}


def _content_delta(chunk: Any) -> str:
    """Return the streamed text of one chat-completion chunk, if any."""

    try:
        choices = chunk.get("choices") or []
        if not choices:
            return ""
        delta = choices[0].get("delta") or {}
        content = delta.get("content")
    except AttributeError:
        return ""
    return content if isinstance(content, str) else ""


def _close_stream(iterator: Any) -> None:
    if iterator is None:
        return
    close = getattr(iterator, "close", None)
    if callable(close):
        try:
            close()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass


def _default_runtime_factory() -> Callable[..., Any]:
    """Return the validated llama.cpp binding class, or fail as unsupported."""

    try:
        from llama_cpp import Llama  # noqa: PLC0415 - lazy native import
    except ImportError as exc:  # pragma: no cover - depends on install state
        raise RuntimeUnsupportedError(
            "The embedded llama.cpp runtime is not installed."
        ) from exc
    return Llama


class EmbeddedProvider:
    """`LocalModelProvider` implementation backed by an in-process GGUF model."""

    def __init__(
        self,
        config: RuntimeConfig,
        runtime_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._config = config
        self._runtime_factory = runtime_factory
        self._lock = threading.RLock()
        self._generation_lock = threading.Lock()
        self._llm: Any = None
        self._metadata: ModelMetadata | None = None
        self._stop_requested = threading.Event()
        self._closed = False
        self._status = ProviderStatus(
            ModelStatus.NOT_READY,
            status_message(ModelStatus.NOT_READY),
            config.model_name,
        )
        self.last_diagnostic: str | None = None

    # -- inspectable state ------------------------------------------------

    @property
    def config(self) -> RuntimeConfig:
        return self._config

    def status(self) -> ProviderStatus:
        return self._status

    def metadata(self) -> ModelMetadata | None:
        """Return verified model metadata once the model has been prepared."""

        return self._metadata

    # -- lifecycle --------------------------------------------------------

    def prepare(self) -> ProviderStatus:
        """Verify the model file and load the runtime, mapping failures to states."""

        with self._lock:
            if self._closed:
                return self._set_status(
                    ModelStatus.ERROR,
                    "The offline assistant has been closed.",
                )
            if self._llm is not None:
                return self._set_status(ModelStatus.READY)

            self._set_status(ModelStatus.PREPARING)

            try:
                path = resolve_model_path(self._config)
                self._metadata = verify_model_file(
                    path,
                    expected_size=self._config.expected_byte_size,
                    expected_sha256=self._config.expected_sha256,
                )
            except ModelMissingError as exc:
                self.last_diagnostic = str(exc)
                return self._set_status(ModelStatus.MODEL_MISSING, exc.user_message)
            except ModelCorruptError as exc:
                self.last_diagnostic = str(exc)
                return self._set_status(ModelStatus.MODEL_CORRUPT, exc.user_message)

            try:
                llm = self._build_runtime(Path(self._metadata.path))
            except RuntimeUnsupportedError as exc:
                self.last_diagnostic = str(exc)
                return self._set_status(ModelStatus.UNSUPPORTED, exc.user_message)
            except ImportError as exc:
                # A factory may fail to import its binding lazily.
                self.last_diagnostic = f"{type(exc).__name__}: {exc}"
                return self._set_status(
                    ModelStatus.UNSUPPORTED,
                    RuntimeUnsupportedError.user_message,
                )
            except Exception as exc:
                self.last_diagnostic = f"{type(exc).__name__}: {exc}"
                return self._set_status(
                    ModelStatus.ERROR,
                    ModelLoadError.user_message,
                )

            if llm is None:
                self.last_diagnostic = "The runtime factory returned no model"
                return self._set_status(ModelStatus.ERROR, ModelLoadError.user_message)

            self._llm = llm
            self.last_diagnostic = None
            return self._set_status(ModelStatus.READY)

    def _build_runtime(self, path: Path) -> Any:
        factory = self._runtime_factory
        if factory is None:
            factory = _default_runtime_factory()

        settings = self._config.generation
        threads = settings.n_threads or max(
            1, min(DEFAULT_THREAD_LIMIT, os.cpu_count() or 4)
        )
        return factory(
            model_path=str(path),
            n_ctx=settings.context_size,
            n_threads=threads,
            verbose=False,
        )

    def generate(
        self,
        request: GenerationRequest,
        on_token: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> str:
        """Stream a local chat completion and return the accumulated text."""

        if not isinstance(request, GenerationRequest):
            raise TypeError("generate() expects a GenerationRequest")

        if not self._generation_lock.acquire(blocking=False):
            raise GenerationError(
                "The local assistant is already generating a response."
            )

        try:
            self._ensure_ready()
            with self._lock:
                self._stop_requested.clear()
                self._set_status(ModelStatus.GENERATING)

            settings = self._config.generation
            parts: list[str] = []
            iterator: Any = None
            stopped = False
            failed = False

            try:
                stream = self._llm.create_chat_completion(
                    messages=self._messages(request),
                    stream=True,
                    max_tokens=settings.max_tokens,
                    temperature=settings.temperature,
                    top_p=settings.top_p,
                    repeat_penalty=settings.repeat_penalty,
                )
                iterator = iter(stream)
                while True:
                    if self._stop_requested.is_set() or (
                        stop_event is not None and stop_event.is_set()
                    ):
                        stopped = True
                        break
                    try:
                        chunk = next(iterator)
                    except StopIteration:
                        break
                    piece = _content_delta(chunk)
                    if not piece:
                        continue
                    parts.append(piece)
                    if on_token is not None:
                        on_token(piece)
            except Exception as exc:
                failed = True
                self.last_diagnostic = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    self._set_status(ModelStatus.ERROR, GenerationError.user_message)
                raise GenerationError(GenerationError.user_message) from exc
            finally:
                _close_stream(iterator)
                with self._lock:
                    if not failed and not self._closed:
                        self._set_status(
                            ModelStatus.STOPPED if stopped else ModelStatus.READY
                        )

            return "".join(parts)
        finally:
            self._generation_lock.release()

    def stop(self) -> None:
        """Request a cooperative stop; safe to call from another thread."""

        self._stop_requested.set()
        with self._lock:
            if self._status.state is ModelStatus.GENERATING:
                self._set_status(ModelStatus.STOPPING)

    def close(self) -> None:
        """Release the runtime object and mark the provider unavailable."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            llm, self._llm = self._llm, None
            self._metadata = None
            self._status = ProviderStatus(
                ModelStatus.NOT_READY,
                status_message(ModelStatus.NOT_READY),
                self._config.model_name,
            )

        close = getattr(llm, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # pragma: no cover - best-effort cleanup
                pass

    # -- internals --------------------------------------------------------

    def _messages(self, request: GenerationRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if request.system_prompt.strip():
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.user_prompt})
        return messages

    def _ensure_ready(self) -> None:
        if self._llm is not None:
            return

        status = self.prepare()
        if status.state is ModelStatus.READY:
            return

        error_type = _STATUS_ERRORS.get(status.state, ModelLoadError)
        raise error_type(status.detail or error_type.user_message)

    def _set_status(
        self,
        state: ModelStatus,
        detail: str | None = None,
    ) -> ProviderStatus:
        self._status = ProviderStatus(
            state,
            detail if detail is not None else status_message(state),
            self._config.model_name,
        )
        return self._status
