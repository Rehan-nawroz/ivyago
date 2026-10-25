"""Shared visual foundation for the Ivyago desktop shell.

Every color, size, radius, and type value used by the shell lives here so that
individual widgets never invent their own visual language. The values follow
the approved Phase 1.5 reference: near-black surfaces, a single red brand
accent, and quiet gray text.
"""

from PySide6.QtCore import QEasingCurve
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QWidget

# --- Layout rhythm -------------------------------------------------------

SPACING_UNIT = 8

MINIMUM_WINDOW_WIDTH = 1024
MINIMUM_WINDOW_HEIGHT = 700
INITIAL_WINDOW_WIDTH = 1200
INITIAL_WINDOW_HEIGHT = 800

SIDEBAR_WIDTH = 256
SIDEBAR_COLLAPSED_WIDTH = 64
TITLE_BAR_HEIGHT = 40
NAV_ITEM_HEIGHT = 44
CONTENT_PADDING = 32
COMPOSER_MAX_WIDTH = 672
HERO_TEXT_MAX_WIDTH = 520
WINDOW_RESIZE_MARGIN = 6
SETTINGS_MAX_WIDTH = 760
LEGAL_TEXT_MAX_WIDTH = 660

# --- Motion --------------------------------------------------------------
# Short, non-blocking entrances only. Page and dialog transitions answer a
# user action (navigation, opening a document) and never gate state changes.
MOTION_FAST_MS = 120
MOTION_BASE_MS = 160
MOTION_SLOW_MS = 220
MOTION_MAX_MS = 220
MOTION_EASING = QEasingCurve.Type.OutCubic

# --- Conversation (Phase 4) ---------------------------------------------

CONVERSATION_MAX_WIDTH = 720
CHAT_BUBBLE_MAX_WIDTH = 620
CHAT_ROW_HEIGHT = 44
RAIL_BUTTON_SIZE = 40
MESSAGE_ACTION_SIZE = 24
NEW_CHAT_HEIGHT = 44

# --- Brand ---------------------------------------------------------------

BRAND_RED = "#FF1124"
BRAND_CRIMSON = "#E11D2D"
BRAND_DARK_RED = "#7A0C14"
BRAND_RED_SOFT = "#3A0D13"

# --- Surfaces ------------------------------------------------------------

SURFACE_WINDOW = "#08080C"
SURFACE_TITLE_BAR = "#07070A"
SURFACE_SIDEBAR = "#070709"
SURFACE_CARD = "#0E1015"
SURFACE_INPUT = "#090B0F"
SURFACE_STATUS_PILL = "#0C0F16"
SURFACE_BADGE = "#160609"
SURFACE_NAV_HOVER = "#12141A"
SURFACE_CONTROL_HOVER = "#1A1D24"
SURFACE_RESPONSE = "#0E1015"
SURFACE_STOP_HOVER = "#160609"
SURFACE_USER_BUBBLE = "#18202E"
SURFACE_ASSISTANT_BUBBLE = "#0E1015"
SURFACE_NEW_CHAT = "#170A0D"
SURFACE_NEW_CHAT_HOVER = "#210D11"
SURFACE_AVATAR_TOP = "#180306"
SURFACE_AVATAR_BOTTOM = "#0A0203"
NAV_ACTIVE_LEFT = "#2A0D12"
NAV_ACTIVE_RIGHT = "#14080B"
SURFACE_SETTINGS_CARD = "#0B0D12"
SURFACE_SETTINGS_CARD_HOVER = "#10131A"
SURFACE_DANGER = "#130A0D"
SURFACE_DANGER_HOVER = "#1E0C11"

# --- Lines ---------------------------------------------------------------

BORDER_WINDOW = "#1C1F28"
BORDER_QUIET = "#14161C"
BORDER_SIDEBAR = "#14161F"
BORDER_INPUT = "#1D212B"
BORDER_STATUS_PILL = "#232733"
BORDER_NAV_ACTIVE = "#3E1117"
BORDER_BADGE = "#7A0C14"
BORDER_USER_BUBBLE = "#2A3547"
BORDER_ASSISTANT_BUBBLE = "#3E1117"
BORDER_NEW_CHAT = "#7A0C14"
BORDER_FOCUS = "#FF5A66"
BORDER_STRONG = "#2A2F3B"
BORDER_DANGER = "#4A1218"
BORDER_DANGER_HOVER = "#8E1620"

