"""Frameless window chrome: the custom title bar and edge-resize geometry."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QPushButton, QWidget

from . import icons, theme

_HT_RESULT = {
    (True, False, False, False): 10,   # HTLEFT
    (False, True, False, False): 11,   # HTRIGHT
    (False, False, True, False): 12,   # HTTOP
    (True, False, True, False): 13,    # HTTOPLEFT
    (False, True, True, False): 14,    # HTTOPRIGHT
    (False, False, False, True): 15,   # HTBOTTOM
    (True, False, False, True): 16,    # HTBOTTOMLEFT
    (False, True, False, True): 17,    # HTBOTTOMRIGHT
}


def resize_edges_at(
    position: QPoint,
    size: QSize,
    margin: int = theme.WINDOW_RESIZE_MARGIN,
) -> Qt.Edge:
    """Return the window edges under ``position`` (window-local coordinates)."""

    edges = Qt.Edge(0)
    if position.x() < margin:
        edges |= Qt.Edge.LeftEdge
    elif position.x() >= size.width() - margin:
        edges |= Qt.Edge.RightEdge
    if position.y() < margin:
        edges |= Qt.Edge.TopEdge
    elif position.y() >= size.height() - margin:
        edges |= Qt.Edge.BottomEdge
    return edges


def hit_test_code(edges: Qt.Edge) -> int | None:
    """Map Qt window edges to the Win32 ``WM_NCHITTEST`` result code."""

    if not edges:
        return None
    key = (
        bool(edges & Qt.Edge.LeftEdge),
        bool(edges & Qt.Edge.RightEdge),
        bool(edges & Qt.Edge.TopEdge),
        bool(edges & Qt.Edge.BottomEdge),
    )
    return _HT_RESULT.get(key)


class WindowControlButton(QPushButton):
    """A compact caption button that tints white on hover."""

    def __init__(
        self,
        icon_name: str,
        accessible_name: str,
        object_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFixedSize(34, 26)
        self.setIconSize(QSize(14, 14))
        self.setIcon(
            icons.icon(
                icon_name,
                theme.TEXT_SECONDARY,
                14,
                active_tint=theme.TEXT_PRIMARY,
            )
        )
        self.setText("")
        self.setToolTip(accessible_name)
        self.setAccessibleName(accessible_name)
        self.setAutoDefault(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_icon_name(self, icon_name: str, accessible_name: str) -> None:
        self.setIcon(
            icons.icon(
                icon_name,
                theme.TEXT_SECONDARY,
                14,
                active_tint=theme.TEXT_PRIMARY,
            )
        )
        self.setToolTip(accessible_name)
        self.setAccessibleName(accessible_name)


class TitleBar(QWidget):
    """Draggable custom title bar with minimize, maximize, and close."""

    def __init__(self, window: QMainWindow, parent: QWidget | None = None) -> None:
        super().__init__(parent or window)
        self._window = window
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(theme.TITLE_BAR_HEIGHT)
        self.setAccessibleName("Window title bar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(4)
        layout.addStretch(1)

        self.minimize_button = WindowControlButton(
            "minimize", "Minimize", "windowButton", self
        )
        self.maximize_button = WindowControlButton(
            "maximize", "Maximize", "windowButton", self
        )
        self.close_button = WindowControlButton("close", "Close", "windowClose", self)

        self.minimize_button.clicked.connect(self._window.showMinimized)
        self.maximize_button.clicked.connect(self.toggle_maximize)
        self.close_button.clicked.connect(self._window.close)

        for button in (
            self.minimize_button,
            self.maximize_button,
            self.close_button,
        ):
            layout.addWidget(button)

        self.sync_window_state()

    # -- behavior ---------------------------------------------------------

    def toggle_maximize(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self.sync_window_state()

    def sync_window_state(self) -> None:
        if self._window.isMaximized():
            self.maximize_button.set_icon_name("restore", "Restore")
        else:
            self.maximize_button.set_icon_name("maximize", "Maximize")

    def showEvent(self, event: QShowEvent) -> None:  # noqa: D401 - Qt override
        super().showEvent(event)
        self.sync_window_state()

    def mousePressEvent(self, event) -> None:  # noqa: D401 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: D401 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
