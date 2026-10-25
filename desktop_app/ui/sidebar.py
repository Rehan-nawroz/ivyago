"""Branded, session-aware left rail for the Ivyago desktop shell.

The expanded sidebar carries the brand lockup, New Chat, the in-memory chat
list, the reassurance footer, and Settings. The collapsed state is the compact
64 px icon rail from the approved reference. Both states are presentation only:
selection, creation, and clearing are delegated to the conversation controller,
and no chat data is ever persisted here.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..models import ChatSession, NavigationDestination
from . import assets, icons, motion, theme

_LABELS = {
    NavigationDestination.ASSIST: "Assist",
    NavigationDestination.HISTORY: "History",
    NavigationDestination.SETTINGS: "Settings",
}

_ICONS = {
    NavigationDestination.ASSIST: "chat",
    NavigationDestination.HISTORY: "history",
    NavigationDestination.SETTINGS: "settings",
}

_ICON_SIZE = 20
_RAIL_ICON_SIZE = 18
_ICON_LEFT = 14
_TEXT_GAP = 12
_ACCENT_WIDTH = 3
_RAIL_SESSION_LIMIT = 8
_RAIL_CONTROL = theme.RAIL_BUTTON_SIZE


class NavButton(QAbstractButton):
    """One top-level destination, painted to match the reference design."""

    def __init__(
        self,
        destination: NavigationDestination,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.destination = destination
        self._hovered = False
        self.setText(_LABELS[destination])
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(theme.NAV_ITEM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(f"Open {_LABELS[destination]}")
        self.setAccessibleDescription(
            f"Switch the Ivyago window to the {_LABELS[destination]} view."
        )

    def sizeHint(self) -> QSize:
        return QSize(
            theme.SIDEBAR_WIDTH - 2 * theme.SPACING_UNIT,
            theme.NAV_ITEM_HEIGHT,
        )

    def enterEvent(self, event) -> None:  # noqa: D401 - Qt override
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: D401 - Qt override
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: D401 - Qt override
        # Enter should activate a focused destination like Space already does.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: D401 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.CONTROL_RADIUS
        shape = QPainterPath()
        shape.addRoundedRect(rect, radius, radius)

        checked = self.isChecked()
        if checked:
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            gradient.setColorAt(0.0, QColor(theme.NAV_ACTIVE_LEFT))
            gradient.setColorAt(1.0, QColor(theme.NAV_ACTIVE_RIGHT))
            painter.fillPath(shape, gradient)
            painter.setPen(QPen(QColor(theme.BORDER_NAV_ACTIVE), 1))
            painter.drawPath(shape)
            self._paint_accent(painter, rect)
            tint = theme.BRAND_RED
            text_color = QColor(theme.TEXT_PRIMARY)
            weight = QFont.Weight.DemiBold
        else:
            if self.isDown():
                painter.fillPath(shape, QColor(theme.BORDER_STRONG))
            elif self._hovered:
                painter.fillPath(shape, QColor(theme.SURFACE_NAV_HOVER))
            tint = theme.TEXT_BODY if self._hovered else theme.TEXT_SECONDARY
            text_color = QColor(
                theme.TEXT_BODY if self._hovered else theme.TEXT_SECONDARY
            )
            weight = QFont.Weight.Medium

        icon = icons.pixmap(_ICONS[self.destination], tint, _ICON_SIZE)
        icon_x = rect.left() + _ICON_LEFT
        icon_y = rect.top() + (rect.height() - _ICON_SIZE) / 2
        painter.drawPixmap(
            QRectF(icon_x, icon_y, _ICON_SIZE, _ICON_SIZE),
            icon,
            QRectF(icon.rect()),
        )

        font = QFont(self.font())
        font.setPixelSize(theme.FONT_SIZE_NAV)
        font.setWeight(weight)
        painter.setFont(font)
        painter.setPen(text_color)
        text_x = icon_x + _ICON_SIZE + _TEXT_GAP
        painter.drawText(
            QRectF(text_x, rect.top(), rect.width() - text_x - 8, rect.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.text(),
        )

        if self.hasFocus():
            focus_pen = QPen(QColor(theme.BORDER_FOCUS))
            focus_pen.setWidthF(1)
            painter.setPen(focus_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1
            )
        painter.end()

    @staticmethod
    def _paint_accent(painter: QPainter, rect: QRectF) -> None:
        bar = QRectF(rect.left(), rect.top(), _ACCENT_WIDTH, rect.height())
        path = QPainterPath()
        path.addRoundedRect(bar, 1.5, 1.5)
        painter.fillPath(path, QColor(theme.BRAND_RED))


class SessionRow(QAbstractButton):
    """One in-memory chat row: icon plus a safely elided title."""

    def __init__(
        self,
        session: ChatSession,
        *,
        collapsed: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.session_id = session.session_id
        self._title = session.title
        self._collapsed = collapsed
        self._hovered = False
        self.setText(session.title)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip(session.title)
        self.setAccessibleName(f"Open chat: {session.title}")
        self.setAccessibleDescription(
            "Open this in-memory chat for the current Ivyago session."
        )
        if collapsed:
            self.setFixedSize(_RAIL_CONTROL, _RAIL_CONTROL)
        else:
            self.setFixedHeight(theme.CHAT_ROW_HEIGHT)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )

    def sizeHint(self) -> QSize:
        if self._collapsed:
            return QSize(_RAIL_CONTROL, _RAIL_CONTROL)
        return QSize(
            theme.SIDEBAR_WIDTH - 2 * theme.SPACING_UNIT,
            theme.CHAT_ROW_HEIGHT,
        )

    def enterEvent(self, event) -> None:  # noqa: D401 - Qt override
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: D401 - Qt override
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: D401 - Qt override
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: D401 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = theme.CONTROL_RADIUS
        shape = QPainterPath()
        shape.addRoundedRect(rect, radius, radius)

        active = self.isChecked()
        if active:
            gradient = QLinearGradient(rect.topLeft(), rect.topRight())
            gradient.setColorAt(0.0, QColor(theme.NAV_ACTIVE_LEFT))
            gradient.setColorAt(1.0, QColor(theme.NAV_ACTIVE_RIGHT))
            painter.fillPath(shape, gradient)
            painter.setPen(QPen(QColor(theme.BORDER_NAV_ACTIVE), 1))
            painter.drawPath(shape)
            NavButton._paint_accent(painter, rect)
            tint = theme.BRAND_RED
            text_color = QColor(theme.TEXT_PRIMARY)
            weight = QFont.Weight.DemiBold
        else:
            if self.isDown():
                painter.fillPath(shape, QColor(theme.BORDER_STRONG))
            elif self._hovered:
                painter.fillPath(shape, QColor(theme.SURFACE_NAV_HOVER))
            tint = theme.TEXT_BODY if self._hovered else theme.TEXT_SECONDARY
            text_color = QColor(
                theme.TEXT_BODY if self._hovered else theme.TEXT_SECONDARY
            )
            weight = QFont.Weight.Medium

        if self._collapsed:
            icon_size = _RAIL_ICON_SIZE
            icon = icons.pixmap("chat", tint, icon_size)
            icon_x = rect.left() + (rect.width() - icon_size) / 2
            icon_y = rect.top() + (rect.height() - icon_size) / 2
            painter.drawPixmap(
                QRectF(icon_x, icon_y, icon_size, icon_size),
                icon,
                QRectF(icon.rect()),
            )
        else:
            icon = icons.pixmap("chat", tint, _ICON_SIZE)
            icon_x = rect.left() + _ICON_LEFT
            icon_y = rect.top() + (rect.height() - _ICON_SIZE) / 2
            painter.drawPixmap(
                QRectF(icon_x, icon_y, _ICON_SIZE, _ICON_SIZE),
                icon,
                QRectF(icon.rect()),
            )

            font = QFont(self.font())
            font.setPixelSize(theme.FONT_SIZE_NAV)
            font.setWeight(weight)
            painter.setFont(font)

            text_x = icon_x + _ICON_SIZE + _TEXT_GAP
            available = int(rect.right() - text_x - 8)
            elided = QFontMetrics(font).elidedText(
                self._title, Qt.TextElideMode.ElideRight, max(0, available)
            )
            painter.setPen(text_color)
            painter.drawText(
                QRectF(text_x, rect.top(), available, rect.height()),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                elided,
            )

        if self.hasFocus():
            focus_pen = QPen(QColor(theme.BORDER_FOCUS))
            focus_pen.setWidthF(1)
            painter.setPen(focus_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1
            )
        painter.end()


class Sidebar(QFrame):
    """Brand lockup, session chat list, reassurance footer, and Settings."""

    navigation_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(theme.SIDEBAR_WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._buttons: dict[NavigationDestination, NavButton] = {}
        self._rows: dict[str, SessionRow] = {}
        self._rail_rows: dict[str, SessionRow] = {}
        self._conversation = None
        self._collapsed = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._expanded_panel = self._build_expanded_panel()
        self._collapsed_panel = self._build_collapsed_panel()
        self._layout.addWidget(self._expanded_panel)
        self._layout.addWidget(self._collapsed_panel)
        self._collapsed_panel.setVisible(False)

        self._build_hidden_destinations()

    # -- construction -----------------------------------------------------

    def _build_expanded_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("sidebarExpanded")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(
            theme.SPACING_UNIT * 2,
            theme.SPACING_UNIT * 3,
            theme.SPACING_UNIT * 2,
            theme.SPACING_UNIT * 3,
        )
        layout.setSpacing(0)

        layout.addWidget(self._build_brand(panel))
        layout.addSpacing(theme.SPACING_UNIT * 3)
        layout.addWidget(self._build_new_chat(panel))
        layout.addSpacing(theme.SPACING_UNIT * 2)

        self._session_list = QWidget(panel)
        self._session_list.setObjectName("sessionList")
        self._session_layout = QVBoxLayout(self._session_list)
        self._session_layout.setContentsMargins(0, 0, 0, 0)
        self._session_layout.setSpacing(2)
        layout.addWidget(self._session_list)

        layout.addStretch(1)
        layout.addWidget(self._build_footer(panel))
        return panel

    def _build_brand(self, parent: QWidget) -> QWidget:
        brand = QWidget(parent)
        brand.setObjectName("brandLockup")

        row = QHBoxLayout(brand)
        row.setContentsMargins(theme.SPACING_UNIT, 0, theme.SPACING_UNIT, 0)
        row.setSpacing(theme.SPACING_UNIT + 6)
        row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.brand_mark = QLabel(brand)
        self.brand_mark.setObjectName("brandMark")
        self.brand_mark.setFixedSize(56, 56)
        self.brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_mark.setAccessibleName("Ivyago nurse mark")
        self._load_brand_mark()

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)

        self.brand_wordmark = QLabel("Ivyago", brand)
        self.brand_wordmark.setObjectName("brandTitle")
        self.brand_wordmark.setAccessibleName("Ivyago")

        self.brand_tagline = QLabel("Your Emergency\nAI Assistant", brand)
        self.brand_tagline.setObjectName("brandTagline")

        text_column.addWidget(self.brand_wordmark)
        text_column.addWidget(self.brand_tagline)
        text_column.addStretch(1)

        self.collapse_button = self._rail_button(
            brand, "panel", "Collapse sidebar", "Collapse sidebar", size=28
        )
        self.collapse_button.clicked.connect(
            lambda: self.set_collapsed(True)
        )

        row.addWidget(self.brand_mark, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text_column, 1)
        row.addWidget(self.collapse_button, 0, Qt.AlignmentFlag.AlignTop)
        return brand

    def _load_brand_mark(self) -> None:
        try:
            mark = assets.brand_mark(52)
        except (FileNotFoundError, OSError):
            self.brand_mark.setText("I")
            self.brand_mark.setObjectName("brandMarkFallback")
            self.brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return
        self.brand_mark.setPixmap(mark)

    def _build_new_chat(self, parent: QWidget) -> QWidget:
        self.new_chat_button = QPushButton("New Chat", parent)
        self.new_chat_button.setObjectName("newChatButton")
        self.new_chat_button.setFixedHeight(theme.NEW_CHAT_HEIGHT)
        self.new_chat_button.setIcon(
            icons.icon(
                "plus",
                theme.BRAND_RED,
                16,
                active_tint=theme.BRAND_RED,
                disabled_tint=theme.TEXT_MUTED,
            )
        )
        self.new_chat_button.setIconSize(QSize(16, 16))
        self.new_chat_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_chat_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.new_chat_button.setAutoDefault(False)
        self.new_chat_button.setAccessibleName("New Chat")
        self.new_chat_button.setToolTip("Start a new chat")
        self.new_chat_button.clicked.connect(self._request_new_chat)
        return self.new_chat_button

    def _build_footer(self, parent: QWidget) -> QWidget:
        footer = QWidget(parent)
        footer.setObjectName("asideFooter")

        column = QVBoxLayout(footer)
        column.setContentsMargins(theme.SPACING_UNIT, 0, theme.SPACING_UNIT, 0)
        column.setSpacing(theme.SPACING_UNIT)

        badge = QLabel(footer)
        badge.setObjectName("sidebarBadge")
        badge.setFixedSize(40, 40)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(icons.pixmap("heart_pulse", theme.BRAND_RED, 20))
        badge.setAccessibleName("Always available")
        self.heartbeat_badge = badge

        note = QLabel("Help is always there\nwhen you need it.", footer)
        note.setObjectName("sidebarNote")
        note.setWordWrap(True)

        rule = QFrame(footer)
        rule.setObjectName("sidebarRule")
        rule.setFixedSize(28, 2)

        self.settings_button = NavButton(NavigationDestination.SETTINGS, footer)
        self.settings_button.clicked.connect(
            lambda: self.navigation_requested.emit(
                NavigationDestination.SETTINGS
            )
        )
        self._buttons[NavigationDestination.SETTINGS] = self.settings_button

        column.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
        column.addWidget(note)
        column.addWidget(rule, 0, Qt.AlignmentFlag.AlignLeft)
        column.addSpacing(theme.SPACING_UNIT)
        column.addWidget(self.settings_button)
        return footer

    def _build_collapsed_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setObjectName("sidebarCollapsed")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(
            (theme.SIDEBAR_COLLAPSED_WIDTH - _RAIL_CONTROL) // 2,
            theme.SPACING_UNIT * 2,
            (theme.SIDEBAR_COLLAPSED_WIDTH - _RAIL_CONTROL) // 2,
            theme.SPACING_UNIT * 2,
        )
        layout.setSpacing(theme.SPACING_UNIT)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.expand_button = self._rail_button(
            panel, "panel", "Expand sidebar", "Expand sidebar"
        )
        self.expand_button.clicked.connect(lambda: self.set_collapsed(False))
        layout.addWidget(self.expand_button, 0, Qt.AlignmentFlag.AlignHCenter)

        rule = QFrame(panel)
        rule.setObjectName("sidebarRailRule")
        rule.setFixedSize(_RAIL_CONTROL, 1)
        layout.addWidget(rule, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(theme.SPACING_UNIT)

        self.rail_new_chat = QPushButton(panel)
        self.rail_new_chat.setObjectName("newChatIcon")
        self.rail_new_chat.setFixedSize(_RAIL_CONTROL, _RAIL_CONTROL)
        self.rail_new_chat.setIcon(
            icons.icon(
                "plus",
                theme.BRAND_RED,
                18,
                active_tint=theme.BRAND_RED,
            )
        )
        self.rail_new_chat.setIconSize(QSize(18, 18))
        self.rail_new_chat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rail_new_chat.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.rail_new_chat.setAutoDefault(False)
        self.rail_new_chat.setAccessibleName("New Chat")
        self.rail_new_chat.setToolTip("New Chat")
        self.rail_new_chat.clicked.connect(self._request_new_chat)
        layout.addWidget(self.rail_new_chat, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(theme.SPACING_UNIT)

        self._rail_session_list = QWidget(panel)
        self._rail_session_list.setObjectName("railSessionList")
        self._rail_session_layout = QVBoxLayout(self._rail_session_list)
        self._rail_session_layout.setContentsMargins(0, 0, 0, 0)
        self._rail_session_layout.setSpacing(4)
        layout.addWidget(self._rail_session_list)

        layout.addStretch(1)

        self.rail_badge = QLabel(panel)
        self.rail_badge.setObjectName("sidebarBadge")
        self.rail_badge.setFixedSize(40, 40)
        self.rail_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rail_badge.setPixmap(icons.pixmap("heart_pulse", theme.BRAND_RED, 20))
        self.rail_badge.setAccessibleName("Always available")
        self.rail_badge.setToolTip("Help is always there when you need it.")
        layout.addWidget(self.rail_badge, 0, Qt.AlignmentFlag.AlignHCenter)

        self.rail_settings = QPushButton(panel)
        self.rail_settings.setObjectName("railButton")
        self.rail_settings.setFixedSize(_RAIL_CONTROL, _RAIL_CONTROL)
        self.rail_settings.setIconSize(QSize(18, 18))
        self.rail_settings.setIcon(
            icons.icon(
                "settings",
                theme.TEXT_SECONDARY,
                18,
                active_tint=theme.TEXT_PRIMARY,
            )
        )
        self.rail_settings.setCheckable(True)
        self.rail_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.rail_settings.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.rail_settings.setAutoDefault(False)
        self.rail_settings.setAccessibleName("Settings")
        self.rail_settings.setToolTip("Settings")
        self.rail_settings.clicked.connect(
            lambda: self.navigation_requested.emit(
                NavigationDestination.SETTINGS
            )
        )
        layout.addWidget(self.rail_settings, 0, Qt.AlignmentFlag.AlignHCenter)
        return panel

    def _build_hidden_destinations(self) -> None:
        """Keep the Assist/History navigation API without cluttering the rail.

        The visible chat list replaces the old History-style top-level rows, but
        the existing navigation destinations and page APIs remain callable.
        """

        self._hidden_nav = QWidget(self)
        self._hidden_nav.setVisible(False)
        column = QVBoxLayout(self._hidden_nav)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        for destination in (
            NavigationDestination.ASSIST,
            NavigationDestination.HISTORY,
        ):
            button = NavButton(destination, self._hidden_nav)
            button.clicked.connect(
                lambda _checked=False, dest=destination: (
                    self.navigation_requested.emit(dest)
                )
            )
            self._buttons[destination] = button
            column.addWidget(button)
        self._layout.addWidget(self._hidden_nav)

    @staticmethod
    def _rail_button(
        parent: QWidget,
        icon_name: str,
        accessible_name: str,
        tooltip: str,
        *,
        size: int = _RAIL_CONTROL,
    ) -> QPushButton:
        button = QPushButton(parent)
        button.setObjectName("railButton")
        button.setFixedSize(size, size)
        button.setIconSize(QSize(16, 16))
        button.setIcon(
            icons.icon(
                icon_name,
                theme.TEXT_SECONDARY,
                16,
                active_tint=theme.TEXT_PRIMARY,
            )
        )
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.setAutoDefault(False)
        button.setAccessibleName(accessible_name)
        button.setToolTip(tooltip)
        return button

    # -- public API -------------------------------------------------------

    def button(self, destination: NavigationDestination) -> NavButton:
        return self._buttons[destination]

    def set_selected(self, destination: NavigationDestination) -> None:
        for candidate, button in self._buttons.items():
            button.setChecked(candidate is destination)
        self.rail_settings.setChecked(destination is NavigationDestination.SETTINGS)
        self._sync_rail_property(self.rail_settings)

    def set_conversation_controller(self, controller) -> None:
        """Connect the session list and actions to the conversation controller."""

        if controller is self._conversation:
            return
        previous = self._conversation
        if previous is not None:
            for signal, slot in (
                (previous.sessions_changed, self._on_sessions_changed),
                (previous.active_session_changed, self._on_sessions_changed),
                (previous.generation_state_changed, self._on_generation_state),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):  # pragma: no cover - Qt detail
                    pass

        self._conversation = controller
        controller.sessions_changed.connect(self._on_sessions_changed)
        controller.active_session_changed.connect(self._on_sessions_changed)
        controller.generation_state_changed.connect(self._on_generation_state)
        self._rebuild_sessions()

    def conversation_controller(self):
        return self._conversation

    def set_collapsed(self, collapsed: bool) -> None:
        """Switch between the expanded sidebar and the compact icon rail."""

        collapsed = bool(collapsed)
        self._collapsed = collapsed
        self._expanded_panel.setVisible(not collapsed)
        self._collapsed_panel.setVisible(collapsed)
        self.setFixedWidth(
            theme.SIDEBAR_COLLAPSED_WIDTH if collapsed else theme.SIDEBAR_WIDTH
        )
        self._rebuild_sessions()
        target = self.expand_button if collapsed else self.collapse_button
        target.setFocus()
        motion.fade_in(
            self._collapsed_panel if collapsed else self._expanded_panel,
            duration_ms=theme.MOTION_FAST_MS,
        )

    def is_collapsed(self) -> bool:
        return self._collapsed

    def session_row(self, session_id: str) -> SessionRow | None:
        rows = self._rail_rows if self._collapsed else self._rows
        return rows.get(session_id)

    def clear_active_chat(self, *, confirm=None) -> bool:
        """Ask for confirmation, then clear only the active in-memory chat."""

        controller = self._conversation
        if controller is None:
            return False
        if controller.is_generating():
            return False
        confirm = confirm or self._confirm_clear
        if not confirm():
            return False
        return bool(controller.clear_active_chat())

    # -- session list -----------------------------------------------------

    def _request_new_chat(self) -> None:
        controller = self._conversation
        if controller is None or controller.is_generating():
            return
        controller.new_chat()
        self.navigation_requested.emit(NavigationDestination.ASSIST)

    def _on_sessions_changed(self, _payload: object = None) -> None:
        self._rebuild_sessions()

    def _on_generation_state(self, state: str) -> None:
        busy = state == "generating"
        self.new_chat_button.setEnabled(not busy)
        self.rail_new_chat.setEnabled(not busy)
        for rows in (self._rows, self._rail_rows):
            for row in rows.values():
                row.setEnabled(not busy)

    def _rebuild_sessions(self) -> None:
        controller = self._conversation
        sessions = controller.sessions() if controller is not None else ()
        active_id = None
        if controller is not None:
            active_id = controller.active_session().session_id

        self._clear_layout(self._session_layout)
        self._clear_layout(self._rail_session_layout)
        self._rows = {}
        self._rail_rows = {}

        for session in sessions:
            row = self._make_row(session, active_id, collapsed=False)
            self._session_layout.addWidget(row)
            self._rows[session.session_id] = row

        for session in sessions[:_RAIL_SESSION_LIMIT]:
            float_row = self._make_row(session, active_id, collapsed=True)
            self._rail_session_layout.addWidget(
                float_row, 0, Qt.AlignmentFlag.AlignHCenter
            )
            self._rail_rows[session.session_id] = float_row

        busy = bool(controller is not None and controller.is_generating())
        self._on_generation_state("generating" if busy else "idle")

    def _make_row(
        self, session: ChatSession, active_id: str | None, *, collapsed: bool
    ) -> SessionRow:
        row = SessionRow(
            session,
            collapsed=collapsed,
            parent=(
                self._rail_session_list if collapsed else self._session_list
            ),
        )
        row.setChecked(session.session_id == active_id)
        row.clicked.connect(
            lambda _checked=False, sid=session.session_id: self._select_row(sid)
        )
        row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        row.customContextMenuRequested.connect(
            lambda point, sid=session.session_id, target=row: (
                self._show_session_menu(sid, target, point)
            )
        )
        return row

    def _select_row(self, session_id: str) -> None:
        controller = self._conversation
        if controller is None:
            return
        if controller.select_chat(session_id):
            self.navigation_requested.emit(NavigationDestination.ASSIST)

    def _show_session_menu(
        self, session_id: str, row: SessionRow, point
    ) -> None:
        controller = self._conversation
        if controller is None:
            return
        menu = QMenu(row)
        clear_action = menu.addAction("Clear chat")
        clear_action.setEnabled(
            not controller.is_generating()
            and controller.active_session().session_id == session_id
        )
        chosen = menu.exec(row.mapToGlobal(point))
        if chosen is clear_action:
            self.clear_active_chat()

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _confirm_clear(self) -> bool:
        dialog = QMessageBox(self)
        dialog.setIconPixmap(icons.pixmap("trash", theme.TEXT_SECONDARY, 26))
        dialog.setWindowTitle("Clear chat")
        dialog.setText("Clear this chat?")
        dialog.setInformativeText(
            "The messages in this session will be removed. Other chats stay, "
            "and Ivyago does not keep a copy."
        )
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Clear")
        dialog.button(QMessageBox.StandardButton.No).setText("Cancel")
        theme.apply_dialog_theme(dialog)
        motion.fade_dialog(dialog)
        return dialog.exec() == QMessageBox.StandardButton.Yes

    @staticmethod
    def _sync_rail_property(button: QPushButton) -> None:
        theme.set_state(button, "active", "true" if button.isChecked() else "false")
