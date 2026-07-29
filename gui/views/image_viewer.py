from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGraphicsEllipseItem,
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

from core.alignment import RegisteredStack
from core.io_fits import FrameStack, make_thumbnail, stretch_to_uint8

STAR_MARKER_RADIUS = 6
STAR_MARKER_COLOR = Qt.GlobalColor.red

THUMBNAIL_SIZE = 96
BLINK_INTERVAL_MS = 400


def _to_qimage(gray: np.ndarray) -> QImage:
    gray = np.ascontiguousarray(gray)
    h, w = gray.shape
    image = QImage(gray.data, w, h, w, QImage.Format.Format_Grayscale8)
    return image.copy()  # entkoppelt vom NumPy-Puffer


class ZoomableGraphicsView(QGraphicsView):
    """Bildansicht mit Mausrad-Zoom, die das Bild von sich aus einpasst.

    Das Einpassen darf nicht nur einmal beim ersten Bild geschehen: zu diesem Zeitpunkt
    kann das Ansichtsfenster noch seine endgültige Größe suchen (etwa weil das Widget als
    verdeckte Seite eines QStackedWidget liegt), und das Fenster lässt sich später
    vergrößern. Deshalb wird bei jeder Größenänderung neu eingepasst — solange der Nutzer
    nicht selbst gezoomt hat; dann behält seine Einstellung Vorrang.
    """

    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._auto_fit = True

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)
        self._auto_fit = False  # ab jetzt bestimmt der Nutzer den Maßstab

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt-Namenskonvention)
        super().resizeEvent(event)
        if self._auto_fit:
            self.fit_to_content()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt-Namenskonvention)
        # Beim Einblenden steht die endgültige Größe erst fest, nachdem das Layout
        # durchgelaufen ist — daher verzögert einpassen.
        super().showEvent(event)
        if self._auto_fit:
            # Mit Kontextobjekt: wird die Ansicht vor dem Auslösen zerstört, verwirft Qt
            # den Aufruf. Ohne das liefe er auf ein bereits gelöschtes Objekt und stürzte ab
            # — etwa wenn direkt nach dem Laden geschlossen wird.
            QTimer.singleShot(0, self, self.fit_to_content)

    def fit_to_content(self) -> None:
        """Passt den sichtbaren Inhalt vollständig ins Ansichtsfenster ein."""
        bounds = self.scene().itemsBoundingRect()
        if bounds.isEmpty():
            return
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def reset_fit(self) -> None:
        """Schaltet das automatische Einpassen wieder ein und passt sofort ein."""
        self._auto_fit = True
        self.fit_to_content()


class ImageViewer(QWidget):
    frame_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._stack: FrameStack | None = None
        self._registered: RegisteredStack | None = None
        self._index = 0
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._blink_tick)
        self._blink_partner = 0
        self._blink_showing_partner = False

        self.scene = QGraphicsScene(self)
        self.view = ZoomableGraphicsView(self.scene, self)
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._star_items: list[QGraphicsEllipseItem] = []

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

        self.frame_label = QLabel(self.tr("Keine Frames geladen"), self)

        self.low_pct_spin = QDoubleSpinBox(self)
        self.low_pct_spin.setRange(0.0, 49.0)
        self.low_pct_spin.setValue(1.0)
        self.low_pct_spin.setSuffix(" %")
        self.low_pct_spin.setPrefix(self.tr("Schwarzpunkt "))
        self.low_pct_spin.valueChanged.connect(self._update_display)

        self.high_pct_spin = QDoubleSpinBox(self)
        self.high_pct_spin.setRange(51.0, 100.0)
        self.high_pct_spin.setValue(99.5)
        self.high_pct_spin.setSuffix(" %")
        self.high_pct_spin.setPrefix(self.tr("Weißpunkt "))
        self.high_pct_spin.valueChanged.connect(self._update_display)

        self.blink_button = QPushButton(self.tr("Blink"), self)
        self.blink_button.setCheckable(True)
        self.blink_button.toggled.connect(self._toggle_blink)

        self.star_overlay_button = QPushButton(self.tr("Sterne anzeigen"), self)
        self.star_overlay_button.setCheckable(True)
        self.star_overlay_button.setEnabled(False)
        self.star_overlay_button.toggled.connect(self._update_display)

        # Ohne diesen Knopf gäbe es nach dem Zoomen keinen Weg zurück zur Gesamtansicht.
        self.fit_button = QPushButton(self.tr("Einpassen"), self)
        self.fit_button.clicked.connect(self.view.reset_fit)

        controls = QHBoxLayout()
        controls.addWidget(self.low_pct_spin)
        controls.addWidget(self.high_pct_spin)
        controls.addWidget(self.blink_button)
        controls.addWidget(self.star_overlay_button)
        controls.addWidget(self.fit_button)
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
        self._registered = None
        self._index = 0
        self.blink_button.setChecked(False)
        self.star_overlay_button.setChecked(False)
        self.star_overlay_button.setEnabled(False)

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
            # Ein neuer Stapel kann eine andere Bildgröße haben; zudem ist das Widget beim
            # Laden womöglich noch nicht sichtbar. Verzögert einpassen, damit das Layout
            # zuvor die endgültige Größe festlegt.
            self.view.reset_fit()
            QTimer.singleShot(0, self.view, self.view.reset_fit)
        else:
            self.frame_label.setText(self.tr("Keine Frames gefunden"))

    def set_registered_stack(self, registered: RegisteredStack) -> None:
        self._registered = registered
        self.star_overlay_button.setEnabled(True)
        self.star_overlay_button.setChecked(True)
        self._update_display()

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
        else:
            self._pixmap_item.setPixmap(pixmap)
        self.scene.setSceneRect(self._pixmap_item.boundingRect())

        self._update_star_overlay(index)

        label = f"{index + 1} / {len(self._stack)} — {frame.path.name}"
        if self._registered is not None:
            registered_frame = self._registered[index]
            alignment = registered_frame.alignment
            label += (
                f" — Δx={alignment.dx:+.1f}px Δy={alignment.dy:+.1f}px"
                f" ({alignment.n_matches} Sterne gematcht)"
            )
        self.frame_label.setText(label)

    def _update_star_overlay(self, index: int) -> None:
        for item in self._star_items:
            self.scene.removeItem(item)
        self._star_items.clear()

        if self._registered is None or not self.star_overlay_button.isChecked():
            return

        pen = QPen(STAR_MARKER_COLOR)
        pen.setWidth(0)
        stars = self._registered[index].stars
        for star_x, star_y in zip(stars.x, stars.y, strict=True):
            item = self.scene.addEllipse(
                star_x - STAR_MARKER_RADIUS,
                star_y - STAR_MARKER_RADIUS,
                2 * STAR_MARKER_RADIUS,
                2 * STAR_MARKER_RADIUS,
                pen,
            )
            self._star_items.append(item)

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
