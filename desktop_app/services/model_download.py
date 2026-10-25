"""One-time download of the local language model.

This module is the desktop application's only network client. It is kept out of
the assistant stack on purpose: ``AssistantController``, the conversation layer,
the service, and the provider never import it, and once the verified model file
exists the assistant runs entirely offline.

The download runs on a background thread, resumes a ``.part`` file with HTTP
byte ranges, checks free disk space first, and verifies the same SHA-256 the
provider enforces before atomically moving the file into place. UI code only
observes signals; no widget is touched here.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, Signal

from .. import paths
from .model_verifier import sha256_file
from .runtime_config import (
    VALIDATED_MODEL_BYTE_SIZE,
    VALIDATED_MODEL_NAME,
    VALIDATED_MODEL_SHA256,
)

MODEL_DOWNLOAD_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
    "qwen2.5-1.5b-instruct-q4_k_m.gguf"
)
USER_AGENT = "Ivyago/0.1.0 (Windows desktop; one-time model setup)"

CHUNK_SIZE = 1024 * 1024
DISK_HEADROOM_BYTES = 256 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 30.0
PROGRESS_INTERVAL_SECONDS = 0.15

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

STATE_IDLE = "idle"
STATE_DOWNLOADING = "downloading"
STATE_VERIFYING = "verifying"
STATE_DONE = "done"
STATE_CANCELLED = "cancelled"
STATE_FAILED = "failed"

MESSAGE_NETWORK = (
    "Could not reach the model download service. Check your internet "
    "connection and try again."
)
MESSAGE_UNAVAILABLE = (
    "The model download is not available right now. Try again later."
)
MESSAGE_DISK = (
    "There is not enough free disk space for the model. Free up about "
    "1.5 GB and try again."
)
MESSAGE_WRITE = (
    "The model could not be saved. Check free disk space and folder "
    "permissions, then try again."
)
MESSAGE_CHECKSUM = (
    "The downloaded model did not match its verified checksum, so it was "
    "removed. Please try the download again."
)
MESSAGE_INCOMPLETE = (
    "The download stopped before it finished. Try again to resume it."
)
MESSAGE_UNKNOWN = "The model could not be downloaded. Please try again."


@dataclass(frozen=True)
class ModelDownloadSpec:
    """Where the model comes from, where it goes, and what it must be."""

    url: str = MODEL_DOWNLOAD_URL
    destination: Path = field(
        default_factory=lambda: paths.model_file(VALIDATED_MODEL_NAME)
    )
    expected_size: int = VALIDATED_MODEL_BYTE_SIZE
    expected_sha256: str = VALIDATED_MODEL_SHA256

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        host = (parsed.hostname or "").lower()
        allowed = parsed.scheme == "https" or (
            parsed.scheme == "http" and host in _LOOPBACK_HOSTS
        )
        if not allowed:
            raise ValueError(
                "Model downloads must use https; http is allowed only for "
                "loopback test servers."
            )
        if not host:
            raise ValueError("Model download URL must include a host.")

        if self.expected_size <= 0:
            raise ValueError("expected_size must be positive.")

        digest = str(self.expected_sha256).lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(
                "expected_sha256 must be a 64-character hex digest."
            )
        object.__setattr__(self, "expected_sha256", digest)

    @property
    def part_path(self) -> Path:
        """Return the resumable partial-download path."""

        return self.destination.with_name(self.destination.name + ".part")


def default_model_download_spec() -> ModelDownloadSpec:
    """Return the packaged model source for this release."""

    return ModelDownloadSpec()


def model_is_ready(spec: ModelDownloadSpec | None = None) -> bool:
    """Return whether a complete model file already exists.

    Size is the cheap startup check. The full SHA-256 verification still runs
    in the provider before the runtime opens the file.
    """

    resolved = spec or default_model_download_spec()
    try:
        return (
            resolved.destination.is_file()
            and resolved.destination.stat().st_size == resolved.expected_size
        )
    except OSError:
        return False


class ModelDownloader(QObject):
    """Background model download with progress, cancellation, and resume."""

    progress = Signal(int, int)
    state_changed = Signal(str)
    failed = Signal(str)
    finished = Signal(str)

    def __init__(
        self,
        spec: ModelDownloadSpec | None = None,
        parent: QObject | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(parent)
        self.spec = spec or default_model_download_spec()
        self._timeout = timeout
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        # Internal debugging detail; never rendered by the UI.
        self.last_error: str | None = None

    # -- lifecycle --------------------------------------------------------

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Start the download; return ``False`` when one is already running."""

        if self.is_running():
            return False
        self._cancel.clear()
        self.last_error = None
        self._thread = threading.Thread(
            target=self._run_guarded,
            name="ivyago-model-download",
            daemon=True,
        )
        self._thread.start()
        return True

    def cancel(self) -> None:
        """Ask the worker to stop; the partial file is kept for resume."""

        self._cancel.set()

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def shutdown(self) -> None:
        """Cancel and wait briefly; safe to call when the dialog closes."""

        self.cancel()
        self.wait(timeout=2.0)

    # -- worker -----------------------------------------------------------

    def _run_guarded(self) -> None:
        try:
            self._run()
        except Exception as exc:  # pragma: no cover - defensive boundary
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._emit_failed(MESSAGE_UNKNOWN)

    def _run(self) -> None:
        spec = self.spec
        part = spec.part_path

        try:
            spec.destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.last_error = str(exc)
            self._emit_failed(MESSAGE_WRITE)
            return

        offset = self._resume_offset(part, spec.expected_size)
        if not self._has_disk_space(spec, part, offset):
            self._emit_failed(MESSAGE_DISK)
            return

        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if offset:
            headers["Range"] = f"bytes={offset}-"

        self.state_changed.emit(STATE_DOWNLOADING)
        self.progress.emit(offset, spec.expected_size)

        try:
            response = urlopen(
                Request(spec.url, headers=headers), timeout=self._timeout
            )
        except HTTPError as exc:
            if exc.code in (404, 410):
                self._emit_failed(MESSAGE_UNAVAILABLE)
            else:
                self.last_error = f"HTTP {exc.code}"
                self._emit_failed(MESSAGE_NETWORK)
            return
        except (URLError, TimeoutError, OSError) as exc:
            self.last_error = str(exc)
            self._emit_failed(MESSAGE_NETWORK)
            return

        with response:
            status = getattr(response, "status", 200)
            resumed = offset > 0 and status == 206
            if not resumed:
                offset = 0

            mode = "ab" if resumed else "wb"
            try:
                handle = part.open(mode)
            except OSError as exc:
                self.last_error = str(exc)
                self._emit_failed(MESSAGE_WRITE)
                return

            last_emit = 0.0
            try:
                with handle:
                    while True:
                        if self._cancel.is_set():
                            self.state_changed.emit(STATE_CANCELLED)
                            return
                        try:
                            chunk = response.read(CHUNK_SIZE)
                        except (TimeoutError, OSError) as exc:
                            self.last_error = str(exc)
                            self._emit_failed(MESSAGE_NETWORK)
                            return
                        if not chunk:
                            break
                        try:
                            handle.write(chunk)
                        except OSError as exc:
                            self.last_error = str(exc)
                            self._emit_failed(MESSAGE_WRITE)
                            return
                        offset += len(chunk)
                        now = time.monotonic()
                        if (
                            now - last_emit >= PROGRESS_INTERVAL_SECONDS
                            or offset >= spec.expected_size
                        ):
                            last_emit = now
                            self.progress.emit(
                                min(offset, spec.expected_size),
                                spec.expected_size,
                            )
            except OSError as exc:  # pragma: no cover - filesystem edge
                self.last_error = str(exc)
                self._emit_failed(MESSAGE_WRITE)
                return

        if self._cancel.is_set():
            self.state_changed.emit(STATE_CANCELLED)
            return
        if offset != spec.expected_size:
            self._emit_failed(MESSAGE_INCOMPLETE)
            return

        self.state_changed.emit(STATE_VERIFYING)
        self.progress.emit(spec.expected_size, spec.expected_size)
        try:
            digest = sha256_file(part)
        except OSError as exc:
            self.last_error = str(exc)
            self._emit_failed(MESSAGE_WRITE)
            return

        if self._cancel.is_set():
            self.state_changed.emit(STATE_CANCELLED)
            return
        if digest.lower() != spec.expected_sha256:
            self._discard(part)
            self._emit_failed(MESSAGE_CHECKSUM)
            return

        try:
            os.replace(part, spec.destination)
        except OSError as exc:
            self.last_error = str(exc)
            self._emit_failed(MESSAGE_WRITE)
            return

        self.state_changed.emit(STATE_DONE)
        self.finished.emit(str(spec.destination))

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _resume_offset(part: Path, expected_size: int) -> int:
        try:
            size = part.stat().st_size
        except OSError:
            return 0
        if size <= 0 or size >= expected_size:
            if size >= expected_size and size > 0:
                ModelDownloader._discard(part)
            return 0
        return size

    @staticmethod
    def _has_disk_space(
        spec: ModelDownloadSpec, part: Path, offset: int
    ) -> bool:
        try:
            free = shutil.disk_usage(str(part.parent)).free
        except OSError:
            return True
        return free >= (spec.expected_size - offset) + DISK_HEADROOM_BYTES

    @staticmethod
    def _discard(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def _emit_failed(self, message: str) -> None:
        self.state_changed.emit(STATE_FAILED)
        self.failed.emit(message)
