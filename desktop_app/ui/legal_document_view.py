"""Reusable native, offline legal-document view.

The document sits in a centered reading column so long policy text keeps a
comfortable measure, and the Back action stays the first, keyboard-reachable
control. Nothing here opens a URL or requires a connection.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme
from .backdrop import BackdropFrame


class LegalDocumentView(BackdropFrame):
    """Scrollable, selectable, plain-text document with a Back action."""

    def __init__(
        self,
        title: str,
        body: str,
        attribution: str,
        on_back: Callable[[], None],
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("legalDocumentView")
        self._on_back = on_back

        layout = QVBoxLayout(self)
        # Keep the document title comfortably below the window chrome while
        # leaving the body centered in the remaining reading area.
        layout.setContentsMargins(32, 64, 32, 28)
        layout.setSpacing(theme.SPACING_UNIT)

        self.back_button = QPushButton("Back", self)
        self.back_button.setObjectName("backButton")
        self.back_button.setAccessibleName("Back to Settings")
        self.back_button.setAccessibleDescription(
            "Return to the Settings page. Escape also goes back."
        )
        self.back_button.setToolTip("Back to Settings")
        self.back_button.setIcon(
            icons.icon("arrow_left", theme.TEXT_SECONDARY, 16)
        )
        self.back_button.setIconSize(icons.icon_size(16))
        self.back_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.back_button.setAutoDefault(False)
        self.back_button.clicked.connect(self._go_back)

        self.page_title = QLabel(title, self)
        self.page_title.setObjectName("pageTitle")
        self.page_title.setAccessibleName(f"{title} document title")

        caption = QLabel("Bundled with Ivyago. No connection required.", self)
        caption.setObjectName("pageSubtitle")
        caption.setWordWrap(True)

        rule = QFrame(self)
        rule.setObjectName("legalRule")
        rule.setFixedHeight(1)

        self.body_text = QLabel(body, self)
        self.body_text.setWordWrap(True)
        self.body_text.setTextFormat(Qt.TextFormat.PlainText)
        self.body_text.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.body_text.setMargin(0)
        self.body_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.body_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.body_text.setObjectName("legalBody")
        self.body_text.setAccessibleName(f"{title} text")

        body_container = QWidget(self)
        body_container.setObjectName("legalBodyContainer")
        body_container.setMaximumWidth(theme.LEGAL_TEXT_MAX_WIDTH)
        body_layout = QVBoxLayout(body_container)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(theme.SPACING_UNIT)
        # The title and its document share one reading column so the measure
        # stays aligned from the first line to the last.
        body_layout.addWidget(self.page_title)
        body_layout.addWidget(caption)
        body_layout.addWidget(rule)
        body_layout.addWidget(self.body_text)
        body_layout.addStretch(1)

        scroll_body = QWidget()
        scroll_body.setObjectName("legalScrollBody")
        scroll_row = QHBoxLayout(scroll_body)
        scroll_row.setContentsMargins(0, 0, 0, 0)
        scroll_row.setSpacing(0)
        scroll_row.addStretch(1)
        scroll_row.addWidget(body_container, 6)
        scroll_row.addStretch(1)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("legalScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
        )
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.scroll_area.setAccessibleName(f"{title} content")
        self.scroll_area.setWidget(scroll_body)

        self.attribution_label = QLabel(attribution, self)
        self.attribution_label.setObjectName("attributionLabel")
        self.attribution_label.setWordWrap(True)
        self.attribution_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        layout.addWidget(self.back_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.scroll_area, 1)
        layout.addWidget(self.attribution_label)

        # Escape mirrors the Back action, but only while this page is shown.
        self._back_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._back_shortcut.setEnabled(False)
        self._back_shortcut.activated.connect(self._go_back)

    # -- lifecycle --------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: D401 - Qt override
        super().showEvent(event)
        self._back_shortcut.setEnabled(True)
        self.back_button.setFocus()

    def hideEvent(self, event) -> None:  # noqa: D401 - Qt override
        super().hideEvent(event)
        self._back_shortcut.setEnabled(False)

    # -- actions ----------------------------------------------------------

    def _go_back(self) -> None:
        self._back_shortcut.setEnabled(False)
        self._on_back()
