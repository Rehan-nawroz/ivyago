"""Themed empty states for destinations that are not built yet."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from . import icons, theme
from .backdrop import BackdropFrame


class PlaceholderView(BackdropFrame):
    """A calm page with a title and an honest phase status message."""

    def __init__(
        self,
        title: str,
        message: str,
        icon_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.page_title = title

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.CONTENT_PADDING,
            theme.CONTENT_PADDING,
            theme.CONTENT_PADDING,
            theme.CONTENT_PADDING,
        )
        layout.setSpacing(theme.SPACING_UNIT * 2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        badge = QLabel(self)
        badge.setObjectName("emptyStateIcon")
        badge.setFixedSize(60, 60)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(icons.pixmap(icon_name, theme.BRAND_RED, 26))

        title_label = QLabel(title, self)
        title_label.setObjectName("pageTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setAccessibleName(f"{title} page title")

        message_label = QLabel(message, self)
        message_label.setObjectName("pageMessage")
        message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message_label.setWordWrap(True)
        message_label.setFixedWidth(460)
        message_label.setAccessibleName(f"{title} page status")

        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(message_label, 0, Qt.AlignmentFlag.AlignHCenter)
