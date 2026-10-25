"""Short, non-blocking transitions for the Ivyago desktop shell.

Motion answers a user action: switching destinations, opening or closing a
document, confirming a dialog. It never gates a logical state change - a
stacked widget's current page and every model value update synchronously, and
the fade that follows is purely cosmetic.

Agents or tests that need deterministic state can call ``finish`` on a
transition, and the operating system's own animation preference is honoured:
when Qt reports system animation as disabled (or ``IVYAGO_REDUCED_MOTION`` is
set), no effect is installed at all.
"""

from __future__ import annotations

import os
import weakref

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGraphicsEffect,
    QGraphicsOpacityEffect,
    QStackedWidget,
    QWidget,
)
from PySide6.QtCore import Qt

from . import theme

REDUCED_MOTION_ENV = "IVYAGO_REDUCED_MOTION"

_TRANSITIONS: weakref.WeakKeyDictionary[QWidget, "FadeTransition"] = (
    weakref.WeakKeyDictionary()
)


def reduced_motion_enabled() -> bool:
    """Return whether animations should be skipped entirely.

    ``IVYAGO_REDUCED_MOTION`` always wins so a user (or a deterministic test)
    can force the calm path. Otherwise Qt's system animation flag is used; on
    platforms that do not expose one, motion stays enabled because the
    durations used here are short and nonessential.
    """

    flag = os.environ.get(REDUCED_MOTION_ENV, "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    app = QApplication.instance()
    if app is None:  # pragma: no cover - only during interpreter shutdown
        return False
    try:
        return not app.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo)
    except (AttributeError, RuntimeError):  # pragma: no cover - Qt detail
        return False


def transition_duration() -> int:
    """Return the page/dialog fade duration, or ``0`` when motion is off."""

    return 0 if reduced_motion_enabled() else theme.MOTION_BASE_MS


class FadeTransition(QObject):
    """Fade one widget from transparent to opaque without delaying state."""

    finished = Signal()

    def __init__(
        self,
        widget: QWidget,
        duration_ms: int | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or widget)
        self._widget_ref = weakref.ref(widget)
        self._duration = (
            theme.MOTION_BASE_MS if duration_ms is None else max(0, int(duration_ms))
        )
        self._done = False

        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0.0)
        widget.setGraphicsEffect(effect)
        self._effect = effect

        self._animation = QPropertyAnimation(effect, b"opacity", self)
        self._animation.setDuration(self._duration)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve(theme.MOTION_EASING))
        self._animation.finished.connect(self._on_animation_finished)

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._done:
            return
        self._animation.start()

    def is_running(self) -> bool:
        return not self._done

    def duration(self) -> int:
        return self._duration

    def finish(self) -> None:
        """Jump to the finished state immediately (idempotent)."""

        self._complete()

    def _on_animation_finished(self) -> None:
        self._complete()

    def _complete(self) -> None:
        if self._done:
            return
        self._done = True
        self._animation.stop()

        widget = self._widget_ref()
        if widget is not None:
            try:
                # Setting no effect deletes the opacity effect Qt owns; the
                # widget itself is left exactly as it was before the fade.
                widget.setGraphicsEffect(None)
            except RuntimeError:  # pragma: no cover - widget already deleted
                pass
            _TRANSITIONS.pop(widget, None)
        self._effect = None
        self.finished.emit()


def transition_for(widget: QWidget) -> FadeTransition | None:
    """Return the live transition installed on ``widget``, if any."""

    transition = _TRANSITIONS.get(widget)
    if transition is not None and transition.is_running():
        return transition
    return None


def finish_transition(widget: QWidget) -> None:
    """Immediately settle any transition on ``widget``."""

    transition = _TRANSITIONS.get(widget)
    if transition is not None:
        transition.finish()


def _has_foreign_effect(widget: QWidget) -> bool:
    """True when another graphics effect (a shadow, blur, ...) is installed."""

    effect: QGraphicsEffect | None = widget.graphicsEffect()
    return effect is not None and not isinstance(effect, QGraphicsOpacityEffect)


def fade_in(
    widget: QWidget | None,
    *,
    duration_ms: int | None = None,
) -> FadeTransition | None:
    """Fade ``widget`` in, returning the transition (``None`` when skipped)."""

    if widget is None:
        return None

    existing = _TRANSITIONS.get(widget)
    if existing is not None:
        existing.finish()

    duration = (
        theme.MOTION_BASE_MS if duration_ms is None else max(0, int(duration_ms))
    )
    if duration <= 0 or reduced_motion_enabled() or _has_foreign_effect(widget):
        return None

    transition = FadeTransition(widget, duration)
    _TRANSITIONS[widget] = transition
    transition.start()
    return transition


def show_page(
    stack: QStackedWidget,
    widget: QWidget,
    *,
    duration_ms: int | None = None,
) -> FadeTransition | None:
    """Select a stacked page immediately, then fade it in.

    The current page always changes before the animation starts, so navigation
    stays correct even if the transition is interrupted or never runs.
    """

    previous = stack.currentWidget()
    stack.setCurrentWidget(widget)
    if previous is widget:
        return _TRANSITIONS.get(widget)
    if not stack.isVisible():
        return None
    return fade_in(widget, duration_ms=duration_ms)


def fade_dialog(dialog: QDialog) -> QPropertyAnimation | None:
    """Fade a confirmation dialog in, with a guaranteed visible end state."""

    if reduced_motion_enabled():
        dialog.setWindowOpacity(1.0)
        return None

    try:
        dialog.setWindowOpacity(0.0)
    except RuntimeError:  # pragma: no cover - Qt detail
        return None

    animation = QPropertyAnimation(dialog, b"windowOpacity", dialog)
    animation.setDuration(theme.MOTION_FAST_MS)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve(theme.MOTION_EASING))
    animation.finished.connect(lambda: _ensure_opaque(dialog))
    animation.start()
    # Failsafe: a stalled animation must never leave a dialog invisible.
    QTimer.singleShot(theme.MOTION_FAST_MS + 200, lambda: _ensure_opaque(dialog))
    return animation


def _ensure_opaque(dialog: QDialog) -> None:
    try:
        if dialog.windowOpacity() < 1.0:
            dialog.setWindowOpacity(1.0)
    except RuntimeError:  # pragma: no cover - dialog already destroyed
        pass
