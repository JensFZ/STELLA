from __future__ import annotations

import numpy as np
from PySide6.QtCore import QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHeaderView,
    QLabel,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.detection import DetectionResult
from core.io_fits import stretch_to_uint8

COLUMN_LABELS = ["Vorschau", "Geschwindigkeit", "Winkel", "Position", "SNR", "Status"]
STATUS_COLUMN = 5
STATUS_OPTIONS = ["Offen", "Bestätigt", "Verworfen"]
STATUS_TO_CONFIRMED = {0: None, 1: True, 2: False}
CONFIRMED_TO_STATUS = {None: 0, True: 1, False: 2}
THUMBNAIL_DISPLAY_SIZE = 64

#: Rolle, unter der die zugehörige DetectionResult am Item hängt. Muss am Item selbst
#: hängen (nicht an der Zeilennummer), damit die Zuordnung das Sortieren übersteht.
DETECTION_ROLE = int(Qt.ItemDataRole.UserRole) + 1
#: Rolle für den numerischen Sortierschlüssel (siehe NumericTableWidgetItem).
SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 2


def _thumbnail_pixmap(image: np.ndarray) -> QPixmap:
    stretched = np.ascontiguousarray(stretch_to_uint8(image))
    height, width = stretched.shape
    qimage = QImage(stretched.data, width, height, width, QImage.Format.Format_Grayscale8).copy()
    return QPixmap.fromImage(qimage).scaled(
        THUMBNAIL_DISPLAY_SIZE, THUMBNAIL_DISPLAY_SIZE, Qt.AspectRatioMode.KeepAspectRatio
    )


class NumericTableWidgetItem(QTableWidgetItem):
    """Tabellen-Item, das nach einem hinterlegten Zahlenwert sortiert statt nach dem
    angezeigten Text — sonst würde z.B. "10.0" vor "9.0" einsortiert."""

    def __init__(self, text: str, sort_value: float):
        super().__init__(text)
        self.setData(SORT_ROLE, float(sort_value))
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        own = self.data(SORT_ROLE)
        theirs = other.data(SORT_ROLE)
        if own is None or theirs is None:
            return super().__lt__(other)
        return float(own) < float(theirs)


class StatusDelegate(QStyledItemDelegate):
    """Dropdown zur Bestätigung/Verwerfung. Bewusst als Delegate statt als
    `setCellWidget`-Widget: Zellen-Widgets bleiben beim Sortieren an ihrer alten
    Bildschirmzeile stehen und würden dann zum falschen Kandidaten gehören."""

    def createEditor(
        self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> QWidget:
        editor = QComboBox(parent)
        editor.addItems(STATUS_OPTIONS)
        return editor

    def setEditorData(self, editor: QComboBox, index: QModelIndex) -> None:
        editor.setCurrentIndex(STATUS_OPTIONS.index(index.data(Qt.ItemDataRole.DisplayRole)))

    def setModelData(self, editor: QComboBox, model, index: QModelIndex) -> None:
        model.setData(index, editor.currentText(), Qt.ItemDataRole.DisplayRole)


class ResultsTable(QWidget):
    """Kandidatenliste mit Vorschaubild pro Treffer, sortierbaren Spalten und manueller
    Bestätigung/Verwerfung durch den Nutzer (false positives sind bei Synthetic Tracking
    normal)."""

    #: Wird ausgelöst, wenn sich eine Bewertung ändert — der Export hängt davon ab.
    confirmation_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._detections: list[DetectionResult] = []

        self.summary_label = QLabel("Keine Kandidaten.", self)

        self.table = QTableWidget(0, len(COLUMN_LABELS), self)
        self.table.setHorizontalHeaderLabels(COLUMN_LABELS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setIconSize(QSize(THUMBNAIL_DISPLAY_SIZE, THUMBNAIL_DISPLAY_SIZE))
        self.table.setSortingEnabled(True)
        self.table.setItemDelegateForColumn(STATUS_COLUMN, StatusDelegate(self.table))
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked
        )
        self.table.itemChanged.connect(self._on_item_changed)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)

    def set_detections(self, detections: list[DetectionResult]) -> None:
        self._detections = detections

        # Sortierung während des Befüllens abschalten: sonst sortiert Qt bereits zwischen
        # den einzelnen setItem-Aufrufen um und die Zeilen geraten durcheinander.
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(len(detections))

        for row, detection in enumerate(detections):
            thumbnail_item = NumericTableWidgetItem("", detection.snr)
            thumbnail_item.setIcon(QIcon(_thumbnail_pixmap(detection.thumbnail)))
            self.table.setItem(row, 0, thumbnail_item)

            self.table.setItem(
                row,
                1,
                NumericTableWidgetItem(
                    f"{detection.vector.speed_arcsec_per_min:.2f}",
                    detection.vector.speed_arcsec_per_min,
                ),
            )
            self.table.setItem(
                row,
                2,
                NumericTableWidgetItem(
                    f"{detection.vector.angle_deg:.1f}°", detection.vector.angle_deg
                ),
            )
            self.table.setItem(
                row,
                3,
                NumericTableWidgetItem(
                    f"({detection.position[0]}, {detection.position[1]})", detection.position[0]
                ),
            )
            self.table.setItem(
                row, 4, NumericTableWidgetItem(f"{detection.snr:.1f}", detection.snr)
            )

            status_item = QTableWidgetItem(STATUS_OPTIONS[CONFIRMED_TO_STATUS[detection.confirmed]])
            status_item.setData(DETECTION_ROLE, detection)
            self.table.setItem(row, STATUS_COLUMN, status_item)

        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)
        self.table.sortItems(4, Qt.SortOrder.DescendingOrder)
        self.table.resizeRowsToContents()
        self.summary_label.setText(f"{len(detections)} Kandidat(en) gefunden.")

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != STATUS_COLUMN:
            return
        detection = item.data(DETECTION_ROLE)
        if detection is None:
            return
        detection.confirmed = STATUS_TO_CONFIRMED[STATUS_OPTIONS.index(item.text())]
        self.confirmation_changed.emit()

    def detections(self) -> list[DetectionResult]:
        return list(self._detections)
