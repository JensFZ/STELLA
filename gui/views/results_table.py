from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.detection import DetectionResult
from core.io_fits import stretch_to_uint8

COLUMN_LABELS = ["Vorschau", "Geschwindigkeit", "Winkel", "Position", "SNR", "Status"]
STATUS_OPTIONS = ["Offen", "Bestätigt", "Verworfen"]
STATUS_TO_CONFIRMED = {0: None, 1: True, 2: False}
THUMBNAIL_DISPLAY_SIZE = 64


def _thumbnail_pixmap(image: np.ndarray) -> QPixmap:
    stretched = np.ascontiguousarray(stretch_to_uint8(image))
    height, width = stretched.shape
    qimage = QImage(
        stretched.data, width, height, width, QImage.Format.Format_Grayscale8
    ).copy()
    return QPixmap.fromImage(qimage).scaled(
        THUMBNAIL_DISPLAY_SIZE, THUMBNAIL_DISPLAY_SIZE, Qt.AspectRatioMode.KeepAspectRatio
    )


class ResultsTable(QWidget):
    """Kandidatenliste mit Vorschaubild pro Treffer und manueller Bestätigung/Verwerfung
    durch den Nutzer (false positives sind bei Synthetic Tracking normal)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._detections: list[DetectionResult] = []

        self.summary_label = QLabel("Keine Kandidaten.", self)

        self.table = QTableWidget(0, len(COLUMN_LABELS), self)
        self.table.setHorizontalHeaderLabels(COLUMN_LABELS)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)

    def set_detections(self, detections: list[DetectionResult]) -> None:
        self._detections = detections
        self.table.setRowCount(len(detections))

        for row, detection in enumerate(detections):
            thumbnail_label = QLabel(self)
            thumbnail_label.setPixmap(_thumbnail_pixmap(detection.thumbnail))
            self.table.setCellWidget(row, 0, thumbnail_label)

            speed_item = QTableWidgetItem(f"{detection.vector.speed_arcsec_per_min:.2f}")
            angle_item = QTableWidgetItem(f"{detection.vector.angle_deg:.1f}°")
            position_item = QTableWidgetItem(f"({detection.position[0]}, {detection.position[1]})")
            snr_item = QTableWidgetItem(f"{detection.snr:.1f}")
            for item in (speed_item, angle_item, position_item, snr_item):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, speed_item)
            self.table.setItem(row, 2, angle_item)
            self.table.setItem(row, 3, position_item)
            self.table.setItem(row, 4, snr_item)

            status_combo = QComboBox(self)
            status_combo.addItems(STATUS_OPTIONS)
            status_combo.currentIndexChanged.connect(
                lambda index, d=detection: self._on_status_changed(d, index)
            )
            self.table.setCellWidget(row, 5, status_combo)

        self.table.resizeRowsToContents()
        self.summary_label.setText(f"{len(detections)} Kandidat(en) gefunden.")

    def _on_status_changed(self, detection: DetectionResult, index: int) -> None:
        detection.confirmed = STATUS_TO_CONFIRMED[index]

    def detections(self) -> list[DetectionResult]:
        return list(self._detections)
