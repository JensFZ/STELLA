from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.io_fits import FrameStack, make_thumbnail, stretch_to_uint8

THUMBNAIL_SIZE = 96
BLINK_INTERVAL_MS = 400


def _to_qimage(gray: np.ndarray) -> QImage:
    gray = np.ascontiguousarray(gray)
    h, w = gray.shape
    image = QImage(gray.data, w, h, w, QImage.Format.Format_Grayscale8)
    return image.copy()  # entkoppelt vom NumPy-Puffer


class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)


class ImageViewer(QWidget):
    frame_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._stack: FrameStack | None = None
        self._index = 0
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._blink_tick)
        self._blink_partner = 0
        self._blink_showing_partner = False

        self.scene = QGraphicsScene(self)
        self.view = ZoomableGraphicsView(self.scene, self)
        self._pixmap_item: QGraphicsPixmapItem | None = None

        self.thumbnail_list = QListWidget(self)
        self.thumbnail_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnail_list.setFlow(QListWidget.Flow.LeftToRight)
        self.thumbnail_list.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.thumbnail_list.setFixedHeight(THUMBNAIL_SIZE + 32)
        self.thumbnail_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnail_list.setWrapping(False)
        self.thumbnail_list.currentRowChanged.connect(self.set_frame_index)

        self.frame_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(0)
        self.frame_slider.valueChanged.connect(self.set_frame_index)

        self.frame_label = QLabel("Keine Frames geladen", self)

        self.low_pct_spin = QDoubleSpinBox(self)
        self.low_pct_spin.setRange(0.0, 49.0)
        self.low_pct_spin.setValue(1.0)
        self.low_pct_spin.setSuffix(" %")
        self.low_pct_spin.setPrefix("Schwarzpunkt ")
        self.low_pct_spin.valueChanged.connect(self._update_display)

        self.high_pct_spin = QDoubleSpinBox(self)
        self.high_pct_spin.setRange(51.0, 100.0)
        self.high_pct_spin.setValue(99.5)
        self.high_pct_spin.setSuffix(" %")
        self.high_pct_spin.setPrefix("Weißpunkt ")
        self.high_pct_spin.valueChanged.connect(self._update_display)

        self.blink_button = QPushButton("Blink", self)
        self.blink_button.setCheckable(True)
        self.blink_button.toggled.connect(self._toggle_blink)

        controls = QHBoxLayout()
        controls.addWidget(self.low_pct_spin)
        controls.addWidget(self.high_pct_spin)
        controls.addWidget(self.blink_button)
        controls.addStretch(1)

        nav = QHBoxLayout()
        nav.addWidget(self.frame_slider, stretch=1)
        nav.addWidget(self.frame_label)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.view, stretch=1)
        layout.addLayout(nav)
        layout.addWidget(self.thumbnail_list)

        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.frame_slider,
            self.low_pct_spin,
            self.high_pct_spin,
            self.blink_button,
            self.thumbnail_list,
        ):
            widget.setEnabled(enabled)

    def set_stack(self, stack: FrameStack) -> None:
        self._stack = stack
        self._index = 0
        self.blink_button.setChecked(False)

        self.thumbnail_list.blockSignals(True)
        self.thumbnail_list.clear()
        for frame in stack.frames:
            thumb = make_thumbnail(frame.data, size=THUMBNAIL_SIZE)
            pixmap = QPixmap.fromImage(_to_qimage(thumb)).scaled(
                THUMBNAIL_SIZE, THUMBNAIL_SIZE, Qt.AspectRatioMode.KeepAspectRatio
            )
            self.thumbnail_list.addItem(QListWidgetItem(QIcon(pixmap), frame.path.name))
        self.thumbnail_list.blockSignals(False)

        has_frames = len(stack) > 0
        self._set_controls_enabled(has_frames)
        self.frame_slider.blockSignals(True)
        self.frame_slider.setMaximum(max(0, len(stack) - 1))
        self.frame_slider.setValue(0)
        self.frame_slider.blockSignals(False)

        if has_frames:
            self.thumbnail_list.setCurrentRow(0)
            self._update_display()
        else:
            self.frame_label.setText("Keine Frames gefunden")

    def set_frame_index(self, index: int) -> None:
        if self._stack is None or not (0 <= index < len(self._stack)):
            return
        self._index = index
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(index)
        self.frame_slider.blockSignals(False)
        self.thumbnail_list.blockSignals(True)
        self.thumbnail_list.setCurrentRow(index)
        self.thumbnail_list.blockSignals(False)
        self._update_display()
        self.frame_changed.emit(index)

    def _update_display(self) -> None:
        self._render_frame(self._index)

    def _render_frame(self, index: int) -> None:
        if self._stack is None or len(self._stack) == 0:
            return
        frame = self._stack[index]
        stretched = stretch_to_uint8(
            frame.data, low_pct=self.low_pct_spin.value(), high_pct=self.high_pct_spin.value()
        )
        pixmap = QPixmap.fromImage(_to_qimage(stretched))

        if self._pixmap_item is None:
            self._pixmap_item = self.scene.addPixmap(pixmap)
            self.view.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            self._pixmap_item.setPixmap(pixmap)
        self.scene.setSceneRect(self._pixmap_item.boundingRect())

        self.frame_label.setText(f"{index + 1} / {len(self._stack)} — {frame.path.name}")

    def _toggle_blink(self, checked: bool) -> None:
        if self._stack is None or len(self._stack) < 2:
            self.blink_button.setChecked(False)
            return
        if checked:
            self._blink_partner = (self._index + 1) % len(self._stack)
            self._blink_showing_partner = False
            self._blink_timer.start(BLINK_INTERVAL_MS)
        else:
            self._blink_timer.stop()
            self._render_frame(self._index)

    def _blink_tick(self) -> None:
        self._blink_showing_partner = not self._blink_showing_partner
        index = self._blink_partner if self._blink_showing_partner else self._index
        self._render_frame(index)
