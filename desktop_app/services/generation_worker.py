"""Qt-safe generation worker.

The worker is a plain ``QObject`` that runs one provider generation and reports
lifecycle events as Qt signals. It never touches a widget: the controller turns
these signals into UI state on the Qt thread.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Qt, Signal

from .model_provider import GenerationRequest, LocalModelProvider

_GENERIC_FAILURE = "The local assistant could not finish that response."
_SERVICE_FAILURE = "The offline assistant could not complete that request."


class GenerationWorker(QObject):
    """Runs exactly one ``GenerationRequest`` on a worker thread."""

    started = Signal(str)
    token = Signal(str, str)
    completed = Signal(str, str)
    stopped = Signal(str, str)
    failed = Signal(str, str, str)
    finished = Signal(str)

    def __init__(
        self,
        provider: LocalModelProvider,
        request: GenerationRequest,
        stop_event: threading.Event | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._request = request
        self._stop_event = stop_event if stop_event is not None else threading.Event()
        self._chunks: list[str] = []
        self._stop_requested = False

    # -- inspectable state ------------------------------------------------

    @property
    def request_id(self) -> str:
        return self._request.request_id

    @property
    def partial_text(self) -> str:
        return "".join(self._chunks)

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    # -- Qt slots ---------------------------------------------------------

    def run(self) -> None:
        """Generate one response and emit the matching lifecycle signals."""

        request_id = self.request_id
        try:
            self.started.emit(request_id)
            text = self._provider.generate(
                self._request,
                on_token=self._emit_token,
                stop_event=self._stop_event,
            )
        except Exception as exc:  # typed provider errors and unexpected failures
            if self._stop_event.is_set():
                self.stopped.emit(request_id, self.partial_text)
            else:
                self.failed.emit(
                    request_id,
                    getattr(exc, "user_message", _GENERIC_FAILURE),
                    f"{type(exc).__name__}: {exc}",
                )
        else:
            if self._stop_event.is_set():
                self.stopped.emit(request_id, text or self.partial_text)
            else:
                self.completed.emit(request_id, text)
        finally:
            self.finished.emit(request_id)

    def request_stop(self) -> None:
        """Ask the provider to stop; safe from any thread."""

        self._stop_requested = True
        self._stop_event.set()
        try:
            self._provider.stop()
        except Exception:  # pragma: no cover - stop must never raise into the UI
            pass

    # -- internals --------------------------------------------------------

    def _emit_token(self, text: str) -> None:
        if not text:
            return
        self._chunks.append(text)
        self.token.emit(self.request_id, text)


class AssistantGenerationWorker(QObject):
    """Runs one assistant request through the service on a worker thread.

    This is the worker-owned orchestration unit for Phase 3. It keeps every
    service call (detector, SQLite, prompt construction, cleanup, fallback) off
    the Qt UI thread: ``prepare_request`` runs before the provider generates,
    and ``finalize_response`` runs after, with streamed tokens forwarded in
    between so the UI stays responsive.
    """

    started = Signal(str)                # request_id
    prepared = Signal(str, object)       # request_id, PreparedAssistantRequest
    token = Signal(str, str)             # request_id, chunk
    completed = Signal(str, str, object)  # request_id, final_text, AssistantResponse
    stopped = Signal(str, str)           # request_id, partial_text
    failed = Signal(str, str, str)       # request_id, user_message, diagnostic
    finished = Signal(str)               # request_id

    def __init__(
        self,
        provider: LocalModelProvider,
        service,
        request,
        stop_event: threading.Event | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._service = service
        self._request = request
        self._stop_event = stop_event if stop_event is not None else threading.Event()
        self._chunks: list[str] = []

    # -- inspectable state ------------------------------------------------

    @property
    def request_id(self) -> str:
        return self._request.request_id

    @property
    def partial_text(self) -> str:
        return "".join(self._chunks)

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    # -- Qt slots ---------------------------------------------------------

    def run(self) -> None:
        """Prepare, generate, and finalize one response; emit lifecycle signals."""

        request_id = self.request_id
        try:
            self.started.emit(request_id)

            # 1) Prepare prompts off the UI thread (detector + prompt policy).
            try:
                prepared = self._service.prepare_request(self._request)
            except Exception as exc:
                self.failed.emit(
                    request_id,
                    _SERVICE_FAILURE,
                    "AssistantService.prepare: %s: %s" % (type(exc).__name__, exc),
                )
                return
            self.prepared.emit(request_id, prepared)

            # 2) Generate through the provider, streaming tokens.
            generation = GenerationRequest(
                request_id=request_id,
                system_prompt=prepared.system_prompt,
                user_prompt=prepared.user_prompt,
            )
            try:
                text = self._provider.generate(
                    generation,
                    on_token=self._emit_token,
                    stop_event=self._stop_event,
                )
            except Exception as exc:
                if self._stop_event.is_set():
                    self.stopped.emit(request_id, self.partial_text)
                else:
                    self.failed.emit(
                        request_id,
                        getattr(exc, "user_message", _GENERIC_FAILURE),
                        "%s: %s" % (type(exc).__name__, exc),
                    )
                return

            if self._stop_event.is_set():
                # Cooperative stop preserves the streamed partial text as-is.
                self.stopped.emit(request_id, text or self.partial_text)
                return

            # 3) Finalize (clean/validate/fallback) off the UI thread.
            try:
                response = self._service.finalize_response(prepared, text)
            except Exception as exc:
                self.failed.emit(
                    request_id,
                    _SERVICE_FAILURE,
                    "AssistantService.finalize: %s: %s" % (type(exc).__name__, exc),
                )
                return

            self.completed.emit(request_id, response.text, response)
        finally:
            self.finished.emit(request_id)

    def request_stop(self) -> None:
        """Ask the provider to stop; safe from any thread."""

        self._stop_event.set()
        try:
            self._provider.stop()
        except Exception:  # pragma: no cover - stop must never raise into the UI
            pass

    # -- internals --------------------------------------------------------

    def _emit_token(self, text: str) -> None:
        if not text:
            return
        self._chunks.append(text)
        self.token.emit(self.request_id, text)


def start_generation_thread(
    worker,
    parent: QObject | None = None,
) -> QThread:
    """Move ``worker`` to a new thread, start it, and return the thread.

    ``worker.finished`` is connected to ``QThread.quit`` so normal completion
    stops the event loop. Callers that close the app should also call
    ``QThread.quit()`` directly, because a queued ``quit`` cannot run while the
    main thread is blocked waiting for shutdown.
    """

    thread = QThread(parent)
    thread.setObjectName("ivyago-generation")
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    # ``quit`` is thread-safe, and calling it directly from the worker thread
    # means the event loop stops even when the main thread is blocked waiting
    # for shutdown instead of pumping events.
    worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
    thread.start()
    return thread
