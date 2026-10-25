"""Runtime-independent contracts for Ivyago's local model providers.

Nothing in this module imports Qt, performs I/O, or knows which embedded runtime
is installed. The provider boundary is deliberately small so the Assist view and
the controller can be tested with fake providers and so a future runtime swap
does not touch the UI.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class ModelStatus(str, Enum):
    """Lifecycle and failure states for the local assistant."""

    NOT_READY = "not_ready"
    PREPARING = "preparing"
    READY = "ready"
    GENERATING = "generating"
    STOPPING = "stopping"
    STOPPED = "stopped"
    MODEL_MISSING = "model_missing"
    MODEL_CORRUPT = "model_corrupt"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


# Calm, local, user-facing copy. The UI shows ``detail`` when a provider supplies
# one and falls back to these strings, so every failure reads the same way in the
# composer note and in the response area.
STATUS_MESSAGES = {
    ModelStatus.NOT_READY: "The bundled offline assistant is not ready.",
    ModelStatus.PREPARING: "Preparing the offline assistant for first use.",
    ModelStatus.READY: "Offline assistant ready.",
    ModelStatus.GENERATING: "Generating a local response\u2026",
    ModelStatus.STOPPING: "Stopping the response\u2026",
    ModelStatus.STOPPED: "Generation stopped.",
    ModelStatus.MODEL_MISSING: "The offline assistant model is missing from this installation.",
    ModelStatus.MODEL_CORRUPT: "The offline assistant model is damaged or incomplete.",
    ModelStatus.UNSUPPORTED: "This computer cannot run the offline assistant.",
    ModelStatus.ERROR: "The offline assistant stopped unexpectedly.",
}

FAILURE_STATES = frozenset(
    {
        ModelStatus.MODEL_MISSING,
        ModelStatus.MODEL_CORRUPT,
        ModelStatus.UNSUPPORTED,
        ModelStatus.ERROR,
    }
)


def status_message(state: ModelStatus, detail: str | None = None) -> str:
    """Return the display copy for ``state``, preferring a provider detail."""

    if detail:
        return detail
    return STATUS_MESSAGES[state]


@dataclass(frozen=True)
class ProviderStatus:
    """An immutable snapshot of a provider's readiness."""

    state: ModelStatus
    detail: str | None = None
    model_name: str | None = None


@dataclass(frozen=True)
class GenerationRequest:
    """One local generation request: prompt data and an identifier only."""

    request_id: str
    system_prompt: str
    user_prompt: str


class ProviderError(Exception):
    """Base class for typed, user-safe local provider failures."""

    user_message = "The local assistant could not complete that request."

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.user_message)
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.detail or self.user_message


class ModelMissingError(ProviderError):
    """The configured model file does not exist."""

    user_message = "The offline assistant model is missing from this installation."


class ModelCorruptError(ProviderError):
    """The model file exists but is empty, the wrong size, or the wrong hash."""

    user_message = "The offline assistant model is damaged or incomplete."


class RuntimeUnsupportedError(ProviderError):
    """No embedded runtime is available on this machine."""

    user_message = "This computer cannot run the offline assistant."


class ModelLoadError(ProviderError):
    """The embedded runtime could not open the model."""

    user_message = "The offline assistant could not load its model."


class GenerationError(ProviderError):
    """Generation failed after the model was ready."""

    user_message = "The offline assistant could not finish that response."


class GenerationStopped(ProviderError):
    """A generation was stopped by the user."""

    user_message = "Generation stopped."


@runtime_checkable
class LocalModelProvider(Protocol):
    """Runtime-independent contract implemented by every local provider."""

    def status(self) -> ProviderStatus: ...

    def prepare(self) -> ProviderStatus: ...

    def generate(
        self,
        request: GenerationRequest,
        on_token: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ) -> str: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...
