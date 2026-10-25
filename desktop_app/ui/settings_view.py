"""Native, session-only Settings page.

The page is a trust and safety surface: it explains offline processing and
session-only memory truthfully, offers the bundled legal documents, reports a
friendly local-assistant status, and exposes confirmed conversation clearing.
It never constructs a provider, reads a model artifact, or writes anything.

All visual values come from :mod:`desktop_app.ui.theme`; all motion comes from
:mod:`desktop_app.ui.motion`, which keeps navigation synchronous and honours
the system animation preference.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..services.model_provider import ModelStatus
from . import icons, motion, theme
from .backdrop import BackdropFrame
from .legal_document_view import LegalDocumentView

REPOSITORY_URL = "https://github.com/Rehan-nawroz/ivyago"
ATTRIBUTION = (
    "Created and maintained by Rehan-nawroz\n"
    "Source repository: github.com/Rehan-nawroz/ivyago"
)

PRIVACY = """Ivyago is offline-first.

Messages are processed locally by the desktop application. No account or cloud service is required for the assistant flow.

On first launch, Ivyago downloads its language model (about 1.1 GB) once from the official model repository. That request sends no messages, account details, or personal content. After the download finishes, the assistant works without an internet connection.

The current release does not use advertising or behavioral tracking. Conversations are stored in memory for the current process only and are removed when Ivyago closes.

Persistent storage is not enabled in this release. Ivyago is in beta testing; future releases may change storage behavior and this policy should be updated."""
TERMS = """Ivyago provides general informational and safety guidance.

Ivyago is not a doctor, hospital, ambulance service, emergency dispatcher, or diagnostic system. Responses may be incomplete, incorrect, or unsuitable for a particular person.

Contact local emergency services when appropriate. Do not replace qualified professional advice with Ivyago.

You remain responsible for decisions made using the software. Ivyago is provided as a beta release."""
SAFETY = """Call local emergency services when there is immediate danger.

Do not delay emergency care while waiting for Ivyago. Do not use Ivyago as the sole basis for treatment decisions.

Confirm medication questions with a qualified doctor or pharmacist.

