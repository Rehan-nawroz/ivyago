"""Windows-native behavior for the frameless main window.

Frameless shells lose the system resize border. The filter below answers
``WM_NCHITTEST`` for the outer few pixels of the window so Windows itself
performs the resize (including the resize cursor and edge snapping) instead of
re-implementing drag math in Qt.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QPoint
from PySide6.QtWidgets import QMainWindow

from .window_chrome import hit_test_code, resize_edges_at

_WM_NCHITTEST = 0x0084
_WINDOWS_NATIVE_EVENTS = (b"windows_generic_MSG", b"windows_dispatcher_MSG")


class FramelessResizeFilter(QAbstractNativeEventFilter):
    """Route clicks near the window border to the native resize handler."""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__()
        self._window = window
        self._hwnd = 0

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt API
        if event_type not in _WINDOWS_NATIVE_EVENTS:
            return False, 0

        try:
            native = ctypes.wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError, OSError):
            return False, 0

        if native.message != _WM_NCHITTEST:
            return False, 0

        window = self._window
        if (
            window is None
            or not window.isVisible()
            or window.isMaximized()
            or window.isFullScreen()
        ):
            return False, 0

        if self._hwnd == 0:
            self._hwnd = int(window.winId())
        if int(native.hWnd) != self._hwnd:
            return False, 0

        scale = window.devicePixelRatioF() or 1.0
        screen_x = ctypes.c_short(native.lParam & 0xFFFF).value
        screen_y = ctypes.c_short((native.lParam >> 16) & 0xFFFF).value
        origin = window.geometry().topLeft()
        local = QPoint(
            int(round(screen_x / scale)) - origin.x(),
            int(round(screen_y / scale)) - origin.y(),
        )

        code = hit_test_code(resize_edges_at(local, window.size()))
        if code is None:
            return False, 0
        return True, code
