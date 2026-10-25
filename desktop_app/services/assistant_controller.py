"""Assistant controller: the only bridge between the Assist view and a provider.

The controller owns request identity, worker threads, and the app-facing state
machine. It contains no widgets, keeps only one generation alive at a time, and
ignores late events from a request that is no longer active.
"""

from __future__ import annotations

import uuid

from PySide6.QtCore import QObject, QThread, Qt, Signal

from .assistant_service import AssistantRequest
from .generation_worker import (
    AssistantGenerationWorker,
    GenerationWorker,
    start_generation_thread,
)
from .model_provider import (
    GenerationRequest,
    LocalModelProvider,
    ModelStatus,
    ProviderError,
    ProviderStatus,
    status_message,
)

_GENERATION_SHUTDOWN_MS = 5000
_PREPARATION_SHUTDOWN_MS = 15000

# Threads and workers that could not be joined are kept referenced so Qt never
# destroys a running QThread underneath the process.
_ORPHANED_THREADS: list[QThread] = []
_ORPHANED_WORKERS: list[QObject] = []

# Diagnostic prefixes that mean the model itself cannot be used, so the composer
# must stay disabled instead of inviting a retry that cannot succeed.
_TERMINAL_FAILURES = {
    "ModelMissingError": ModelStatus.MODEL_MISSING,
    "ModelCorruptError": ModelStatus.MODEL_CORRUPT,
    "RuntimeUnsupportedError": ModelStatus.UNSUPPORTED,
    "ModelLoadError": ModelStatus.ERROR,
}


class _PreparationWorker(QObject):
    """Loads the model on a background thread and reports one status."""

    finished = Signal(object)

    def __init__(self, provider: LocalModelProvider) -> None:
        super().__init__()
        self._provider = provider

    def run(self) -> None:
        try:
            status = self._provider.prepare()
        except ProviderError as exc:
            status = ProviderStatus(ModelStatus.ERROR, exc.user_message)
        except Exception:  # pragma: no cover - defensive provider failure
            status = ProviderStatus(
                ModelStatus.ERROR, status_message(ModelStatus.ERROR)
            )
        self.finished.emit(status)