# --- Text ----------------------------------------------------------------

TEXT_PRIMARY = "#FFFFFF"
TEXT_BODY = "#E5E7EB"
TEXT_SECONDARY = "#9CA3AF"
TEXT_MUTED = "#6B7280"
TEXT_WARNING = "#FF9AA5"
TEXT_USER_BUBBLE = "#E8EDF7"
TEXT_CAUTION = "#8A8F9B"
TEXT_DISABLED = "#6A7180"
TEXT_SETTINGS_VALUE = "#A8AEBB"

# --- Typography ----------------------------------------------------------

FONT_FAMILY = "Segoe UI"
PREFERRED_FONT_FAMILIES = ("Inter", "Segoe UI Variable Text", "Segoe UI", "Arial")
FONT_SIZE_DISPLAY = 36
FONT_SIZE_HERO_SUBTITLE = 20
FONT_SIZE_PAGE_TITLE = 22
FONT_SIZE_BRAND = 24
FONT_SIZE_BODY = 14
FONT_SIZE_SMALL = 12
FONT_SIZE_TINY = 11
FONT_SIZE_NAV = 14
FONT_SIZE_SECTION = 12
FONT_SIZE_CARD_TITLE = 13

# --- Shapes --------------------------------------------------------------

CONTROL_RADIUS = 8
CARD_RADIUS = 12
PILL_RADIUS = 24
BADGE_RADIUS = 20

RESPONSE_MAX_HEIGHT = 260
RESPONSE_RADIUS = 12


def repolish(widget: QWidget) -> None:
    """Re-evaluate a dynamic-property stylesheet rule for ``widget``."""

    style = widget.style()
    if style is None:  # pragma: no cover - only for deleted widgets
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_state(widget: QWidget, name: str, value: str) -> bool:
    """Set a dynamic style property and repolish only when it changed."""

    if widget.property(name) == value:
        return False
    widget.setProperty(name, value)
    repolish(widget)
    return True


def resolved_font_family() -> str:
    """Return the preferred installed interface font for this machine."""

    if QGuiApplication.instance() is None:
        return FONT_FAMILY
    available = set(QFontDatabase.families())
    for family in PREFERRED_FONT_FAMILIES:
        if family in available:
            return family
    return FONT_FAMILY


_DIALOG_STYLESHEET = f"""
QMessageBox, QDialog {{
    background: {SURFACE_CARD};
}}
QMessageBox QLabel, QDialog QLabel {{
    color: {TEXT_BODY};
    background: transparent;
    min-width: 260px;
}}
QMessageBox QPushButton, QDialog QPushButton {{
    color: {TEXT_BODY};
    background: {SURFACE_INPUT};
    border: 1px solid {BORDER_INPUT};
    border-radius: {CONTROL_RADIUS}px;
    padding: 7px 18px;
    min-width: 64px;
}}
QMessageBox QPushButton:hover, QDialog QPushButton:hover {{
    background: {SURFACE_CONTROL_HOVER};
    border: 1px solid {BORDER_STRONG};
}}
QMessageBox QPushButton:pressed, QDialog QPushButton:pressed {{
    background: {BORDER_STRONG};
}}
QMessageBox QPushButton:focus, QDialog QPushButton:focus {{
    border: 1px solid {BORDER_FOCUS};
}}
QMessageBox QPushButton:disabled, QDialog QPushButton:disabled {{
    color: {TEXT_DISABLED};
    background: {SURFACE_SIDEBAR};
    border: 1px solid {BORDER_QUIET};
}}
"""


def build_dialog_stylesheet() -> str:
    """Return the shared confirmation-dialog styling."""

    return _DIALOG_STYLESHEET


def apply_dialog_theme(dialog) -> None:
    """Apply the Ivyago dark dialog styling to one dialog instance."""

    dialog.setStyleSheet(build_dialog_stylesheet())


