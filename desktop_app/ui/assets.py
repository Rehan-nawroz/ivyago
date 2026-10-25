"""Brand asset loading with a small high-DPI pixmap cache.

Asset lookup stays behind :mod:`desktop_app.paths` so the fallback behavior for
missing decorative resources is identical everywhere, and nothing here touches
the filesystem at import time.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap

from .. import paths

_CACHE: dict[tuple[str, int], QPixmap] = {}


def _render_scale() -> int:
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 2
    return max(2, int(round(screen.devicePixelRatio())))


def _scaled_resource(name: str, height: int) -> QPixmap:
    scale = _render_scale()
    key = (name, height)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    source = QPixmap(str(paths.desktop_resource_path(name)))
    if source.isNull():
        raise FileNotFoundError(f"Unreadable desktop resource: {name}")

    scaled = source.scaledToHeight(
        height * scale,
        Qt.TransformationMode.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(scale)
    _CACHE[key] = scaled
    return scaled


def brand_mark(height: int = 52) -> QPixmap:
    """Return the nurse mark (``logo.png``) scaled to ``height`` logical pixels."""

    return _scaled_resource("logo.png", height)


def brand_wordmark(height: int) -> QPixmap:
    """Return the Ivyago wordmark (``ivyago-line.png``) at ``height``."""

    return _scaled_resource("ivyago-line.png", height)


def clear_cache() -> None:
    """Drop cached pixmaps (used by fallback tests)."""

    _CACHE.clear()