class AssistantController(QObject):
    """Single-owner request lifecycle for the desktop composer."""

    status_changed = Signal(object)
    generation_started = Signal(str)
    token_received = Signal(str, str)
    generation_completed = Signal(str, str)
    generation_stopped = Signal(str, str)
    generation_failed = Signal(str, str, str)
    generation_finished = Signal(str)
    # Phase 3: finalized AssistantResponse metadata (route/severity/source).
    response_ready = Signal(str, object)

    def __init__(
        self,
        provider: LocalModelProvider,
        assistant_service=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._assistant_service = assistant_service
        self._status = provider.status()
        self._closed = False
        self._preparing = False
        self._prep_worker: _PreparationWorker | None = None
        self._prep_thread: QThread | None = None
        self._worker: GenerationWorker | None = None
        self._worker_thread: QThread | None = None
        self._active_request_id: str | None = None
        self._terminal_failure: ProviderStatus | None = None
        self.shutdown_incomplete = False

    # -- inspectable state ------------------------------------------------

    def provider(self) -> LocalModelProvider:
        return self._provider

    def assistant_service(self):
        """Return the assistant service this controller owns, if any."""

        return self._assistant_service

    def status(self) -> ProviderStatus:
        return self._status

    def is_generating(self) -> bool:
        return self._active_request_id is not None

    def is_preparing(self) -> bool:
        return self._preparing

    # -- preparation ------------------------------------------------------

    def prepare(self) -> None:
        """Load the model on a background thread without blocking the UI."""

        if self._closed or self._preparing:
            return
        if self._status.state is ModelStatus.READY:
            return

        self._preparing = True
        self._publish(
            ProviderStatus(
                ModelStatus.PREPARING,
                status_message(ModelStatus.PREPARING),
                self._status.model_name,
            )
        )

        worker = _PreparationWorker(self._provider)
        thread = QThread()
        thread.setObjectName("ivyago-preparation")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_prepared)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(self._on_preparation_thread_finished)

        self._prep_worker = worker
        self._prep_thread = thread
        thread.start()

    def _on_prepared(self, status: object) -> None:
        self._preparing = False
        if isinstance(status, ProviderStatus):
            self._publish(status)

    def _on_preparation_thread_finished(self) -> None:
        if self.sender() is self._prep_thread:
            self._prep_worker = None
            self._prep_thread = None

    # -- generation -------------------------------------------------------

    def submit(self, user_prompt: str, system_prompt: str = "") -> bool:
        """Start one generation; return False for empty input or an active one."""

        if self._closed:
            return False

        prompt = (user_prompt or "").strip()
        if not prompt:
            return False
        if self._active_request_id is not None:
            return False

        request_id = str(uuid.uuid4())

        if self._assistant_service is not None:
            # Phase 3: the worker owns prepare → generate → finalize off the
            # Qt thread; the controller never calls the detector/DB directly.
            assistant_request = AssistantRequest(
                request_id=request_id, user_text=prompt
            )
            worker = AssistantGenerationWorker(
                self._provider, self._assistant_service, assistant_request
            )
            completed_slot = self._on_service_completed
        else:
            # Phase 2 direct-prompt path (no service): unchanged behaviour.
            request = GenerationRequest(
                request_id=request_id,
                system_prompt=system_prompt,
                user_prompt=prompt,
            )
            worker = GenerationWorker(self._provider, request)
            completed_slot = self._on_completed

        worker.started.connect(self._on_worker_started)
        worker.token.connect(self._on_token)
        worker.completed.connect(completed_slot)
        worker.stopped.connect(self._on_stopped)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)

        thread = start_generation_thread(worker)
        thread.finished.connect(self._on_worker_thread_finished)

        self._worker = worker
        self._worker_thread = thread
        self._active_request_id = request_id
        self._terminal_failure = None
        return True

    def stop(self) -> bool:
        """Request a cooperative stop for the active generation."""

        worker = self._worker
        if worker is None or self._active_request_id is None:
            return False
        self._publish(
            ProviderStatus(
                ModelStatus.STOPPING,
                status_message(ModelStatus.STOPPING),
                self._status.model_name,
            )
        )
        worker.request_stop()
        return True

    def close(self) -> None:
        """Stop generation, join workers with bounded waits, and close the provider."""

        if self._closed:
            return
        self._closed = True

        worker = self._worker
        if worker is not None:
            try:
                worker.request_stop()
            except Exception:  # pragma: no cover - shutdown must never raise
                pass

        generation_thread = self._worker_thread
        if generation_thread is not None:
            generation_thread.quit()
            if not generation_thread.wait(_GENERATION_SHUTDOWN_MS):
                self.shutdown_incomplete = True
                _ORPHANED_THREADS.append(generation_thread)
                _ORPHANED_WORKERS.append(worker)

        preparation_thread = self._prep_thread
        if preparation_thread is not None:
            preparation_thread.quit()
            if not preparation_thread.wait(_PREPARATION_SHUTDOWN_MS):
                self.shutdown_incomplete = True
                _ORPHANED_THREADS.append(preparation_thread)
                if self._prep_worker is not None:
                    _ORPHANED_WORKERS.append(self._prep_worker)

        self._worker = None
        self._worker_thread = None
        self._prep_worker = None
        self._prep_thread = None
        self._active_request_id = None
        self._preparing = False

        if not self.shutdown_incomplete:
            try:
                self._provider.close()
            except Exception:  # pragma: no cover - closing must never raise
                pass

    # -- worker events ----------------------------------------------------

    def _is_active(self, request_id: str) -> bool:
        return request_id == self._active_request_id

    def _on_worker_started(self, request_id: str) -> None:
        if not self._is_active(request_id):
            return
        self._publish(
            ProviderStatus(
                ModelStatus.GENERATING,
                status_message(ModelStatus.GENERATING),
                self._status.model_name,
            )
        )
        self.generation_started.emit(request_id)

    def _on_token(self, request_id: str, text: str) -> None:
        if not self._is_active(request_id):
            return
        self.token_received.emit(request_id, text)

    def _on_completed(self, request_id: str, text: str) -> None:
        if not self._is_active(request_id):
            return
        self._publish(
            ProviderStatus(
                ModelStatus.READY,
                status_message(ModelStatus.READY),
                self._status.model_name,
            )
        )
        self.generation_completed.emit(request_id, text)

    def _on_service_completed(self, request_id: str, text: str, response) -> None:
        """Finalized service response: publish READY, emit text + metadata."""

        if not self._is_active(request_id):
            return
        self._publish(
            ProviderStatus(
                ModelStatus.READY,
                status_message(ModelStatus.READY),
                self._status.model_name,
            )
        )
        self.generation_completed.emit(request_id, text)
        if response is not None:
            self.response_ready.emit(request_id, response)

    def _on_stopped(self, request_id: str, text: str) -> None:
        if not self._is_active(request_id):
            return
        self._publish(
            ProviderStatus(
                ModelStatus.STOPPED,
                status_message(ModelStatus.STOPPED),
                self._status.model_name,
            )
        )
        self.generation_stopped.emit(request_id, text)

    def _on_failed(self, request_id: str, user_message: str, diagnostic: str) -> None:
        if not self._is_active(request_id):
            return
        kind = diagnostic.split(":", 1)[0].strip()
        state = _TERMINAL_FAILURES.get(kind)
        self._terminal_failure = (
            ProviderStatus(state, user_message, self._status.model_name)
            if state is not None
            else None
        )
        self._publish(
            ProviderStatus(
                ModelStatus.ERROR, user_message, self._status.model_name
            )
        )
        self.generation_failed.emit(request_id, user_message, diagnostic)

    def _on_finished(self, request_id: str) -> None:
        if not self._is_active(request_id):
            return
        self._active_request_id = None

        terminal = self._terminal_failure
        self._terminal_failure = None
        if terminal is not None:
            self._publish(terminal)
        else:
            self._publish(
                ProviderStatus(
                    ModelStatus.READY,
                    status_message(ModelStatus.READY),
                    self._status.model_name,
                )
            )
        self.generation_finished.emit(request_id)

    def _on_worker_thread_finished(self) -> None:
        if self.sender() is self._worker_thread:
            self._worker = None
            self._worker_thread = None

    # -- internals --------------------------------------------------------

    def _publish(self, status: ProviderStatus) -> None:
        self._status = status
        self.status_changed.emit(status)