def build_app_stylesheet() -> str:
    """Build the shared Qt stylesheet from the centralized theme values."""

    return f"""
    QWidget {{
        color: {TEXT_BODY};
        font-family: {resolved_font_family()};
        font-size: {FONT_SIZE_BODY}px;
    }}
    QToolTip {{
        color: {TEXT_BODY};
        background: {SURFACE_CARD};
        border: 1px solid {BORDER_STATUS_PILL};
        padding: 6px 10px;
        font-size: {FONT_SIZE_SMALL}px;
    }}
    QMainWindow#mainWindow, QWidget#appRoot {{
        background: {SURFACE_WINDOW};
        border: 1px solid {BORDER_WINDOW};
    }}
    QWidget#appBody {{
        background: {SURFACE_WINDOW};
    }}
    QFrame#sidebar {{
        background: {SURFACE_SIDEBAR};
        border-right: 1px solid {BORDER_SIDEBAR};
    }}
    QWidget#titleBar {{
        background: {SURFACE_TITLE_BAR};
        border-bottom: 1px solid {BORDER_QUIET};
    }}
    QPushButton#windowButton, QPushButton#windowClose {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 0px;
    }}
    QPushButton#windowButton:hover {{
        background: {SURFACE_CONTROL_HOVER};
    }}
    QPushButton#windowButton:pressed {{
        background: {BORDER_STRONG};
    }}
    QPushButton#windowClose:hover {{
        background: {BRAND_CRIMSON};
    }}
    QPushButton#windowClose:pressed {{
        background: {BRAND_DARK_RED};
    }}
    QLabel#brandTitle {{
        color: {BRAND_RED};
        font-size: {FONT_SIZE_BRAND}px;
        font-weight: 800;
        letter-spacing: -0.4px;
    }}
    QLabel#brandMarkFallback {{
        color: {BRAND_RED};
        font-size: 26px;
        font-weight: 800;
    }}
    QLabel#brandTagline {{
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_TINY}px;
        font-weight: 500;
    }}
    QFrame#statusPill {{
        background: {SURFACE_STATUS_PILL};
        border: 1px solid {BORDER_STATUS_PILL};
        border-radius: 14px;
    }}
    QLabel#statusText {{
        color: {TEXT_BODY};
        font-size: {FONT_SIZE_SMALL}px;
        font-weight: 500;
    }}
    QLabel#heroGreeting {{
        color: {TEXT_PRIMARY};
        font-size: {FONT_SIZE_DISPLAY}px;
        font-weight: 800;
        letter-spacing: -0.6px;
    }}
    QLabel#heroSubtitle {{
        color: {TEXT_BODY};
        font-size: {FONT_SIZE_HERO_SUBTITLE}px;
        font-weight: 700;
    }}
    QLabel#heroBody {{
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_BODY}px;
    }}
    QLabel#heroAvatar {{
        background: qlineargradient(
            x1: 0, y1: 0, x2: 0, y2: 1,
            stop: 0 {SURFACE_AVATAR_TOP},
            stop: 1 {SURFACE_AVATAR_BOTTOM}
        );
        border: 2px solid {BRAND_RED};
        border-radius: 64px;
    }}
    QLabel#pageTitle {{
        color: {TEXT_PRIMARY};
        font-size: {FONT_SIZE_PAGE_TITLE}px;
        font-weight: 700;
    }}
    QLabel#pageMessage {{
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_BODY}px;
    }}
    QLabel#emptyStateIcon {{
        background: {SURFACE_CARD};
        border: 1px solid {BORDER_STATUS_PILL};
        border-radius: 30px;
    }}
    QLabel#composerNote {{
        color: {TEXT_MUTED};
        font-size: {FONT_SIZE_TINY}px;
    }}
    QLabel#composerNote[tone="error"] {{
        color: {TEXT_WARNING};
    }}
    QLabel#sourceNote {{
        color: {TEXT_MUTED};
        font-size: {FONT_SIZE_TINY}px;
        background: transparent;
        border: none;
        padding: 0px;
    }}
    QFrame#responsePanel {{
        background: {SURFACE_RESPONSE};
        border: 1px solid {BORDER_INPUT};
        border-radius: {RESPONSE_RADIUS}px;
    }}
    QPlainTextEdit#responseView {{
        color: {TEXT_BODY};
        font-size: {FONT_SIZE_BODY}px;
        background: transparent;
        border: none;
        padding: 0px;
        selection-background-color: {BRAND_CRIMSON};
        selection-color: {TEXT_PRIMARY};
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {BORDER_NAV_ACTIVE};
        border-radius: 3px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {BRAND_DARK_RED};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QLabel#sidebarNote {{
        color: {TEXT_BODY};
        font-size: {FONT_SIZE_SMALL}px;
        font-weight: 500;
    }}
    QLabel#sidebarBadge {{
        background: {SURFACE_BADGE};
        border: 1px solid {BORDER_BADGE};
        border-radius: {BADGE_RADIUS}px;
    }}
    QFrame#sidebarRule {{
        background: {BRAND_RED};
        border: none;
        border-radius: 1px;
    }}
    QFrame#composer {{
        background: {SURFACE_INPUT};
        border: 1px solid {BORDER_INPUT};
        border-radius: 26px;
    }}
    QFrame#composer[focused="true"] {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QFrame#composer[busy="true"] {{
        border: 1px solid {BORDER_STATUS_PILL};
    }}
    QLineEdit#messageInput {{
        background: transparent;
        border: none;
        color: {TEXT_BODY};
        font-size: {FONT_SIZE_BODY}px;
        placeholder-text-color: {TEXT_MUTED};
        selection-background-color: {BRAND_RED};
        selection-color: {TEXT_PRIMARY};
    }}
    QLineEdit#messageInput:disabled {{
        color: {TEXT_MUTED};
    }}
    QPushButton#iconButton {{
        background: transparent;
        border: none;
        border-radius: 18px;
        padding: 0px;
    }}
    QPushButton#iconButton:hover {{
        background: {SURFACE_CONTROL_HOVER};
    }}
    QPushButton#iconButton:pressed {{
        background: {BORDER_STRONG};
    }}
    QPushButton#iconButton:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QPushButton#iconButton:disabled {{
        background: transparent;
    }}
    QPushButton#sendButton {{
        background: {BRAND_RED};
        border: 1px solid transparent;
        border-radius: 18px;
        padding: 0px;
    }}
    QPushButton#sendButton:hover {{
        background: {BRAND_CRIMSON};
    }}
    QPushButton#sendButton:pressed {{
        background: {BRAND_DARK_RED};
    }}
    QPushButton#sendButton:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QPushButton#sendButton:disabled {{
        background: {BRAND_RED_SOFT};
        border: 1px solid {BORDER_DANGER};
    }}
    QPushButton#stopButton {{
        background: transparent;
        border: 1px solid {BRAND_DARK_RED};
        border-radius: 18px;
        padding: 0px;
    }}
    QPushButton#stopButton:hover {{
        background: {SURFACE_STOP_HOVER};
        border: 1px solid {BRAND_CRIMSON};
    }}
    QPushButton#stopButton:pressed {{
        background: {SURFACE_DANGER_HOVER};
    }}
    QPushButton#stopButton:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QPushButton#stopButton:disabled {{
        border: 1px solid {BORDER_INPUT};
    }}
    /* --- Phase 4 conversation thread --- */
    QScrollArea#conversationThread {{
        background: transparent;
        border: none;
    }}
    QWidget#threadViewport, QWidget#threadBody, QWidget#threadContent,
    QWidget#emptyStatePage {{
        background: transparent;
    }}
    QFrame#userBubble {{
        background: {SURFACE_USER_BUBBLE};
        border: 1px solid {BORDER_USER_BUBBLE};
        border-radius: {CARD_RADIUS}px;
    }}
    QLabel#userMessageText {{
        color: {TEXT_USER_BUBBLE};
        font-size: {FONT_SIZE_BODY}px;
        background: transparent;
        border: none;
    }}
    QFrame#assistantBubble {{
        background: {SURFACE_ASSISTANT_BUBBLE};
        border: 1px solid {BORDER_ASSISTANT_BUBBLE};
        border-radius: {CARD_RADIUS}px;
    }}
    QPlainTextEdit#messageBody {{
        color: {TEXT_BODY};
        font-size: {FONT_SIZE_BODY}px;
        background: transparent;
        border: none;
        padding: 0px;
        selection-background-color: {BRAND_CRIMSON};
        selection-color: {TEXT_PRIMARY};
    }}
    QLabel#messageTime {{
        color: {TEXT_MUTED};
        font-size: {FONT_SIZE_TINY}px;
        background: transparent;
        border: none;
    }}
    QLabel#messageSource {{
        color: {TEXT_MUTED};
        font-size: {FONT_SIZE_TINY}px;
        background: transparent;
        border: none;
    }}
    QLabel#messageStreaming {{
        color: {TEXT_MUTED};
        font-size: {FONT_SIZE_TINY}px;
        background: transparent;
        border: none;
    }}
    QLabel#messageCaution {{
        color: {TEXT_CAUTION};
        font-size: {FONT_SIZE_TINY}px;
        background: transparent;
        border: none;
        padding: 2px 2px 0px 2px;
    }}
    QPushButton#messageAction {{
        background: transparent;
        border: none;
        border-radius: 6px;
        padding: 0px;
    }}
    QPushButton#messageAction:hover {{
        background: {SURFACE_CONTROL_HOVER};
    }}
    QPushButton#messageAction:pressed {{
        background: {BORDER_STRONG};
    }}
    QPushButton#messageAction:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QPushButton#newChatButton {{
        background: {SURFACE_NEW_CHAT};
        border: 1px solid {BORDER_NEW_CHAT};
        border-radius: {CONTROL_RADIUS}px;
        color: {TEXT_PRIMARY};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 600;
        text-align: left;
        padding-left: 14px;
    }}
    QPushButton#newChatButton:hover {{
        background: {SURFACE_NEW_CHAT_HOVER};
        border: 1px solid {BRAND_CRIMSON};
    }}
    QPushButton#newChatButton:pressed {{
        background: {SURFACE_DANGER_HOVER};
    }}
    QPushButton#newChatButton:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QPushButton#newChatButton:disabled {{
        color: {TEXT_DISABLED};
        border: 1px solid {BORDER_QUIET};
        background: {SURFACE_SIDEBAR};
    }}
    QPushButton#railButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {CONTROL_RADIUS}px;
        padding: 0px;
    }}
    QPushButton#railButton:hover {{
        background: {SURFACE_NAV_HOVER};
        border: 1px solid {BORDER_STATUS_PILL};
    }}
    QPushButton#railButton:pressed {{
        background: {BORDER_STRONG};
    }}
    QPushButton#railButton:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QPushButton#railButton:disabled {{
        background: transparent;
        border: 1px solid transparent;
    }}
    QPushButton#railButton[active="true"] {{
        background: {NAV_ACTIVE_LEFT};
    }}
    QPushButton#newChatIcon {{
        background: {SURFACE_NEW_CHAT};
        border: 1px solid {BORDER_NEW_CHAT};
        border-radius: {CONTROL_RADIUS}px;
        padding: 0px;
    }}
    QPushButton#newChatIcon:hover {{
        background: {SURFACE_NEW_CHAT_HOVER};
    }}
    QFrame#sidebarRailRule {{
        background: {BORDER_SIDEBAR};
        border: none;
    }}
    /* --- Shared secondary controls (Settings, legal documents) --- */
    QPushButton#settingsAction, QPushButton#backButton {{
        color: {TEXT_BODY};
        background: {SURFACE_SETTINGS_CARD};
        border: 1px solid {BORDER_QUIET};
        border-radius: {CONTROL_RADIUS}px;
        padding: 10px 14px;
        text-align: left;
        font-size: {FONT_SIZE_BODY}px;
    }}
    QPushButton#settingsAction:hover, QPushButton#backButton:hover {{
        background: {SURFACE_SETTINGS_CARD_HOVER};
        border: 1px solid {BORDER_STRONG};
        color: {TEXT_PRIMARY};
    }}
    QPushButton#settingsAction:pressed, QPushButton#backButton:pressed {{
        background: {SURFACE_NAV_HOVER};
    }}
    QPushButton#settingsAction:focus, QPushButton#backButton:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QPushButton#settingsAction:disabled, QPushButton#backButton:disabled {{
        color: {TEXT_DISABLED};
        background: {SURFACE_SIDEBAR};
        border: 1px solid {BORDER_QUIET};
    }}
    QPushButton#backButton {{
        padding: 7px 14px 7px 10px;
    }}
    QPushButton#clearCurrentButton, QPushButton#clearAllButton {{
        color: {TEXT_BODY};
        background: {SURFACE_DANGER};
        border: 1px solid {BORDER_DANGER};
        border-radius: {CONTROL_RADIUS}px;
        padding: 10px 14px;
        text-align: left;
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 600;
    }}
    QPushButton#clearCurrentButton:hover, QPushButton#clearAllButton:hover {{
        background: {SURFACE_DANGER_HOVER};
        border: 1px solid {BORDER_DANGER_HOVER};
        color: {TEXT_PRIMARY};
    }}
    QPushButton#clearCurrentButton:pressed, QPushButton#clearAllButton:pressed {{
        background: {SURFACE_STOP_HOVER};
    }}
    QPushButton#clearCurrentButton:focus, QPushButton#clearAllButton:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QPushButton#clearCurrentButton:disabled, QPushButton#clearAllButton:disabled {{
        color: {TEXT_DISABLED};
        background: {SURFACE_SIDEBAR};
        border: 1px solid {BORDER_QUIET};
    }}
    QPushButton#clearAllButton {{
        border: 1px solid {BORDER_DANGER_HOVER};
        color: {TEXT_PRIMARY};
    }}
    QPushButton#repositoryLink {{
        color: {TEXT_SECONDARY};
        background: transparent;
        border: 1px solid transparent;
        border-radius: {CONTROL_RADIUS}px;
        padding: 8px 12px;
        text-align: left;
        font-size: {FONT_SIZE_SMALL}px;
    }}
    QPushButton#repositoryLink:hover {{
        color: {TEXT_BODY};
        background: {SURFACE_SETTINGS_CARD};
        border: 1px solid {BORDER_QUIET};
    }}
    QPushButton#repositoryLink:pressed {{
        background: {SURFACE_NAV_HOVER};
    }}
    QPushButton#repositoryLink:focus {{
        border: 1px solid {BORDER_FOCUS};
        color: {TEXT_BODY};
    }}
    QLabel#pageSubtitle {{
        color: {TEXT_MUTED};
        font-size: {FONT_SIZE_SMALL}px;
        background: transparent;
    }}
    QLabel#settingsSectionHeading {{
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_SECTION}px;
        font-weight: 700;
        letter-spacing: 0.4px;
        background: transparent;
        padding-top: 4px;
    }}
    QFrame#settingsCard {{
        background: {SURFACE_SETTINGS_CARD};
        border: 1px solid {BORDER_QUIET};
        border-radius: 10px;
    }}
    QLabel#settingsCardTitle {{
        color: {TEXT_PRIMARY};
        font-size: {FONT_SIZE_CARD_TITLE}px;
        font-weight: 600;
        background: transparent;
    }}
    QLabel#settingsCardValue {{
        color: {TEXT_BODY};
        font-size: {FONT_SIZE_CARD_TITLE}px;
        font-weight: 500;
        background: transparent;
    }}
    QLabel#settingsCardDetail {{
        color: {TEXT_SETTINGS_VALUE};
        font-size: {FONT_SIZE_SMALL}px;
        background: transparent;
    }}
    QLabel#assistantStatusLabel {{
        color: {TEXT_BODY};
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 600;
        background: transparent;
    }}
    QLabel#settingsHint {{
        color: {TEXT_MUTED};
        font-size: {FONT_SIZE_SMALL}px;
        background: transparent;
    }}
    QScrollArea#settingsScroll, QScrollArea#legalScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollArea#settingsScroll > QWidget > QWidget,
    QWidget#legalBodyContainer {{
        background: transparent;
    }}
    QLabel#legalBody {{
        color: {TEXT_BODY};
        font-size: 15px;
        background: transparent;
        padding: 0px;
    }}
    QLabel#attributionLabel {{
        color: {TEXT_MUTED};
        font-size: {FONT_SIZE_TINY}px;
        background: transparent;
    }}
    QFrame#legalRule {{
        background: {BORDER_QUIET};
        border: none;
    }}
    QMenu {{
        background: {SURFACE_CARD};
        border: 1px solid {BORDER_STATUS_PILL};
        border-radius: 8px;
        padding: 5px;
    }}
    QMenu::item {{
        color: {TEXT_BODY};
        padding: 7px 20px 7px 12px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background: {SURFACE_CONTROL_HOVER};
    }}
    QMenu::item:disabled {{
        color: {TEXT_DISABLED};
    }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER_QUIET};
        margin: 4px 8px;
    }}
    QMessageBox {{
        background: {SURFACE_CARD};
    }}
    QMessageBox QLabel {{
        color: {TEXT_BODY};
        background: transparent;
        min-width: 260px;
    }}
    QMessageBox QPushButton {{
        color: {TEXT_BODY};
        background: {SURFACE_INPUT};
        border: 1px solid {BORDER_INPUT};
        border-radius: {CONTROL_RADIUS}px;
        padding: 7px 18px;
        min-width: 64px;
    }}
    QMessageBox QPushButton:hover {{
        background: {SURFACE_CONTROL_HOVER};
        border: 1px solid {BORDER_STRONG};
    }}
    QMessageBox QPushButton:pressed {{
        background: {BORDER_STRONG};
    }}
    QMessageBox QPushButton:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QMessageBox QPushButton:default {{
        border: 1px solid {BORDER_NAV_ACTIVE};
    }}
    /* --- First-run model setup --- */
    QDialog#modelSetupDialog {{
        background: {SURFACE_CARD};
    }}
    QLabel#setupTitle {{
        color: {TEXT_PRIMARY};
        font-size: {FONT_SIZE_PAGE_TITLE}px;
        font-weight: 700;
        background: transparent;
    }}
    QLabel#setupBody {{
        color: {TEXT_BODY};
        font-size: {FONT_SIZE_BODY}px;
        background: transparent;
    }}
    QLabel#setupDetail {{
        color: {TEXT_MUTED};
        font-size: {FONT_SIZE_SMALL}px;
        background: transparent;
    }}
    QLabel#setupStatus {{
        color: {TEXT_SECONDARY};
        font-size: {FONT_SIZE_SMALL}px;
        background: transparent;
    }}
    QLabel#setupError {{
        color: {TEXT_WARNING};
        font-size: {FONT_SIZE_SMALL}px;
        background: transparent;
    }}
    QFrame#setupRule {{
        background: {BORDER_QUIET};
        border: none;
    }}
    QPushButton#primaryButton {{
        background: {BRAND_RED};
        color: {TEXT_PRIMARY};
        border: 1px solid transparent;
        border-radius: {CONTROL_RADIUS}px;
        padding: 9px 20px;
        font-size: {FONT_SIZE_BODY}px;
        font-weight: 600;
    }}
    QPushButton#primaryButton:hover {{
        background: {BRAND_CRIMSON};
    }}
    QPushButton#primaryButton:pressed {{
        background: {BRAND_DARK_RED};
    }}
    QPushButton#primaryButton:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QPushButton#primaryButton:disabled {{
        background: {BRAND_RED_SOFT};
        color: {TEXT_DISABLED};
        border: 1px solid {BORDER_DANGER};
    }}
    QPushButton#secondaryButton {{
        background: {SURFACE_INPUT};
        color: {TEXT_BODY};
        border: 1px solid {BORDER_INPUT};
        border-radius: {CONTROL_RADIUS}px;
        padding: 9px 18px;
        font-size: {FONT_SIZE_BODY}px;
    }}
    QPushButton#secondaryButton:hover {{
        background: {SURFACE_CONTROL_HOVER};
        border: 1px solid {BORDER_STRONG};
    }}
    QPushButton#secondaryButton:pressed {{
        background: {BORDER_STRONG};
    }}
    QPushButton#secondaryButton:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
    QPushButton#secondaryButton:disabled {{
        color: {TEXT_DISABLED};
        background: {SURFACE_SIDEBAR};
        border: 1px solid {BORDER_QUIET};
    }}
    QProgressBar#setupProgress {{
        background: {SURFACE_INPUT};
        border: 1px solid {BORDER_INPUT};
        border-radius: 5px;
        min-height: 8px;
        max-height: 8px;
        text-align: center;
    }}
    QProgressBar#setupProgress::chunk {{
        background: {BRAND_RED};
        border-radius: 4px;
    }}
    """


def color(value: str) -> QColor:
    """Return a QColor for callers that need a palette value."""

    return QColor(value)
