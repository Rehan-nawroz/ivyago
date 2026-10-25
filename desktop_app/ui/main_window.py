"""Branded, frameless shell for the Ivyago desktop application."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..app_state import AppState
from ..models import NavigationDestination
from ..services.chat_session_store import ChatSessionStore
from ..services.conversation_controller import ConversationController
from . import motion, theme
from .assist_view import AssistView
from .native_chrome import FramelessResizeFilter
from .placeholder_view import PlaceholderView
from .settings_view import SettingsView
from .sidebar import Sidebar
from .window_chrome import TitleBar

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..services.assistant_controller import AssistantController


class MainWindow(QMainWindow):
    """The desktop shell: branded chrome, navigation, themed pages."""

    def __init__(
        self,
        state: AppState,
        controller: AssistantController | None = None,
        conversation_controller: ConversationController | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.state = state
        self._controller = controller
        self._conversation = conversation_controller
        if self._controller is None and conversation_controller is not None:
            # The conversation controller owns the generation controller it
            # delegates to, so window shutdown still closes the provider.
            self._controller = conversation_controller.assistant_controller()
        elif conversation_controller is None and self._controller is not None:
            # Compatibility for callers that inject only an AssistantController:
            # wrap it in the Phase 4 conversation layer (chat state is in memory).
            self._conversation = ConversationController(
                ChatSessionStore(), self._controller, self
            )
        self._resize_filter: FramelessResizeFilter | None = None

        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("mainWindow")
        self.setWindowTitle(state.metadata.application_name)
        self.setMinimumSize(
            theme.MINIMUM_WINDOW_WIDTH,
            theme.MINIMUM_WINDOW_HEIGHT,
        )
        self.resize(theme.INITIAL_WINDOW_WIDTH, theme.INITIAL_WINDOW_HEIGHT)

        root = QWidget(self)
        root.setObjectName("appRoot")
        self.setCentralWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.title_bar = TitleBar(self, root)
        root_layout.addWidget(self.title_bar)

        body = QWidget(root)
        body.setObjectName("appBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        root_layout.addWidget(body, 1)

        self.sidebar = Sidebar(body)
        self.sidebar.navigation_requested.connect(self.select_destination)
        if self._conversation is not None:
            self.sidebar.set_conversation_controller(self._conversation)
        body_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget(body)
        self.stack.setObjectName("contentStack")
        body_layout.addWidget(self.stack, 1)

        self._build_pages()
        self.select_destination(state.selected_destination)

    # -- public API -------------------------------------------------------

    def controller(self) -> AssistantController | None:
        """Return the assistant controller this window owns, if any."""

        return self._controller

    def conversation_controller(self) -> ConversationController | None:
        """Return the in-memory conversation layer this window owns, if any."""

        return self._conversation

    def current_destination(self) -> NavigationDestination:
        """Return the currently selected top-level destination."""

        return self.state.selected_destination

    def current_page(self) -> QWidget:
        """Return the currently visible page widget."""

        return self.stack.currentWidget()

    def page_for(self, destination: NavigationDestination) -> QWidget:
        """Return the page widget for ``destination``."""

        return self._pages[destination]

    def destination_button(
        self,
        destination: NavigationDestination,
    ) -> QAbstractButton:
        """Return a navigation button for deterministic tests and callers."""

        return self.sidebar.button(destination)

    def select_destination(self, destination: NavigationDestination) -> None:
        """Synchronize state, selected navigation styling, and visible page.

        The page switch is immediate; the short fade that follows is purely
        cosmetic and is skipped when the system disables animation.
        """

        if destination not in self._pages:
            raise ValueError(f"Unknown navigation destination: {destination!r}")

        self.state.selected_destination = destination
        self.sidebar.set_selected(destination)
        motion.show_page(self.stack, self._pages[destination])

    # -- construction -----------------------------------------------------

    def _build_pages(self) -> None:
        self._pages: dict[NavigationDestination, QWidget] = {
            NavigationDestination.ASSIST: AssistView(
                self._conversation, self.stack
            ),
            NavigationDestination.HISTORY: PlaceholderView(
                "History",
                "Local conversation history will appear here.",
                "history",
                self.stack,
            ),
            NavigationDestination.SETTINGS: SettingsView(
                self.state.metadata, self._conversation, self._controller, self.stack
            ),
        }
        for page in self._pages.values():
            self.stack.addWidget(page)

    # -- window chrome ----------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: D401 - Qt override
        super().showEvent(event)
        self._install_resize_filter()

    def closeEvent(self, event) -> None:  # noqa: D401 - Qt override
        controller = self._controller
        if controller is not None:
            controller.close()
        self._remove_resize_filter()
        super().closeEvent(event)

    def changeEvent(self, event) -> None:  # noqa: D401 - Qt override
        super().changeEvent(event)
        title_bar = getattr(self, "title_bar", None)
        if event.type() == QEvent.Type.WindowStateChange and title_bar is not None:
            title_bar.sync_window_state()

    def _install_resize_filter(self) -> None:
        if sys.platform != "win32" or self._resize_filter is not None:
            return
        app = QApplication.instance()
        if app is None:
            return
        self._resize_filter = FramelessResizeFilter(self)
        app.installNativeEventFilter(self._resize_filter)

    def _remove_resize_filter(self) -> None:
        if self._resize_filter is None:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeNativeEventFilter(self._resize_filter)
        self._resize_filter = None
