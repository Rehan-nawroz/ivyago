"""Ambient page backdrop: the red ECG glow seen in the approved design.

The artwork is intentionally painted rather than shipped as a bitmap so it
stays crisp at any window size and never dominates the text above it.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QFrame, QWidget

from . import assets

# Coordinates below come from the reference SVG (a 600x300 ECG strip and a
# 400x200 ambient arc), remapped into the live page rectangle.
_ECG_POINTS = (
    (0, 220),
    (220, 220),
    (235, 240),
    (255, 175),
    (275, 260),
    (295, 190),
    (310, 220),
    (360, 220),
    (375, 235),
    (390, 195),
    (405, 240),
    (420, 220),
    (600, 220),
)

_ECG_WIDTH = 560
_ECG_VIEWBOX = (600.0, 300.0)
_ECG_BASELINE_OFFSET = 84.0
_ECG_ALPHA = 110
_WATERMARK_HEIGHT = 320
_WATERMARK_ALPHA = 0.10


def paint_backdrop(painter: QPainter, rect: QRectF) -> None:
    """Paint the ambient glow, ECG trace, and watermark inside ``rect``."""

    if rect.width() <= 0 or rect.height() <= 0:
        return

    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setClipRect(rect)

    _paint_vignette(painter, rect)
    _paint_watermark(painter, rect)
    _paint_ecg(painter, rect)
    _paint_ambient_arc(painter, rect)

    painter.restore()


def _paint_vignette(painter: QPainter, rect: QRectF) -> None:
    center = QPointF(rect.right() - 120.0, rect.bottom() - 40.0)
    gradient = QRadialGradient(center, max(rect.width(), rect.height()) * 0.62)
    gradient.setColorAt(0.0, QColor(255, 17, 36, 30))
    gradient.setColorAt(0.45, QColor(255, 17, 36, 10))
    gradient.setColorAt(1.0, QColor(255, 17, 36, 0))
    painter.fillRect(rect, gradient)


def _paint_watermark(painter: QPainter, rect: QRectF) -> None:
    try:
        mark = assets.brand_mark(_WATERMARK_HEIGHT)
    except (FileNotFoundError, OSError):
        return

    width = mark.width() / max(mark.devicePixelRatio(), 1.0)
    target = QRectF(
        rect.right() - width * 0.55,
        rect.bottom() - _WATERMARK_HEIGHT * 0.72,
        width,
        _WATERMARK_HEIGHT,
    )
    painter.save()
    painter.setOpacity(_WATERMARK_ALPHA)
    painter.drawPixmap(target, mark, QRectF(mark.rect()))
    painter.restore()


def _paint_ecg(painter: QPainter, rect: QRectF) -> None:
    width = min(_ECG_WIDTH, rect.width() * 0.6)
    if width < 120:
        return
    height = width * _ECG_VIEWBOX[1] / _ECG_VIEWBOX[0]
    baseline = _ECG_POINTS[0][1] / _ECG_VIEWBOX[1]
    top = rect.bottom() - _ECG_BASELINE_OFFSET - baseline * height
    left = rect.right() - width

    path = QPainterPath()
    for index, (x, y) in enumerate(_ECG_POINTS):
        point = QPointF(
            left + x / _ECG_VIEWBOX[0] * width,
            top + y / _ECG_VIEWBOX[1] * height,
        )
        if index == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)

    pen = QPen(QColor(255, 17, 36, _ECG_ALPHA))
    pen.setWidthF(2.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)


def _paint_ambient_arc(painter: QPainter, rect: QRectF) -> None:
    box_width = min(400.0, rect.width() * 0.45)
    box_height = box_width * 0.5
    left = rect.left() - box_width * 0.12
    top = rect.bottom() - box_height * 0.9

    path = QPainterPath()
    path.moveTo(left - 50.0 / 400.0 * box_width, top + 180.0 / 200.0 * box_height)
    path.cubicTo(
        left + 100.0 / 400.0 * box_width,
        top + 180.0 / 200.0 * box_height,
        left + 150.0 / 400.0 * box_width,
        top + 120.0 / 200.0 * box_height,
        left + 300.0 / 400.0 * box_width,
        top + 200.0 / 200.0 * box_height,
    )

    for width, alpha in ((34.0, 6), (20.0, 9), (8.0, 13)):
        pen = QPen(QColor(255, 17, 36, alpha))
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class BackdropFrame(QFrame):
    """Page surface that paints the ambient artwork behind its children."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageSurface")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:  # noqa: D401 - Qt override
        super().paintEvent(event)
        painter = QPainter(self)
        paint_backdrop(painter, QRectF(self.rect()))
        painter.end()
