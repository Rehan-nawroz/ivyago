"""In-memory chat session store for Ivyago Phase 4.

The store owns the session-only conversation state. It deliberately has no Qt,
SQLite, filesystem, provider, or network dependency: chats exist only for the
life of the process and are discarded when Ivyago closes.

The assistant pipeline remains authoritative for routing, references, prompts,
cleanup, fallbacks, and generation. This module only stores visible messages
plus the public ``AssistantResponse`` metadata the UI is allowed to show.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import TYPE_CHECKING

from ..models import (
    ChatMessage,
    ChatSession,
    MessageRole,
    MessageStatus,
    utc_now,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .assistant_service import AssistantResponse

DEFAULT_TITLE_CHARS = 36
_TITLE_ELLIPSIS = "\u2026"
_MISSING = object()


class ChatSessionStore:
    """Ordered, session-only chats and messages.

    All state lives in private Python collections. Nothing here writes a file,
    opens a database, or imports a provider.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._active_id: str | None = None
        self._order: dict[str, int] = {}
        self._sequence = 0

    # -- sessions ---------------------------------------------------------

    def create_session(self) -> ChatSession:
        """Create a fresh empty session and make it the active one."""

        now = utc_now()
        session = ChatSession(
            session_id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
        )
        self._sessions[session.session_id] = session
        self._active_id = session.session_id
        self._bump(session.session_id)
        return session

    def active_session(self) -> ChatSession:
        """Return the active session, lazily creating an empty draft."""

        if self._active_id is None or self._active_id not in self._sessions:
            return self.create_session()
        return self._sessions[self._active_id]

    def select_session(self, session_id: str) -> ChatSession:
        """Make ``session_id`` active; unknown sessions raise ``KeyError``."""

        if session_id not in self._sessions:
            raise KeyError(session_id)
        self._active_id = session_id
        return self._sessions[session_id]

    def list_sessions(self) -> tuple[ChatSession, ...]:
        """Return non-empty sessions, most recently updated first.

        Blank drafts are excluded so the sidebar never shows empty rows.
        """

        sessions = [s for s in self._sessions.values() if s.messages]
        sessions.sort(
            key=lambda item: (
                item.updated_at,
                self._order.get(item.session_id, 0),
            ),
            reverse=True,
        )
        return tuple(sessions)

    def ensure_draft_session(self) -> ChatSession:
        """Reuse the active empty draft, or create one without listing it."""

        if self._active_id is not None:
            active = self._sessions.get(self._active_id)
            if active is not None and not active.messages:
                return active
        return self.create_session()

    def session(self, session_id: str) -> ChatSession | None:
        """Return one session snapshot without changing the selection."""

        return self._sessions.get(session_id)

    def remove_empty_drafts(self) -> None:
        """Drop abandoned empty sessions; keep the newest real one active."""

        empty = [
            session_id
            for session_id, session in self._sessions.items()
            if not session.messages
        ]
        if not empty:
            return
        for session_id in empty:
            del self._sessions[session_id]
            self._order.pop(session_id, None)
        if self._active_id in empty:
            remaining = self.list_sessions()
            self._active_id = remaining[0].session_id if remaining else None

    def clear_session(self, session_id: str) -> ChatSession:
        """Empty one session in place; the session stays available."""

        if session_id not in self._sessions:
            raise KeyError(session_id)
        cleared = replace(
            self._sessions[session_id],
            title="",
            messages=(),
            updated_at=utc_now(),
        )
        self._sessions[session_id] = cleared
        self._bump(session_id)
        return cleared

    def clear_all(self) -> ChatSession:
        """Remove every in-memory session and create one fresh active draft."""
        self._sessions.clear()
        self._order.clear()
        self._active_id = None
        self._sequence = 0
        return self.create_session()

    # -- messages ---------------------------------------------------------

    def add_user_message(self, session_id: str, text: str) -> ChatMessage:
        """Append one user message; the first one derives the session title."""

        session = self._require(session_id)
        message = ChatMessage(
            message_id=str(uuid.uuid4()),
            role=MessageRole.USER,
            text=text,
            status=MessageStatus.COMPLETED,
        )
        title = session.title
        if not any(m.role is MessageRole.USER for m in session.messages):
            title = self.title_for_text(text)
        self._store_messages(session_id, session.messages + (message,), title)
        return message

    def add_assistant_message(self, session_id: str, message_id: str) -> ChatMessage:
        """Append one streaming assistant placeholder with a caller-owned id."""

        session = self._require(session_id)
        message = ChatMessage(
            message_id=message_id,
            role=MessageRole.ASSISTANT,
            text="",
            status=MessageStatus.STREAMING,
        )
        self._store_messages(session_id, session.messages + (message,))
        return message

    def update_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        status: MessageStatus | None = None,
        response: "AssistantResponse | None" = None,
    ) -> ChatMessage:
        """Replace one message in place and return the updated value.

        When ``response`` is supplied only its public fields are copied:
        source, route, severity, critical override, and reference availability.
        Prompts, keyword matches, and raw rows are never stored.
        """

        found = self.find_message(message_id)
        if found is None:
            raise KeyError(message_id)
        session, message = found

        changes: dict[str, object] = {}
        if text is not None:
            changes["text"] = text
        if status is not None:
            changes["status"] = status
        if response is not None:
            changes["source"] = str(getattr(response, "source", "") or "")
            changes["route"] = str(getattr(response, "route", "") or "")
            changes["severity"] = str(getattr(response, "severity", "") or "")
            changes["critical_override"] = bool(
                getattr(response, "critical_override", False)
            )
            changes["reference_available"] = bool(
                getattr(response, "reference_available", False)
            )

        updated = replace(message, **changes) if changes else message
        messages = tuple(
            updated if item.message_id == message_id else item
            for item in session.messages
        )

        # Editing the first user message re-derives the sidebar title.
        title: object = _MISSING
        if text is not None and message.role is MessageRole.USER:
            first_user = next(
                (item for item in session.messages if item.role is MessageRole.USER),
                None,
            )
            if first_user is not None and first_user.message_id == message_id:
                title = self.title_for_text(text)
        self._store_messages(session.session_id, messages, title)
        return updated

    def reset_message(
        self,
        message_id: str,
        *,
        text: str = "",
        status: MessageStatus = MessageStatus.STREAMING,
    ) -> ChatMessage:
        """Clear finalized metadata for a retried or stopped assistant message."""

        found = self.find_message(message_id)
        if found is None:
            raise KeyError(message_id)
        session, message = found
        updated = replace(
            message,
            text=text,
            status=status,
            source="",
            route="",
            severity="",
            critical_override=False,
            reference_available=False,
        )
        messages = tuple(
            updated if item.message_id == message_id else item
            for item in session.messages
        )
        self._store_messages(session.session_id, messages)
        return updated

    def find_message(self, message_id: str) -> tuple[ChatSession, ChatMessage] | None:
        """Return the owning session and message for ``message_id``."""

        for session in self._sessions.values():
            for message in session.messages:
                if message.message_id == message_id:
                    return session, message
        return None

    def truncate_after(self, message_id: str) -> ChatSession:
        """Keep messages up to and including ``message_id``; drop the rest."""

        found = self.find_message(message_id)
        if found is None:
            raise KeyError(message_id)
        session, message = found
        kept: list[ChatMessage] = []
        for item in session.messages:
            kept.append(item)
            if item.message_id == message.message_id:
                break
        return self._store_messages(session.session_id, tuple(kept))

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def title_for_text(text: str, max_chars: int = DEFAULT_TITLE_CHARS) -> str:
        """Collapse whitespace and truncate a sidebar title safely."""

        collapsed = " ".join((text or "").split())
        if not collapsed:
            return ""
        if len(collapsed) <= max_chars:
            return collapsed
        return collapsed[:max_chars].rstrip() + _TITLE_ELLIPSIS

    def _require(self, session_id: str) -> ChatSession:
        try:
            return self._sessions[session_id]
        except KeyError:
            raise KeyError(session_id) from None

    def _store_messages(
        self,
        session_id: str,
        messages: tuple[ChatMessage, ...],
        title: object = _MISSING,
    ) -> ChatSession:
        session = self._require(session_id)
        updated = replace(
            session,
            messages=tuple(messages),
            title=session.title if title is _MISSING else str(title),
            updated_at=utc_now(),
        )
        self._sessions[session_id] = updated
        self._bump(session_id)
        return updated

    def _bump(self, session_id: str) -> None:
        self._sequence += 1
        self._order[session_id] = self._sequence