Seek professional help when symptoms worsen, are severe, or are unclear."""

LEGAL_DOCUMENTS = (
    ("Privacy Policy", PRIVACY),
    ("Terms of Use", TERMS),
    ("Safety Notice", SAFETY),
)


class SettingsView(BackdropFrame):
    """Scrollable native Settings page with grouped, readable sections."""

    def __init__(
        self,
        metadata,
        conversation_controller=None,
        assistant_controller=None,
        parent=None,
    ):
        super().__init__(parent)
        self._page_stack = parent if isinstance(parent, QStackedWidget) else None
        self.metadata = metadata
        self.conversation_controller = conversation_controller
        self.assistant_controller = assistant_controller
        self._document_view: LegalDocumentView | None = None
        self.legal_buttons: dict[str, QPushButton] = {}

        self._build_layout()
        self._build_privacy_section()
        self._build_legal_section()
        self._build_status_section()
        self._build_appearance_section()
        self._build_about_section()

        self._update_generation_state()
        self._update_status(
            getattr(assistant_controller, "status", lambda: None)()
        )
        if assistant_controller is not None:
            assistant_controller.status_changed.connect(self._update_status)
        if conversation_controller is not None:
            conversation_controller.generation_state_changed.connect(
                lambda _state: self._update_generation_state()
            )

    # -- construction -----------------------------------------------------

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.CONTENT_PADDING,
            theme.SPACING_UNIT * 3,
            theme.CONTENT_PADDING,
            theme.SPACING_UNIT * 2,
        )
        root.setSpacing(theme.SPACING_UNIT)
        root.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self.content_column = QWidget(self)
        self.content_column.setObjectName("settingsColumn")
        self.content_column.setMaximumWidth(theme.SETTINGS_MAX_WIDTH)
        column = QVBoxLayout(self.content_column)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)

        self.page_title = QLabel("Settings", self.content_column)
        self.page_title.setObjectName("pageTitle")
        self.page_title.setAccessibleName("Settings page title")

        subtitle = QLabel(
            "How Ivyago handles privacy, safety, and the local assistant.",
            self.content_column,
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)

        column.addWidget(self.page_title)
        column.addWidget(subtitle)
        column.addSpacing(theme.SPACING_UNIT)

        self.scroll_area = QScrollArea(self.content_column)
        self.scroll_area.setObjectName("settingsScroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setAccessibleName("Settings content")

        body = QWidget()
        body.setObjectName("settingsBody")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(0, 0, theme.SPACING_UNIT, 0)
        self._body_layout.setSpacing(theme.SPACING_UNIT // 2)
        self.scroll_area.setWidget(body)
        column.addWidget(self.scroll_area, 1)
        root.addWidget(self.content_column, 1)

    def _section(self, heading: str, description: str | None = None) -> QVBoxLayout:
        label = QLabel(heading, self)
        label.setObjectName("settingsSectionHeading")
        label.setAccessibleName(f"{heading} section")
        self._body_layout.addSpacing(theme.SPACING_UNIT + 4)
        self._body_layout.addWidget(label)

        if description:
            hint = QLabel(description, self)
            hint.setObjectName("settingsHint")
            hint.setWordWrap(True)
            self._body_layout.addWidget(hint)

        holder = QWidget(self)
        holder.setObjectName("settingsSectionBody")
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, theme.SPACING_UNIT // 2, 0, 0)
        box.setSpacing(theme.SPACING_UNIT)
        self._body_layout.addWidget(holder)
        return box

    def _card(self, layout: QVBoxLayout, name: str, value: str) -> QFrame:
        card = QFrame(self)
        card.setObjectName("settingsCard")
        card.setAccessibleName(name or "Ivyago")
        card.setAccessibleDescription(value)
        box = QVBoxLayout(card)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(3)

        if name:
            title = QLabel(name, card)
            title.setObjectName("settingsCardTitle")
            title.setWordWrap(True)
            box.addWidget(title)

        headline, _, detail = value.partition("\n")
        body = QLabel(headline, card)
        body.setObjectName("settingsCardValue")
        body.setWordWrap(True)
        body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        box.addWidget(body)

        if detail:
            description = QLabel(detail, card)
            description.setObjectName("settingsCardDetail")
            description.setWordWrap(True)
            description.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            box.addWidget(description)

        layout.addWidget(card)
        return card

    def _action_button(
        self,
        parent: QWidget,
        label: str,
        accessible_name: str,
        description: str,
        tooltip: str,
        *,
        object_name: str = "settingsAction",
        icon_name: str | None = None,
    ) -> QPushButton:
        button = QPushButton(label, parent)
        button.setObjectName(object_name)
        button.setAccessibleName(accessible_name)
        button.setAccessibleDescription(description)
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setAutoDefault(False)
        if icon_name is not None:
            button.setIcon(
                icons.icon(
                    icon_name,
                    theme.TEXT_SECONDARY,
                    16,
                    active_tint=theme.TEXT_PRIMARY,
                    disabled_tint=theme.TEXT_DISABLED,
                )
            )
            button.setIconSize(icons.icon_size(16))
        return button

    def _build_privacy_section(self) -> None:
        box = self._section(
            "Privacy & Data",
            "Ivyago works on this computer. Nothing in this section requires an account.",
        )
        self._card(
            box,
            "Offline processing",
            "Active\nMessages are processed by the local Ivyago assistant; no "
            "cloud account or internet connection is required for the "
            "assistant flow.",
        )
        self._card(
            box,
            "Conversation storage",
            "Temporary session memory\nConversations remain available while "
            "Ivyago is open. They are removed when the application closes.",
        )

        actions = QWidget(self)
        actions.setObjectName("clearActions")
        row = QHBoxLayout(actions)
        row.setContentsMargins(0, theme.SPACING_UNIT // 2, 0, 0)
        row.setSpacing(theme.SPACING_UNIT)

        self.clear_current_button = self._action_button(
            actions,
            "Clear current conversation",
            "Clear current conversation",
            "Remove the messages in the chat you are viewing. Asks for "
            "confirmation first.",
            "Clear only the conversation you are viewing",
            object_name="clearCurrentButton",
        )
        self.clear_current_button.clicked.connect(
            lambda: self._confirm_clear(False)
        )

        self.clear_all_button = self._action_button(
            actions,
            "Clear all conversations",
            "Clear all conversations",
            "Remove every in-memory conversation. Asks for confirmation first.",
            "Clear every in-memory conversation",
            object_name="clearAllButton",
        )
        self.clear_all_button.clicked.connect(lambda: self._confirm_clear(True))

        row.addWidget(self.clear_current_button, 1)
        row.addWidget(self.clear_all_button, 1)
        box.addWidget(actions)

    def _build_legal_section(self) -> None:
        box = self._section(
            "Safety & Legal",
            "Bundled documents. They open inside Ivyago and need no connection.",
        )
        for title, body_text in LEGAL_DOCUMENTS:
            button = self._action_button(
                self,
                title,
                title,
                f"Open the {title} inside Ivyago.",
                f"Read the {title}",
                icon_name="document",
            )
            button.clicked.connect(
                lambda checked=False, name=title, text=body_text: (
                    self._show_document(name, text)
                )
            )
            self.legal_buttons[title] = button
            box.addWidget(button)

    def _build_status_section(self) -> None:
        box = self._section(
            "Assistant Status",
            "Responses are generated on this computer and do not require a "
            "cloud service.",
        )
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("assistantStatusLabel")
        self.status_label.setAccessibleName("Assistant status")
        box.addWidget(self.status_label)

        hint = QLabel("Embedded local runtime", self)
        hint.setObjectName("settingsHint")
        box.addWidget(hint)

    def _build_appearance_section(self) -> None:
        box = self._section("Appearance")
        self._card(box, "Current theme", "Ivyago Dark")

    def _build_about_section(self) -> None:
        box = self._section("About Ivyago")
        self._card(
            box,
            "Ivyago",
            "Offline-first emergency and safety assistant",
        )
        self._card(box, "Version", self.metadata.version)
        self._card(box, "Status", "Beta testing")
        description = QLabel(
            "Ivyago combines a local language model with optional local "
            "reference information to provide practical safety guidance "
            "without requiring a cloud service.",
            self,
        )
        description.setObjectName("settingsHint")
        description.setWordWrap(True)
        box.addWidget(description)

        self.repository_button = self._action_button(
            self,
            ATTRIBUTION,
            "Open Ivyago source repository",
            "Opens the Ivyago project page in your web browser.",
            "Open github.com/Rehan-nawroz/ivyago",
            object_name="repositoryLink",
            icon_name="external_link",
        )
        self.repository_button.clicked.connect(self._open_repository)
        box.addWidget(self.repository_button)

    # -- state ------------------------------------------------------------

    def _update_status(self, status) -> None:
        state = getattr(status, "state", None)
        mapping = {
            ModelStatus.READY: "Ready",
            ModelStatus.PREPARING: "Preparing",
            ModelStatus.NOT_READY: "Not ready",
        }
        friendly = (
            mapping[state]
            if isinstance(state, ModelStatus) and state in mapping
            else "Unavailable"
        )
        self.status_label.setText(f"Assistant status: {friendly}")
        self.status_label.setAccessibleDescription(
            f"The local assistant is {friendly.lower()}."
        )

    def _update_generation_state(self) -> None:
        enabled = (
            self.conversation_controller is not None
            and not self.conversation_controller.is_generating()
        )
        self.clear_current_button.setEnabled(enabled)
        self.clear_all_button.setEnabled(enabled)

    # -- actions ----------------------------------------------------------

    def _confirm_clear(self, all_chats: bool) -> None:
        dialog = self._build_clear_dialog(all_chats)
        if dialog.exec() != QMessageBox.StandardButton.Yes:
            return

        controller = self.conversation_controller
        if controller is None:
            return
        ok = (
            controller.clear_all_chats() if all_chats else controller.clear_active_chat()
        )
        if ok and all_chats and self.window() is not None and hasattr(
            self.window(), "select_destination"
        ):
            from ..models import NavigationDestination

            self.window().select_destination(NavigationDestination.ASSIST)

    def _build_clear_dialog(self, all_chats: bool) -> QMessageBox:
        """Build the themed confirmation dialog for a clear action."""

        dialog = QMessageBox(self)
        # A quiet themed mark replaces the blue system question icon.
        dialog.setIconPixmap(icons.pixmap("trash", theme.TEXT_SECONDARY, 26))
        dialog.setWindowTitle(
            "Clear all conversations"
            if all_chats
            else "Clear current conversation"
        )
        dialog.setText(
            "Clear all conversations?"
            if all_chats
            else "Clear the current conversation?"
        )
        dialog.setInformativeText(
            "Every in-memory chat will be removed. This cannot be undone, and "
            "Ivyago does not keep a copy."
            if all_chats
            else "The messages in this chat will be removed. Other chats stay."
        )
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        # Name the action instead of the generic yes/no answer.
        dialog.button(QMessageBox.StandardButton.Yes).setText("Clear")
        dialog.button(QMessageBox.StandardButton.No).setText("Cancel")
        theme.apply_dialog_theme(dialog)
        motion.fade_dialog(dialog)
        return dialog

    def _open_repository(self) -> None:
        """Open the canonical repository only on an explicit click."""

        QDesktopServices.openUrl(QUrl(REPOSITORY_URL))

    # -- legal documents --------------------------------------------------

    def _show_document(self, title: str, body: str) -> None:
        previous = self._document_view
        view = LegalDocumentView(
            title,
            body,
            ATTRIBUTION,
            self._restore_settings,
            self._page_stack or self.parentWidget(),
        )
        self._document_view = view
        if self._page_stack is not None:
            self._page_stack.addWidget(view)
            motion.show_page(self._page_stack, view)
            if previous is not None:
                self._page_stack.removeWidget(previous)
                previous.deleteLater()
        else:
            view.setGeometry(self.rect())
            self.hide()
            view.show()
            motion.fade_in(view)

    def _restore_settings(self) -> None:
        if self._page_stack is not None:
            motion.show_page(self._page_stack, self)
        else:
            document = self._document_view
            if document is not None:
                document.hide()
            self.show()
            motion.fade_in(self)
