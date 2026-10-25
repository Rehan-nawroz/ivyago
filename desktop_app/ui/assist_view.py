"""The Assist page: session-aware conversation thread, hero, and composer.

The view is presentation only. It renders the immutable message snapshots a
``ConversationController`` publishes and delegates every action (submit, stop,
edit, retry, copy, clear) back to that controller. It never imports a runtime
binding, reads a model file, calls a provider, or touches SQLite.

Session chats are in memory only: the view keeps no persistent state and
re-renders from the store snapshot on every session change.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..models import (
    SOURCE_LABELS,
    UNIVERSAL_CAUTION,
    ChatMessage,
    ChatSession,
    MessageRole,
    MessageStatus,
)
from ..services.chat_session_store import ChatSessionStore
from ..services.conversation_controller import ConversationController
from ..services.model_provider import (
    FAILURE_STATES,
    STATUS_MESSAGES,
    ModelStatus,
    ProviderStatus,
    status_message,
)
from . import assets, icons, motion, theme
from .backdrop import BackdropFrame

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..services.assistant_controller import AssistantController

_AVATAR_SIZE = 128
_AVATAR_MARK_HEIGHT = 106
_DISCONNECTED_NOTE = "Assistant chat is not connected yet."
_READY_HINT = "Offline assistant ready."
_EDIT_HINT = "Editing your message \u2014 press Enter to resubmit."
_COPIED_HINT = "Copied"
_COPY_HINT = "Copy response"
_STREAMING_HINT = "Responding\u2026"


def format_time(created_at: datetime) -> str:
    """Return the quiet local timestamp shown under one message."""

    try:
        local = created_at.astimezone()
    except (ValueError, OSError):  # pragma: no cover - rare platform detail
        local = created_at
    return local.strftime("%H:%M")


def _action_button(
    parent: QWidget,
    icon_name: str,
    accessible_name: str,
    tooltip: str,
) -> QPushButton:
    button = QPushButton(parent)
    button.setObjectName("messageAction")
    button.setFixedSize(theme.MESSAGE_ACTION_SIZE, theme.MESSAGE_ACTION_SIZE)
    button.setIconSize(QSize(14, 14))
    button.setIcon(
        icons.icon(
            icon_name,
            theme.TEXT_MUTED,
            14,
            active_tint=theme.TEXT_BODY,
        )
    )
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    button.setAutoDefault(False)
    button.setAccessibleName(accessible_name)
    button.setToolTip(tooltip)
    return button


class _MessageBody(QPlainTextEdit):
    """Read-only, self-sizing message text that keeps line breaks intact."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("messageBody")
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAccessibleName("Assistant response")
        self.setCursorWidth(0)

    def refresh_height(self) -> None:
        # QPlainTextEdit wraps at the viewport, so measure the wrapped text.
        width = self.viewport().width()
        if width < 60:
            width = max(60, self.width() - 8)
        metrics = QFontMetrics(self.font())
        bounds = metrics.boundingRect(
            QRect(0, 0, width, 1000000),
            int(Qt.TextFlag.TextWordWrap | Qt.TextFlag.TextExpandTabs),
            self.toPlainText(),
        )
        margin = int(self.document().documentMargin()) * 2
        # One line of slack: the document's line spacing can exceed the
        # font metric estimate, and a clipped last line is never acceptable.
        height = max(24, bounds.height() + margin + metrics.lineSpacing())
        if self.height() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event) -> None:  # noqa: D401 - Qt override
        super().resizeEvent(event)
        self.refresh_height()

    def set_response(self, text: str) -> None:
        if self.toPlainText() == text:
            self.refresh_height()
            return
        self.setPlainText(text)
        self.refresh_height()
        if text:
            self.moveCursor(QTextCursor.MoveOperation.End)


