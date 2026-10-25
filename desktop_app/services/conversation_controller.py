"""Conversation orchestration for the Ivyago Phase 4 chat experience.

``ConversationController`` sits between the session store and the existing
``AssistantController``. It owns conversation-level behaviour only:

  * active-chat selection and New Chat,
  * user/assistant message creation,
  * mapping exactly one active generation to exactly one assistant message,
  * Edit, Retry, Copy, Clear, and Stop orchestration.

It never performs detector, database, prompt, cleanup, fallback, or model work.
Those remain in ``AssistantService``/``AssistantGenerationWorker`` and the
provider. Chat state lives only in memory for the current process.
"""

from __future__ import annotations

import uuid

from PySide6.QtCore import QObject, Signal

from ..models import ChatSession, MessageRole, MessageStatus
from .chat_session_store import ChatSessionStore

_NOT_READY = "The offline assistant could not start that request."
_GENERATION_ERROR = "The offline assistant could not finish that response."
_STALE_IGNORED = object()


class ConversationController(QObject):
    """Session selection plus one-generation-at-a-time conversation actions."""

    sessions_changed = Signal(object)        # tuple[ChatSession, ...]
    active_session_changed = Signal(object)  # ChatSession
    message_added = Signal(object)           # ChatMessage
    message_updated = Signal(object)         # ChatMessage
    generation_state_changed = Signal(str)   # "generating" | "idle"
    error_changed = Signal(str)

    def __init__(
        self,
        store: ChatSessionStore,
        assistant_controller,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._assistant = assistant_controller
        self._active_request_id: str | None = None
        self._active_session_id: str | None = None
        self._active_user_message_id: str | None = None
        self._active_message_id: str | None = None
        self._edit_message_id: str | None = None
        self._generating = False

        assistant_controller.generation_started.connect(self._on_generation_started)
        assistant_controller.token_received.connect(self._on_token)
        assistant_controller.generation_completed.connect(self._on_completed)
        assistant_controller.generation_stopped.connect(self._on_stopped)
        assistant_controller.generation_failed.connect(self._on_failed)
        assistant_controller.response_ready.connect(self._on_response_ready)
        assistant_controller.generation_finished.connect(self._on_generation_finished)

    # -- inspectable state ------------------------------------------------

    def store(self) -> ChatSessionStore:
        return self._store

    def assistant_controller(self):
        """Return the generation controller this conversation delegates to."""

        return self._assistant

    def active_session(self) -> ChatSession:
        return self._store.active_session()

    def sessions(self) -> tuple[ChatSession, ...]:
        return self._store.list_sessions()

    def is_generating(self) -> bool:
        return self._generating or bool(self._assistant.is_generating())

    # -- session actions --------------------------------------------------

    def new_chat(self) -> ChatSession:
        """Start (or reuse) a blank chat; blocked while a response is active."""

        if self.is_generating():
            return self._store.active_session()
        self._edit_message_id = None
        session = self._store.ensure_draft_session()
        self._active_session_id = session.session_id
        self.active_session_changed.emit(session)
        self.sessions_changed.emit(self._store.list_sessions())
        return session

    def select_chat(self, session_id: str) -> bool:
        """Select a stored chat; never allowed to orphan an active request."""

        if self.is_generating():
            return False
        try:
            session = self._store.select_session(session_id)
        except KeyError:
            return False
        self._edit_message_id = None
        self._active_session_id = session.session_id
        self.active_session_changed.emit(session)
        self.sessions_changed.emit(self._store.list_sessions())
        return True

    # -- generation -------------------------------------------------------

    def submit(self, text: str) -> bool:
        """Append one user message and one streaming assistant message."""

        prompt = (text or "").strip()
        if not prompt or self.is_generating():
            return False

        session = self._store.active_session()
        user = self._store.add_user_message(session.session_id, prompt)
        assistant = self._store.add_assistant_message(
            session.session_id, str(uuid.uuid4())
        )
        self._edit_message_id = None

        self.message_added.emit(user)
        self.message_added.emit(assistant)
        self.sessions_changed.emit(self._store.list_sessions())

        return self._begin_generation(
            session.session_id, user.message_id, assistant.message_id, prompt
        )

    def stop(self) -> bool:
        """Delegate a cooperative stop to the assistant controller."""

        if not self._generating:
            return False
        return bool(self._assistant.stop())

    # -- message actions --------------------------------------------------

    def edit_user_message(self, message_id: str) -> str | None:
        """Return the edited text for the composer; never starts generation."""

        found = self._store.find_message(message_id)
        if found is None:
            return None
        session, message = found
        if message.role is not MessageRole.USER:
            return None
        if session.session_id != self._store.active_session().session_id:
            return None
        self._edit_message_id = message_id
        return message.text

    def confirm_edited_submission(self, text: str) -> bool:
        """Supersede later turns and generate from the edited user message."""

        prompt = (text or "").strip()
        if not prompt or self.is_generating():
            return False
        if self._edit_message_id is None:
            return False

        found = self._store.find_message(self._edit_message_id)
        if found is None:
            self._edit_message_id = None
            return False
        session, message = found
        if (
            message.role is not MessageRole.USER
            or session.session_id != self._store.active_session().session_id
        ):
            self._edit_message_id = None
            return False

        user = self._store.update_message(message.message_id, text=prompt)
        self._store.truncate_after(message.message_id)
        assistant = self._store.add_assistant_message(
            session.session_id, str(uuid.uuid4())
        )
        self._edit_message_id = None

        refreshed = self._store.session(session.session_id)
        if refreshed is not None:
            # The later turns were removed; rebuild that thread from the store.
            self.active_session_changed.emit(refreshed)
        self.sessions_changed.emit(self._store.list_sessions())

        return self._begin_generation(
            session.session_id,
            user.message_id,
            assistant.message_id,
            prompt,
        )

    def retry_assistant_message(self, message_id: str) -> bool:
        """Re-run the associated user message, replacing one assistant result."""

        if self.is_generating():
            return False
        found = self._store.find_message(message_id)
        if found is None:
            return False
        session, message = found
        if message.role is not MessageRole.ASSISTANT:
            return False
        if session.session_id != self._store.active_session().session_id:
            return False

        user_message = None
        for item in session.messages:
            if item.message_id == message_id:
                break
            if item.role is MessageRole.USER:
                user_message = item
        if user_message is None:
            return False

        reset = self._store.reset_message(
            message.message_id, status=MessageStatus.STREAMING
        )
        self._edit_message_id = None
        self.message_updated.emit(reset)
        self.sessions_changed.emit(self._store.list_sessions())

        return self._begin_generation(
            session.session_id,
            user_message.message_id,
            message.message_id,
            user_message.text,
        )

    def copy_assistant_message(self, message_id: str) -> str | None:
        """Return only the finalized visible assistant text."""

        found = self._store.find_message(message_id)
        if found is None:
            return None
        message = found[1]
        if message.role is not MessageRole.ASSISTANT:
            return None
        if message.status is not MessageStatus.COMPLETED:
            return None
        return message.text.strip() or None

    def clear_active_chat(self) -> bool:
        """Clear only the active chat after the caller confirmed it."""

        if self.is_generating():
            return False
        session = self._store.active_session()
        cleared = self._store.clear_session(session.session_id)
        self._edit_message_id = None
        self.active_session_changed.emit(cleared)
        self.sessions_changed.emit(self._store.list_sessions())
        return True

    def clear_all_chats(self) -> bool:
        """Clear all sessions, leaving one fresh draft, when idle."""
        if self.is_generating():
            return False
        self._edit_message_id = None
        session = self._store.clear_all()
        self._active_session_id = session.session_id
        self.active_session_changed.emit(session)
        self.sessions_changed.emit(self._store.list_sessions())
        return True

    # -- generation lifecycle --------------------------------------------

    def _begin_generation(
        self,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
        prompt: str,
    ) -> bool:
        self._active_session_id = session_id
        self._active_user_message_id = user_message_id
        self._active_message_id = assistant_message_id
        self._active_request_id = None
        self._generating = True
        self.generation_state_changed.emit("generating")

        if not self._assistant.submit(prompt):
            self._fail_active(_NOT_READY, emit_error=True)
            return False
        return True

    def _is_active(self, request_id: str) -> bool:
        return (
            self._generating
            and self._active_message_id is not None
            and request_id == self._active_request_id
        )

    def _on_generation_started(self, request_id: str) -> None:
        if not self._generating or self._active_message_id is None:
            return
        if self._active_request_id is None:
            self._active_request_id = request_id

    def _on_token(self, request_id: str, text: str) -> None:
        if not text or not self._is_active(request_id):
            return
        message_id = self._active_message_id
        if message_id is None:
            return
        found = self._store.find_message(message_id)
        if found is None:
            return
        updated = self._store.update_message(
            message_id, text=found[1].text + text
        )
        self.message_updated.emit(updated)

    def _on_completed(self, request_id: str, text: str) -> None:
        if not self._is_active(request_id):
            return
        message_id = self._active_message_id
        if message_id is None:
            return
        updated = self._store.update_message(
            message_id, text=text, status=MessageStatus.COMPLETED
        )
        self.message_updated.emit(updated)
        self.sessions_changed.emit(self._store.list_sessions())

    def _on_response_ready(self, request_id: str, response) -> None:
        if not self._is_active(request_id) or response is None:
            return
        message_id = self._active_message_id
        if message_id is None:
            return
        updated = self._store.update_message(
            message_id,
            text=getattr(response, "text", None),
            status=MessageStatus.COMPLETED,
            response=response,
        )
        self.message_updated.emit(updated)
        self.sessions_changed.emit(self._store.list_sessions())

    def _on_stopped(self, request_id: str, text: str) -> None:
        if not self._is_active(request_id):
            return
        message_id = self._active_message_id
        if message_id is None:
            return
        updated = self._store.reset_message(
            message_id, text=text or "", status=MessageStatus.STOPPED
        )
        self.message_updated.emit(updated)
        self.sessions_changed.emit(self._store.list_sessions())

    def _on_failed(
        self, request_id: str, user_message: str, _diagnostic: str
    ) -> None:
        if not self._is_active(request_id):
            return
        self._fail_active(user_message or _GENERATION_ERROR, emit_error=True)

    def _on_generation_finished(self, request_id: str) -> None:
        if request_id != self._active_request_id:
            return
        self._generating = False
        self._active_request_id = None
        self._active_user_message_id = None
        self._active_message_id = None
        self.generation_state_changed.emit("idle")

    # -- internals --------------------------------------------------------

    def _fail_active(self, message: str, *, emit_error: bool) -> None:
        message_id = self._active_message_id
        self._generating = False
        self._active_request_id = None
        self._active_user_message_id = None
        self._active_message_id = None
        if message_id is not None:
            found = self._store.find_message(message_id)
            text = (found[1].text if found is not None else "") or message
            updated = self._store.reset_message(
                message_id, text=text, status=MessageStatus.FAILED
            )
            self.message_updated.emit(updated)
            self.sessions_changed.emit(self._store.list_sessions())
        if emit_error and message:
            self.error_changed.emit(message)
        self.generation_state_changed.emit("idle")
