"""Line-icon set for the Ivyago desktop shell.

The approved interface uses one consistent family of stroked icons. They are
defined once here as SVG path data, rendered with Qt's SVG renderer, and tinted
per state so navigation, window controls, and the composer share a single
visual language without shipping extra image files.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_STROKED = {
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "history": (
        '<circle cx="12" cy="12" r="10"/>'
        '<polyline points="12 6 12 12 16 14"/>'
    ),
    "settings": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0'
        'l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2'
        'v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1'
        ' 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1'
        ' 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0'
        ' 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1'
        ' 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0'
        ' 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0'
        ' 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>'
    ),
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "heart_pulse": (
        '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78'
        'l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>'
        '<polyline points="7 12 10 12 12 9 14 15 16 12 18 12"/>'
    ),
    "paperclip": (
        '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66'
        'l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>'
    ),
    "minimize": '<line x1="4" x2="20" y1="12" y2="12"/>',
    "maximize": (
        '<rect height="16" rx="2" ry="2" width="16" x="4" y="4"/>'
    ),
    "restore": (
        '<rect height="12" rx="2" ry="2" width="12" x="9" y="9"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
    ),
    "close": (
        '<line x1="18" x2="6" y1="6" y2="18"/>'
        '<line x1="6" x2="18" y1="6" y2="18"/>'
    ),
    # Phase 4: session rail and message actions.
    "plus": (
        '<line x1="12" x2="12" y1="5" y2="19"/>'
        '<line x1="5" x2="19" y1="12" y2="12"/>'
    ),
    "panel": (
        '<rect height="16" rx="2" ry="2" width="18" x="3" y="4"/>'
        '<line x1="9" x2="9" y1="4" y2="20"/>'
    ),
    "copy": (
        '<rect height="13" rx="2" ry="2" width="13" x="9" y="9"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
    ),
    "edit": (
        '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>'
        '<path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4z"/>'
    ),
    "retry": (
        '<path d="M21 12a9 9 0 1 1-2.64-6.36"/>'
        '<polyline points="21 3 21 9 15 9"/>'
    ),
    # Phase 5 polish: document, repository, and back affordances.
    "arrow_left": (
        '<line x1="19" x2="5" y1="12" y2="12"/>'
        '<polyline points="12 19 5 12 12 5"/>'
    ),
    "document": (
        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
        '<polyline points="14 2 14 8 20 8"/>'
        '<line x1="16" x2="8" y1="13" y2="13"/>'
        '<line x1="16" x2="8" y1="17" y2="17"/>'
    ),
    "trash": (
        '<polyline points="3 6 5 6 21 6"/>'
        '<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>'
        '<path d="M10 11v6M14 11v6"/>'
        '<path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>'
    ),
    "external_link": (
        '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
        '<polyline points="15 3 21 3 21 9"/>'
        '<line x1="10" x2="21" y1="14" y2="3"/>'
    ),
}

_FILLED = {
    "send": '<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>',
    "stop": '<rect height="11" rx="2" ry="2" width="11" x="6.5" y="6.5"/>',
}

ICON_NAMES = frozenset(_STROKED) | frozenset(_FILLED)

_PIXMAP_CACHE: dict[tuple[str, str, int, int], QPixmap] = {}


def _svg_source(name: str, tint: str, stroke_width: float) -> str:
    if name in _FILLED:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'fill="{tint}" stroke="none">{_FILLED[name]}</svg>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{tint}" stroke-width="{stroke_width}" '
        'stroke-linecap="round" stroke-linejoin="round">'
        f"{_STROKED[name]}</svg>"
    )


def _render_scale() -> int:
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 2
    return max(2, int(round(screen.devicePixelRatio())))


def pixmap(name: str, tint: str, size: int, stroke_width: float = 2.0) -> QPixmap:
    """Return a cached, high-DPI pixmap for a named icon tinted with ``tint``."""

    if name not in ICON_NAMES:
        raise KeyError(f"Unknown icon: {name!r}")

    dpr = _render_scale()
    key = (name, tint, size, dpr)
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached

    canvas = QPixmap(int(math.ceil(size * dpr)), int(math.ceil(size * dpr)))
    canvas.setDevicePixelRatio(dpr)
    canvas.fill(Qt.GlobalColor.transparent)

    renderer = QSvgRenderer(QByteArray(_svg_source(name, tint, stroke_width).encode("utf-8")))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()

    _PIXMAP_CACHE[key] = canvas
    return canvas


def icon_size(size: int) -> QSize:
    """Return the square icon size a button should request."""

    return QSize(size, size)


def icon(
    name: str,
    tint: str,
    size: int,
    *,
    active_tint: str | None = None,
    disabled_tint: str | None = None,
) -> QIcon:
    """Return a QIcon whose hover state uses ``active_tint`` when provided."""

    result = QIcon()
    result.addPixmap(pixmap(name, tint, size), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(pixmap(name, tint, size), QIcon.Mode.Selected, QIcon.State.Off)
    if active_tint:
        result.addPixmap(
            pixmap(name, active_tint, size), QIcon.Mode.Active, QIcon.State.Off
        )
    if disabled_tint:
        result.addPixmap(
            pixmap(name, disabled_tint, size), QIcon.Mode.Disabled, QIcon.State.Off
        )
    return result
