"""Typed values shared by the desktop shell."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class NavigationDestination(str, Enum):
    """Top-level destinations available in the desktop shell."""

    ASSIST = "assist"
    HISTORY = "history"
    SETTINGS = "settings"


@dataclass(frozen=True)
class AppMetadata:
    """Static application metadata used by Qt and the shell."""

    application_name: str
    organization_name: str
    version: str


# Stable source identifiers for a finalized assistant response. These are the
# only values ``AssistantResponse.source`` may take. They live here (shared
# UI-facing metadata) so the assistant service and the Assist view agree on one
# canonical set without the view importing the service. Kept dependency-free.
SOURCE_OFFLINE_ASSISTANT = "offline_assistant"
SOURCE_LOCAL_REFERENCE_USED = "local_reference_used"
SOURCE_EMERGENCY_NUMBER_REFERENCE_USED = "emergency_number_reference_used"
SOURCE_LOCAL_REFERENCE_UNAVAILABLE = "local_reference_unavailable"

SOURCE_IDENTIFIERS = frozenset(
    {
        SOURCE_OFFLINE_ASSISTANT,
        SOURCE_LOCAL_REFERENCE_USED,
        SOURCE_EMERGENCY_NUMBER_REFERENCE_USED,
        SOURCE_LOCAL_REFERENCE_UNAVAILABLE,
    }
)

# Quiet human labels for each source identifier. The Phase 1.5 visual system
# forbids severity banners / traffic lights, so these render as a single muted
# line under the answer.
SOURCE_LABELS = {
    SOURCE_OFFLINE_ASSISTANT: "Offline assistant",
    SOURCE_LOCAL_REFERENCE_USED: "Local reference used",
    SOURCE_EMERGENCY_NUMBER_REFERENCE_USED: "Emergency-number reference used",
    SOURCE_LOCAL_REFERENCE_UNAVAILABLE: "Local reference unavailable",
}

# The one approved beta caveat. It is rendered quietly under every COMPLETED
# assistant response (general, emergency, medicine, and fallback alike) and is
# never a dialog, banner, or traffic-light severity indicator. Stopped partial
# responses stay unfinalized and therefore do not render it.
UNIVERSAL_CAUTION = (
    "Caution: Ivyago is an AI assistant in beta testing, not a substitute for "
    "professional medical or emergency advice. Always verify important "
    "guidance with a qualified professional or local emergency service."
)


# --- Session-only conversation values (Phase 4) --------------------------


def utc_now() -> datetime:
    """Return the timezone-aware UTC timestamp used by conversation values."""

    return datetime.now(timezone.utc)


class MessageRole(str, Enum):
    """Who authored one conversation message."""

    USER = "user"
    ASSISTANT = "assistant"


class MessageStatus(str, Enum):
    """Lifecycle of one conversation message."""

    DRAFT = "draft"
    STREAMING = "streaming"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class ChatMessage:
    """One immutable conversation message.

    Assistant metadata is deliberately limited to the public
    ``AssistantResponse`` fields the UI may need. Prompts, matched keywords,
    raw database rows, provider handles, and diagnostics are never stored here.
    """

    message_id: str
    role: MessageRole
    text: str = ""
    created_at: datetime = field(default_factory=utc_now)
    status: MessageStatus = MessageStatus.DRAFT
    source: str = ""
    route: str = ""
    severity: str = ""
    critical_override: bool = False
    reference_available: bool = False


@dataclass(frozen=True)
class ChatSession:
    """One in-memory chat session with its ordered messages.

    The store replaces this value on every change, so widgets may safely keep
    the snapshot they were rendered from.
    """

    session_id: str
    title: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    messages: tuple[ChatMessage, ...] = ()