class _UserMessage(QWidget):
    """Right-aligned blue-gray user bubble with its edit action."""

    edit_requested = Signal(str)

    def __init__(self, message: ChatMessage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("userMessageRow")
        self.message = message

        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(0)
        self.row.addStretch(1)

        self.column = QWidget(self)
        self.column.setObjectName("userMessageColumn")
        self.column.setMaximumWidth(theme.CHAT_BUBBLE_MAX_WIDTH)
        self.column.setMinimumWidth(160)

        column = QVBoxLayout(self.column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        self.bubble = QFrame(self.column)
        self.bubble.setObjectName("userBubble")

        bubble = QVBoxLayout(self.bubble)
        bubble.setContentsMargins(16, 12, 16, 12)
        bubble.setSpacing(0)

        self.text_label = QLabel(message.text, self.bubble)
        self.text_label.setObjectName("userMessageText")
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.text_label.setAccessibleName("Your message")
        bubble.addWidget(self.text_label)

        meta = QWidget(self.column)
        meta.setObjectName("userMessageMeta")
        meta_row = QHBoxLayout(meta)
        meta_row.setContentsMargins(2, 0, 2, 0)
        meta_row.setSpacing(4)
        meta_row.addStretch(1)

        self.time_label = QLabel(format_time(message.created_at), meta)
        self.time_label.setObjectName("messageTime")
        self.time_label.setAccessibleName("Message time")

        self.edit_button = _action_button(
            meta, "edit", "Edit message", "Edit this message"
        )
        self.edit_button.clicked.connect(
            lambda: self.edit_requested.emit(self.message.message_id)
        )

        meta_row.addWidget(self.time_label, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addWidget(self.edit_button, 0, Qt.AlignmentFlag.AlignVCenter)

        column.addWidget(self.bubble)
        column.addWidget(meta)
        self.row.addWidget(self.column)

    def set_message(self, message: ChatMessage) -> None:
        self.message = message
        self.text_label.setText(message.text)
        self.time_label.setText(format_time(message.created_at))


class _AssistantMessage(QWidget):
    """Left-aligned dark assistant card: body, source, actions, caution."""

    retry_requested = Signal(str)
    copy_requested = Signal(str)

    def __init__(self, message: ChatMessage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("assistantMessageRow")
        self.message = message

        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(0)

        self.column = QWidget(self)
        self.column.setObjectName("assistantMessageColumn")
        self.column.setMaximumWidth(theme.CHAT_BUBBLE_MAX_WIDTH)
        self.column.setMinimumWidth(280)

        column = QVBoxLayout(self.column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        self.bubble = QFrame(self.column)
        self.bubble.setObjectName("assistantBubble")
        bubble = QVBoxLayout(self.bubble)
        bubble.setContentsMargins(16, 12, 16, 10)
        bubble.setSpacing(6)

        self.body = _MessageBody(self.bubble)

        meta = QWidget(self.bubble)
        meta.setObjectName("assistantMessageMeta")
        meta_row = QHBoxLayout(meta)
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(4)

        self.source_note = QLabel("", meta)
        self.source_note.setObjectName("messageSource")
        self.source_note.setVisible(False)
        self.source_note.setAccessibleName("Answer source")

        self.streaming_note = QLabel(_STREAMING_HINT, meta)
        self.streaming_note.setObjectName("messageStreaming")
        self.streaming_note.setAccessibleName("Assistant is responding")
        self.streaming_note.setVisible(False)

        self.time_label = QLabel(format_time(message.created_at), meta)
        self.time_label.setObjectName("messageTime")
        self.time_label.setAccessibleName("Message time")

        self.copy_button = _action_button(
            meta, "copy", "Copy response", _COPY_HINT
        )
        self.copy_button.clicked.connect(self._request_copy)

        self.retry_button = _action_button(
            meta, "retry", "Retry response", "Retry this response"
        )
        self.retry_button.clicked.connect(self._request_retry)

        meta_row.addWidget(self.source_note, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addWidget(self.streaming_note, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addStretch(1)
        meta_row.addWidget(self.time_label, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignVCenter)
        meta_row.addWidget(self.retry_button, 0, Qt.AlignmentFlag.AlignVCenter)

        bubble.addWidget(self.body)
        bubble.addWidget(meta)

        self.caution_label = QLabel(UNIVERSAL_CAUTION, self.column)
        self.caution_label.setObjectName("messageCaution")
        self.caution_label.setWordWrap(True)
        self.caution_label.setVisible(False)
        self.caution_label.setAccessibleName("AI beta caution")
        self.caution_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        column.addWidget(self.bubble)
        column.addWidget(self.caution_label)
        self.row.addWidget(self.column)
        self.row.addStretch(1)

        self.set_message(message)

    def set_message(self, message: ChatMessage) -> None:
        self.message = message
        self.body.set_response(message.text)
        self.time_label.setText(format_time(message.created_at))

        completed = message.status is MessageStatus.COMPLETED
        label = SOURCE_LABELS.get(message.source, "") if completed else ""
        self.source_note.setText(label)
        self.source_note.setVisible(completed and bool(label))
        self.caution_label.setVisible(completed)
        self.copy_button.setVisible(completed)
        self.retry_button.setVisible(completed)
        self.streaming_note.setVisible(message.status is MessageStatus.STREAMING)

    def show_copied(self) -> None:
        self.copy_button.setToolTip(_COPIED_HINT)
        self.copy_button.setAccessibleDescription("Response copied to clipboard")
        QTimer.singleShot(1500, self._restore_copy_hint)

    def _restore_copy_hint(self) -> None:
        try:
            self.copy_button.setToolTip(_COPY_HINT)
            self.copy_button.setAccessibleDescription("")
        except RuntimeError:  # pragma: no cover - widget already deleted
            pass

    def _request_copy(self) -> None:
        self.copy_requested.emit(self.message.message_id)

    def _request_retry(self) -> None:
        self.retry_requested.emit(self.message.message_id)


class AssistView(BackdropFrame):
    """Empty hero, session conversation thread, and the Phase 2 composer."""

    page_title = "Assist"

    def __init__(
        self,
        conversation_controller: ConversationController | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._conversation: ConversationController | None = None
        self._controller: AssistantController | None = None
        self._status = ProviderStatus(ModelStatus.NOT_READY, _DISCONNECTED_NOTE)
        self._sticky_note = ""
        self._sticky_tone = "quiet"
        self._editing_message_id: str | None = None
        self._pending_prompt = ""
        self._message_widgets: dict[str, QWidget] = {}
        self._bubble_width = theme.CHAT_BUBBLE_MAX_WIDTH
        self._follow_bottom = True
        self._auto_scrolling = False
        self._stop_was_visible = False
        self.last_copied_text: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.CONTENT_PADDING,
            theme.SPACING_UNIT * 2,
            theme.CONTENT_PADDING,
            theme.SPACING_UNIT * 2,
        )
        layout.setSpacing(0)

        layout.addWidget(self._build_status_row())
        self.content_stack = QStackedWidget(self)
        self.content_stack.setObjectName("assistContentStack")
        self.empty_page = self._build_empty_page()
        self.thread_page = self._build_thread_page()
        self.content_stack.addWidget(self.empty_page)
        self.content_stack.addWidget(self.thread_page)
        layout.addWidget(self.content_stack, 1)
        layout.addWidget(self._build_composer(), 0, Qt.AlignmentFlag.AlignHCenter)

        self._apply_status(self._status)
        if conversation_controller is not None:
            if _is_conversation_controller(conversation_controller):
                self.set_conversation_controller(conversation_controller)
            else:  # backwards-compatible: wrap a bare AssistantController
                self.set_conversation_controller(
                    ConversationController(
                        ChatSessionStore(), conversation_controller, self
                    )
                )

    # -- construction -----------------------------------------------------

    def _build_status_row(self) -> QWidget:
        row = QWidget(self)
        row.setObjectName("statusRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(1)

        self.status_pill = QFrame(row)
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setAccessibleName("Safe and secure")

        pill = QHBoxLayout(self.status_pill)
        pill.setContentsMargins(10, 5, 12, 5)
        pill.setSpacing(6)

        shield = QLabel(self.status_pill)
        shield.setPixmap(icons.pixmap("shield", theme.TEXT_SECONDARY, 14))
        shield.setFixedSize(14, 14)

        caption = QLabel("Safe & Secure", self.status_pill)
        caption.setObjectName("statusText")

        pill.addWidget(shield)
        pill.addWidget(caption)
        layout.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _build_empty_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("emptyStatePage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch(1)
        self.hero = self._build_hero(page)
        layout.addWidget(self.hero, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        return page

    def _build_hero(self, parent: QWidget) -> QWidget:
        hero = QWidget(parent)
        hero.setObjectName("heroGreeting")

        row = QHBoxLayout(hero)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACING_UNIT * 4)
        row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.avatar = QLabel(hero)
        self.avatar.setObjectName("heroAvatar")
        self.avatar.setFixedSize(_AVATAR_SIZE, _AVATAR_SIZE)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avatar.setAccessibleName("Ivyago assistant")
        try:
            self.avatar.setPixmap(assets.brand_mark(_AVATAR_MARK_HEIGHT))
        except (FileNotFoundError, OSError):
            self.avatar.setText("Ivyago")

        glow = QGraphicsDropShadowEffect(self.avatar)
        glow.setBlurRadius(56)
        glow.setOffset(0, 0)
        glow.setColor(QColor(230, 20, 35, 150))
        self.avatar.setGraphicsEffect(glow)

        text_column = QWidget(hero)
        column = QVBoxLayout(text_column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SPACING_UNIT - 2)

        self.hero_title = QLabel(
            '<span style="color:#FFFFFF;">Hello, I\'m </span>'
            '<span style="color:#FF1124;">Ivyago</span>',
            text_column,
        )
        self.hero_title.setObjectName("heroGreeting")
        self.hero_title.setTextFormat(Qt.TextFormat.RichText)
        self.hero_title.setAccessibleName("Hello, I'm Ivyago")

        self.hero_subtitle = QLabel("Your AI emergency assistant.", text_column)
        self.hero_subtitle.setObjectName("heroSubtitle")

        self.hero_body = QLabel(
            "I can help you with medical guidance, first aid steps, emergency "
            "numbers, survival tips and more \u2014 anytime, anywhere.",
            text_column,
        )
        self.hero_body.setObjectName("heroBody")
        self.hero_body.setWordWrap(True)
        self.hero_body.setFixedWidth(theme.HERO_TEXT_MAX_WIDTH)

        column.addWidget(self.hero_title)
        column.addWidget(self.hero_subtitle)
        column.addWidget(self.hero_body)

        row.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(text_column, 0, Qt.AlignmentFlag.AlignVCenter)
        return hero

    def _build_thread_page(self) -> QWidget:
        page = QWidget(self)
        page.setObjectName("threadPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.conversation_thread = QScrollArea(page)
        self.conversation_thread.setObjectName("conversationThread")
        self.conversation_thread.setWidgetResizable(True)
        self.conversation_thread.setFrameShape(QFrame.Shape.NoFrame)
        self.conversation_thread.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.conversation_thread.setAccessibleName("Conversation")

        self.thread_body = QWidget()
        self.thread_body.setObjectName("threadBody")
        body = QHBoxLayout(self.thread_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addStretch(1)

        self.thread_content = QWidget(self.thread_body)
        self.thread_content.setObjectName("threadContent")
        self.thread_content.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum
        )
        self._message_layout = QVBoxLayout(self.thread_content)
        self._message_layout.setContentsMargins(0, 4, 0, 4)
        self._message_layout.setSpacing(theme.SPACING_UNIT + 6)
        self._message_layout.addStretch(1)

        body.addWidget(self.thread_content)
        body.addStretch(1)
        self.conversation_thread.setWidget(self.thread_body)
        scroll_bar = self.conversation_thread.verticalScrollBar()
        scroll_bar.rangeChanged.connect(self._on_range_changed)
        scroll_bar.valueChanged.connect(self._on_scroll_value_changed)
        layout.addWidget(self.conversation_thread)

        # Compatibility placeholders for the Phase 3 single-response API.
        self._empty_response_view = _MessageBody(self)
        self._empty_response_view.setVisible(False)
        self._empty_response_panel = QFrame(self)
        self._empty_response_panel.setVisible(False)
        self._empty_source_note = QLabel("", self)
        self._empty_source_note.setObjectName("sourceNote")
        self._empty_source_note.setVisible(False)
        return page

    def _build_composer(self) -> QWidget:
        container = QWidget(self)
        container.setObjectName("composerArea")
        container.setFixedWidth(theme.COMPOSER_MAX_WIDTH)
        self.composer_area = container

        column = QVBoxLayout(container)
        column.setContentsMargins(0, theme.SPACING_UNIT, 0, 0)
        column.setSpacing(theme.SPACING_UNIT)

        self.composer = QFrame(container)
        self.composer.setObjectName("composer")
        self.composer.setFixedHeight(52)

        row = QHBoxLayout(self.composer)
        row.setContentsMargins(10, 6, 8, 6)
        row.setSpacing(6)

        self.attach_button = QPushButton(self.composer)
        self.attach_button.setObjectName("iconButton")
        self.attach_button.setFixedSize(36, 36)
        self.attach_button.setIconSize(QSize(20, 20))
        self.attach_button.setIcon(
            icons.icon(
                "paperclip",
                theme.TEXT_SECONDARY,
                20,
                active_tint=theme.TEXT_PRIMARY,
                disabled_tint=theme.TEXT_MUTED,
            )
        )
        self.attach_button.setAutoDefault(False)
        self.attach_button.setEnabled(False)
        self.attach_button.setAccessibleName("Attach a file")
        self.attach_button.setToolTip("Attachments arrive in a later phase")

        self.message_input = QLineEdit(self.composer)
        self.message_input.setObjectName("messageInput")
        self.message_input.setPlaceholderText("Type your message...")
        self.message_input.setEnabled(False)
        self.message_input.setAccessibleName("Message input")
        self.message_input.setAccessibleDescription(_DISCONNECTED_NOTE)
        self.message_input.setToolTip(_DISCONNECTED_NOTE)
        self.message_input.textChanged.connect(self._sync_send_enabled)
        self.message_input.returnPressed.connect(self.submit_current_prompt)
        # Focus is rendered on the composer card, not only on the line edit, so
        # keyboard users can see where typing will go at a glance.
        self.message_input.installEventFilter(self)

        self.stop_button = QPushButton(self.composer)
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setFixedSize(36, 36)
        self.stop_button.setVisible(False)
        self.stop_button.setIconSize(QSize(14, 14))
        self.stop_button.setIcon(
            icons.icon(
                "stop",
                theme.BRAND_RED,
                14,
                disabled_tint=theme.TEXT_MUTED,
            )
        )
        self.stop_button.setAutoDefault(False)
        self.stop_button.setEnabled(False)
        self.stop_button.setAccessibleName("Stop generating")
        self.stop_button.setToolTip("Stop generating")
        self.stop_button.clicked.connect(self._request_stop)

        self.send_button = QPushButton(self.composer)
        self.send_button.setObjectName("sendButton")
        self.send_button.setFixedSize(36, 36)
        self.send_button.setIconSize(QSize(16, 16))
        self.send_button.setIcon(
            icons.icon(
                "send",
                theme.TEXT_PRIMARY,
                16,
                active_tint=theme.TEXT_PRIMARY,
            )
        )
        self.send_button.setAutoDefault(False)
        self.send_button.setEnabled(False)
        self.send_button.setAccessibleName("Send message")
        self.send_button.setToolTip("Send message")
        self.send_button.clicked.connect(self.submit_current_prompt)

        row.addWidget(self.attach_button)
        row.addWidget(self.message_input, 1)
        row.addWidget(self.stop_button)
        row.addWidget(self.send_button)

        self.composer_note = QLabel(_DISCONNECTED_NOTE, container)
        self.composer_note.setObjectName("composerNote")
        self.composer_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.composer_note.setAccessibleName("Assistant status")

        column.addWidget(self.composer)
        column.addWidget(self.composer_note)
        return container

    # -- controller wiring ------------------------------------------------

    def set_conversation_controller(
        self, controller: ConversationController
    ) -> None:
        """Connect the conversation store/actions exactly once."""

        if controller is self._conversation:
            return

        previous = self._conversation
        if previous is not None:
            for signal, slot in (
                (previous.active_session_changed, self._on_active_session_changed),
                (previous.message_added, self._on_message_added),
                (previous.message_updated, self._on_message_updated),
                (previous.error_changed, self._on_conversation_error),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):  # pragma: no cover - Qt detail
                    pass

        self._conversation = controller
        controller.active_session_changed.connect(self._on_active_session_changed)
        controller.message_added.connect(self._on_message_added)
        controller.message_updated.connect(self._on_message_updated)
        controller.error_changed.connect(self._on_conversation_error)

        self.set_controller(controller.assistant_controller())
        self._render_session(controller.active_session())

    def set_controller(self, controller: AssistantController | None) -> None:
        """Connect the generation controller for provider status and notes."""

        if controller is self._controller:
            return

        previous = self._controller
        if previous is not None:
            for signal, slot in (
                (previous.status_changed, self._on_status_changed),
                (previous.generation_started, self._on_generation_started),
                (previous.generation_completed, self._on_generation_completed),
                (previous.generation_stopped, self._on_generation_stopped),
                (previous.generation_failed, self._on_generation_failed),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):  # pragma: no cover - Qt detail
                    pass

        self._controller = controller
        self._sticky_note = ""
        self._sticky_tone = "quiet"
        if controller is None:
            self._apply_status(
                ProviderStatus(ModelStatus.NOT_READY, _DISCONNECTED_NOTE)
            )
            return

        controller.status_changed.connect(self._on_status_changed)
        controller.generation_started.connect(self._on_generation_started)
        controller.generation_completed.connect(self._on_generation_completed)
        controller.generation_stopped.connect(self._on_generation_stopped)
        controller.generation_failed.connect(self._on_generation_failed)

        self.message_input.setToolTip("Ask the offline assistant a question")
        self.message_input.setAccessibleDescription(
            "Ask the offline assistant a question."
        )
        self.send_button.setToolTip("Send message to the offline assistant")
        self._apply_status(controller.status())

    # -- public API -------------------------------------------------------

    def conversation_controller(self) -> ConversationController | None:
        return self._conversation

    def message_widget(self, message_id: str) -> QWidget | None:
        return self._message_widgets.get(message_id)

    def messages_visible(self) -> bool:
        return self.content_stack.currentWidget() is self.thread_page

    def submit_current_prompt(self) -> bool:
        """Hand the trimmed composer text to the conversation controller."""

        conversation = self._conversation
        controller = self._controller
        if conversation is None or controller is None:
            return False
        if self._status.state is not ModelStatus.READY:
            return False

        text = self.message_input.text().strip()
        if not text:
            return False

        self._sticky_note = ""
        self._sticky_tone = "quiet"
        editing = self._editing_message_id
        if editing is not None:
            accepted = conversation.confirm_edited_submission(text)
            self._editing_message_id = None
        else:
            accepted = conversation.submit(text)

        if not accepted:
            self._set_note("The offline assistant is still preparing.", "quiet")
            return False

        self._pending_prompt = text
        self.message_input.clear()
        self._sync_send_enabled()
        self._scroll_to_bottom()
        return True

    # -- conversation events ----------------------------------------------

    def _on_active_session_changed(self, session: object) -> None:
        if isinstance(session, ChatSession):
            self._render_session(session)

    def _on_message_added(self, message: object) -> None:
        if not isinstance(message, ChatMessage):
            return
        if message.message_id in self._message_widgets:
            self._on_message_updated(message)
            return
        self._add_message_widget(message)
        self._show_thread()
        self._scroll_to_bottom()

    def _on_message_updated(self, message: object) -> None:
        if not isinstance(message, ChatMessage):
            return
        widget = self._message_widgets.get(message.message_id)
        if widget is None:
            return
        # Follow the stream only while the reader is already at the bottom.
        # Once they scroll up, later tokens must never yank the viewport.
        self._follow_bottom = self._is_at_bottom()
        widget.set_message(message)

    def _on_conversation_error(self, text: str) -> None:
        if not text:
            return
        self._sticky_note = text
        self._sticky_tone = "error"
        self._set_note(text, "error")

    # -- controller events ------------------------------------------------

    def _on_status_changed(self, status: ProviderStatus) -> None:
        if isinstance(status, ProviderStatus):
            self._apply_status(status)

    def _on_generation_started(self, _request_id: str) -> None:
        self._sticky_note = ""
        self._sticky_tone = "quiet"
        self._set_note(STATUS_MESSAGES[ModelStatus.GENERATING], "quiet")

    def _on_generation_completed(self, _request_id: str, _text: str) -> None:
        self._pending_prompt = ""
        self.message_input.clear()

    def _on_generation_stopped(self, _request_id: str, _text: str) -> None:
        self._pending_prompt = ""
        self._sticky_note = STATUS_MESSAGES[ModelStatus.STOPPED]
        self._sticky_tone = "quiet"
        self._set_note(self._sticky_note, "quiet")

    def _on_generation_failed(
        self,
        _request_id: str,
        user_message: str,
        _diagnostic: str,
    ) -> None:
        self._sticky_note = user_message
        self._sticky_tone = "error"
        self._set_note(user_message, "error")
        if self._pending_prompt and not self.message_input.text().strip():
            self.message_input.setText(self._pending_prompt)
            self._sync_send_enabled()

    # -- message actions --------------------------------------------------

    def _begin_edit(self, message_id: str) -> None:
        conversation = self._conversation
        if conversation is None:
            return
        text = conversation.edit_user_message(message_id)
        if text is None:
            return
        self._editing_message_id = message_id
        self.message_input.setText(text)
        self.message_input.setFocus()
        self._sticky_note = _EDIT_HINT
        self._sticky_tone = "quiet"
        self._set_note(_EDIT_HINT, "quiet")
        self._sync_send_enabled()

    def _retry_message(self, message_id: str) -> None:
        conversation = self._conversation
        if conversation is None:
            return
        if conversation.retry_assistant_message(message_id):
            self._scroll_to_bottom()

    def _copy_message(self, message_id: str) -> None:
        conversation = self._conversation
        if conversation is None:
            return
        text = conversation.copy_assistant_message(message_id)
        if not text:
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self.last_copied_text = text
        widget = self._message_widgets.get(message_id)
        if isinstance(widget, _AssistantMessage):
            widget.show_copied()

    # -- message rendering ------------------------------------------------

    def _render_session(self, session: ChatSession) -> None:
        self._clear_message_widgets()
        self._editing_message_id = None
        self._sticky_note = ""
        self._sticky_tone = "quiet"
        for message in session.messages:
            self._add_message_widget(message, scroll=False)
        if session.messages:
            self._show_thread()
            self._scroll_to_bottom()
        else:
            self._show_empty()
        if self._status.state is ModelStatus.READY:
            self._set_note(_READY_HINT, "quiet")

    def _add_message_widget(
        self, message: ChatMessage, *, scroll: bool = False
    ) -> None:
        if message.role is MessageRole.USER:
            widget: QWidget = _UserMessage(message, self.thread_content)
            widget.edit_requested.connect(self._begin_edit)
        else:
            assistant = _AssistantMessage(message, self.thread_content)
            assistant.retry_requested.connect(self._retry_message)
            assistant.copy_requested.connect(self._copy_message)
            widget = assistant
        widget.column.setFixedWidth(self._bubble_width)
        self._message_layout.insertWidget(
            self._message_layout.count() - 1, widget
        )
        self._message_widgets[message.message_id] = widget
        if scroll:
            self._scroll_to_bottom()

    def _clear_message_widgets(self) -> None:
        for widget in self._message_widgets.values():
            self._message_layout.removeWidget(widget)
            widget.setParent(None)
            widget.deleteLater()
        self._message_widgets.clear()

    def _show_thread(self) -> None:
        if self.content_stack.currentWidget() is not self.thread_page:
            motion.show_page(self.content_stack, self.thread_page)
            self._sync_thread_width()

    def _show_empty(self) -> None:
        if self.content_stack.currentWidget() is not self.empty_page:
            motion.show_page(self.content_stack, self.empty_page)

    def _last_assistant_widget(self) -> _AssistantMessage | None:
        latest = None
        for widget in self._message_widgets.values():
            if isinstance(widget, _AssistantMessage):
                latest = widget
        return latest

    # -- scroll -----------------------------------------------------------

    def _is_at_bottom(self) -> bool:
        bar = self.conversation_thread.verticalScrollBar()
        return bar.value() >= bar.maximum() - 8

    def _scroll_to_bottom(self) -> None:
        self._follow_bottom = True
        self._set_scroll_value(self.conversation_thread.verticalScrollBar().maximum())
        QTimer.singleShot(0, self._force_scroll_to_bottom)

    def _force_scroll_to_bottom(self) -> None:
        if not self._follow_bottom:
            return
        try:
            bar = self.conversation_thread.verticalScrollBar()
            self._set_scroll_value(bar.maximum())
        except RuntimeError:  # pragma: no cover - widget already deleted
            pass

    def _set_scroll_value(self, value: int) -> None:
        self._auto_scrolling = True
        try:
            self.conversation_thread.verticalScrollBar().setValue(value)
        finally:
            self._auto_scrolling = False

    def _on_scroll_value_changed(self, value: int) -> None:
        # A reader who scrolls away from the bottom stops auto-follow; scroll
        # back down (or submit a new message) to resume it.
        if self._auto_scrolling:
            return
        bar = self.conversation_thread.verticalScrollBar()
        self._follow_bottom = value >= bar.maximum() - 8

    def _on_range_changed(self, _minimum: int, maximum: int) -> None:
        # The scroll range updates after layout, later than the token that
        # changed the bubble height. Follow it only while auto-follow is on.
        if not self._follow_bottom or self._auto_scrolling:
            return
        try:
            self._set_scroll_value(maximum)
        except RuntimeError:  # pragma: no cover - widget already deleted
            pass

    def _sync_thread_width(self) -> None:
        viewport = self.conversation_thread.viewport().width()
        if viewport <= 0:
            return
        target = min(theme.CONVERSATION_MAX_WIDTH, max(280, viewport - 8))
        if self.thread_content.width() != target:
            self.thread_content.setFixedWidth(target)
        bubble = min(theme.CHAT_BUBBLE_MAX_WIDTH, max(240, target - 8))
        if bubble == self._bubble_width:
            return
        self._bubble_width = bubble
        for widget in self._message_widgets.values():
            widget.column.setFixedWidth(bubble)

    def resizeEvent(self, event) -> None:  # noqa: D401 - Qt override
        super().resizeEvent(event)
        self._sync_thread_width()

    def showEvent(self, event) -> None:  # noqa: D401 - Qt override
        super().showEvent(event)
        self._sync_thread_width()

    # -- state rendering --------------------------------------------------

    def _apply_status(self, status: ProviderStatus) -> None:
        previous_state = self._status.state
        self._status = status
        state = status.state
        connected = self._controller is not None
        ready = state is ModelStatus.READY
        generating = state in (ModelStatus.GENERATING, ModelStatus.STOPPING)

        self.message_input.setEnabled(connected and ready)
        stop_visible = connected and generating
        self.stop_button.setVisible(stop_visible)
        self.stop_button.setEnabled(stop_visible)
        if stop_visible and not self._stop_was_visible:
            motion.fade_in(self.stop_button, duration_ms=theme.MOTION_FAST_MS)
        self._stop_was_visible = stop_visible
        theme.set_state(self.composer, "busy", "true" if generating else "false")
        self._sync_send_enabled()

        if not connected:
            self._set_note(_DISCONNECTED_NOTE, "quiet")
        elif generating:
            self._set_note(status_message(state, status.detail), "quiet")
        elif ready:
            self._set_note(self._sticky_note or _READY_HINT, self._sticky_tone)
        else:
            tone = "error" if state in FAILURE_STATES else "quiet"
            self._set_note(status_message(state, status.detail), tone)

        if ready and previous_state in (
            ModelStatus.GENERATING,
            ModelStatus.STOPPING,
        ):
            self.message_input.setFocus()

    def _sync_send_enabled(self) -> None:
        has_text = bool(self.message_input.text().strip())
        ready = self._status.state is ModelStatus.READY
        self.send_button.setEnabled(
            self._controller is not None
            and self._conversation is not None
            and ready
            and has_text
        )

    def _set_note(self, text: str, tone: str) -> None:
        self.composer_note.setText(text)
        self.composer_note.setVisible(True)
        theme.set_state(self.composer_note, "tone", tone)

    def eventFilter(self, watched, event) -> bool:  # noqa: D401 - Qt override
        if watched is self.message_input:
            if event.type() == QEvent.Type.FocusIn:
                theme.set_state(self.composer, "focused", "true")
            elif event.type() == QEvent.Type.FocusOut:
                theme.set_state(self.composer, "focused", "false")
        return super().eventFilter(watched, event)

    def _request_stop(self) -> None:
        conversation = self._conversation
        if conversation is not None:
            conversation.stop()

    # -- Phase 3 compatibility accessors ---------------------------------

    @property
    def response_view(self) -> _MessageBody:
        widget = self._last_assistant_widget()
        return widget.body if widget is not None else self._empty_response_view

    @property
    def response_panel(self) -> QFrame:
        widget = self._last_assistant_widget()
        return widget.bubble if widget is not None else self._empty_response_panel

    @property
    def source_note(self) -> QLabel:
        widget = self._last_assistant_widget()
        return widget.source_note if widget is not None else self._empty_source_note


def _is_conversation_controller(candidate: object) -> bool:
    """Duck-type the controller so the UI never imports the service eagerly."""

    return hasattr(candidate, "active_session") and hasattr(
        candidate, "assistant_controller"
    )
