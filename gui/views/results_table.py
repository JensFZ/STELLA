from __future__ import annotations

import numpy as np
from PySide6.QtCore import QCoreApplication, QModelIndex, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
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

STATUS_COLUMN = 5
SNR_COLUMN = 4

#: Reihenfolge der Auswahl im Statusfeld. Der *Wert* (nicht der angezeigte Text) ist
#: maßgeblich — siehe CONFIRMED_ROLE.
STATUS_ORDER: list[bool | None] = [None, True, False]

#: Größer als anfangs (64 px): bei 32×32-Ausschnitten war auf 64 px nur Rauschen erkennbar,
#: eine Beurteilung des Kandidaten damit nicht möglich.
THUMBNAIL_DISPLAY_SIZE = 96

#: Farbige Statusanzeige, damit der Fortschritt beim Durchsehen auf einen Blick sichtbar ist.
STATUS_COLORS = {None: "#c8c8c8", True: "#5fbf7f", False: "#c86a6a"}

#: Tastenkürzel für die Bewertung. Das Sichten hunderter Kandidaten ist die Hauptarbeit mit
#: diesem Werkzeug — über die Tastatur geht das um ein Vielfaches schneller als über ein
#: Auswahlfeld mit zwei Klicks je Kandidat.
KEY_TO_CONFIRMED = {
    Qt.Key.Key_J: True,  # Ja
    Qt.Key.Key_Y: True,  # Yes, auf US-Tastatur an gleicher Stelle
    Qt.Key.Key_Plus: True,
    Qt.Key.Key_N: False,  # Nein
    Qt.Key.Key_Minus: False,
    Qt.Key.Key_0: None,  # zurück auf offen
}

#: Rolle, unter der die zugehörige DetectionResult am Item hängt. Muss am Item selbst
#: hängen (nicht an der Zeilennummer), damit die Zuordnung das Sortieren übersteht.
DETECTION_ROLE = int(Qt.ItemDataRole.UserRole) + 1
#: Rolle für den numerischen Sortierschlüssel (siehe NumericTableWidgetItem).
SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 2
#: Rolle für den Bewertungszustand. Bewusst getrennt vom angezeigten Text: dieser ist
#: übersetzt, aus ihm den Zustand zurückzulesen würde in jeder anderen Sprache scheitern.
CONFIRMED_ROLE = int(Qt.ItemDataRole.UserRole) + 3


def column_labels() -> list[str]:
    """Spaltenüberschriften. Als Funktion statt als Konstante, weil eine Konstante beim
    Import ausgewertet würde — also bevor die Übersetzung installiert ist.

    QCoreApplication.translate wird bewusst direkt aufgerufen und nicht über eine eigene
    Hilfsfunktion: lupdate wertet den Quelltext statisch aus und erkennt nur die
    bekannten Aufrufformen. Hinter einem Wrapper versteckte Texte landen gar nicht erst
    in der Übersetzungsdatei.
    """
    translate = QCoreApplication.translate
    return [
        translate("ResultsTable", "Vorschau"),
        translate("ResultsTable", "Geschwindigkeit"),
        translate("ResultsTable", "Winkel"),
        translate("ResultsTable", "Position"),
        translate("ResultsTable", "SNR"),
        translate("ResultsTable", "Status"),
    ]


def status_label(confirmed: bool | None) -> str:
    if confirmed is True:
        return QCoreApplication.translate("ResultsTable", "Bestätigt")
    if confirmed is False:
        return QCoreApplication.translate("ResultsTable", "Verworfen")
    return QCoreApplication.translate("ResultsTable", "Offen")


def _thumbnail_pixmap(image: np.ndarray) -> QPixmap:
    """Vorschaubild des Kandidaten mit Markierung der Fundstelle.

    Der Ausschnitt ist um die Fundposition zentriert (siehe core.detection). Ohne
    Markierung ist im Rauschen nicht erkennbar, worauf sich der Treffer bezieht.
    """
    # Engerer Stretch als im Viewer: hier geht es um Kandidaten dicht an der SNR-Schwelle.
    # Bei der Viewer-Voreinstellung von 20 σ bliebe ein 5-σ-Fund fast schwarz. Dass helle
    # Sterne dabei ausbrennen, ist in einem Vorschaubild ohne Belang.
    stretched = np.ascontiguousarray(stretch_to_uint8(image, low_sigma=-1.0, high_sigma=8.0))
    height, width = stretched.shape
    qimage = QImage(stretched.data, width, height, width, QImage.Format.Format_Grayscale8).copy()
    pixmap = QPixmap.fromImage(qimage).scaled(
        THUMBNAIL_DISPLAY_SIZE,
        THUMBNAIL_DISPLAY_SIZE,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    painter = QPainter(pixmap)
    pen = QPen(QColor("#ff5c5c"))
    pen.setWidth(1)
    painter.setPen(pen)
    centre = pixmap.width() / 2, pixmap.height() / 2
    radius = pixmap.width() * 0.18
    # Offener Kreis statt Fadenkreuz: die Fundstelle selbst bleibt sichtbar.
    painter.drawEllipse(
        int(centre[0] - radius), int(centre[1] - radius), int(2 * radius), int(2 * radius)
    )
    painter.end()
    return pixmap


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
    """Auswahlfeld zur Bestätigung/Verwerfung. Bewusst als Delegate statt als
    `setCellWidget`-Widget: Zellen-Widgets bleiben beim Sortieren an ihrer alten
    Bildschirmzeile stehen und würden dann zum falschen Kandidaten gehören."""

    def createEditor(
        self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex
    ) -> QWidget:
        editor = QComboBox(parent)
        editor.addItems([status_label(value) for value in STATUS_ORDER])
        return editor

    def setEditorData(self, editor: QComboBox, index: QModelIndex) -> None:
        editor.setCurrentIndex(STATUS_ORDER.index(index.data(CONFIRMED_ROLE)))

    def setModelData(self, editor: QComboBox, model, index: QModelIndex) -> None:
        # Der Zustand wird als Wert gesetzt, nicht als Text: aus übersetztem Text
        # zurückzuschließen wäre sprachabhängig und damit zerbrechlich.
        model.setData(index, STATUS_ORDER[editor.currentIndex()], CONFIRMED_ROLE)


class TriageTable(QTableWidget):
    """Tabelle, die Bewertungen per Tastatur entgegennimmt.

    Beim Sichten hunderter Kandidaten ist der Weg über das Auswahlfeld (zwei Klicks je
    Kandidat) der Engpass. Mit J/N wird bewertet und automatisch zum nächsten Kandidaten
    gesprungen, sodass eine Hand am Platz bleiben kann.
    """

    rated = Signal(int, object)  # Zeile, neuer Bestätigungszustand

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt-Namenskonvention)
        key = Qt.Key(event.key())
        if key in KEY_TO_CONFIRMED and self.currentRow() >= 0:
            self.rated.emit(self.currentRow(), KEY_TO_CONFIRMED[key])
            next_row = self.currentRow() + 1
            if next_row < self.rowCount():
                self.selectRow(next_row)
            event.accept()
            return
        super().keyPressEvent(event)


class ResultsTable(QWidget):
    """Kandidatenliste mit Vorschaubild pro Treffer, sortierbaren Spalten und manueller
    Bestätigung/Verwerfung durch den Nutzer (false positives sind bei Synthetic Tracking
    normal)."""

    #: Wird ausgelöst, wenn sich eine Bewertung ändert — der Export hängt davon ab.
    confirmation_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._detections: list[DetectionResult] = []
        #: Verhindert, dass das Nachführen von Text und Farbe erneut itemChanged auslöst.
        self._updating_item = False

        self.summary_label = QLabel(self.tr("Keine Kandidaten."), self)
        self.hint_label = QLabel(
            self.tr("Tastatur: J bestätigen · N verwerfen · 0 zurücksetzen — springt weiter."),
            self,
        )
        self.hint_label.setStyleSheet("color: #9a9a9a; font-size: 11px;")

        self.table = TriageTable(0, len(column_labels()), self)
        self.table.setHorizontalHeaderLabels(column_labels())
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setIconSize(QSize(THUMBNAIL_DISPLAY_SIZE, THUMBNAIL_DISPLAY_SIZE))
        self.table.setSortingEnabled(True)
        self.table.setItemDelegateForColumn(STATUS_COLUMN, StatusDelegate(self.table))
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.SelectedClicked
        )
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.rated.connect(self._on_rated)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)
        layout.addWidget(self.hint_label)

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
                row, SNR_COLUMN, NumericTableWidgetItem(f"{detection.snr:.1f}", detection.snr)
            )

            status_item = QTableWidgetItem()
            status_item.setData(DETECTION_ROLE, detection)
            self._apply_status(status_item, detection.confirmed)
            self.table.setItem(row, STATUS_COLUMN, status_item)

        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)
        self.table.sortItems(SNR_COLUMN, Qt.SortOrder.DescendingOrder)
        self.table.resizeRowsToContents()
        if detections:
            self.table.selectRow(0)
            self.table.setFocus()
        self._update_summary()

    def _apply_status(self, item: QTableWidgetItem, confirmed: bool | None) -> None:
        """Setzt Zustand, Beschriftung und Farbe konsistent an einem Item."""
        self._updating_item = True
        try:
            item.setData(CONFIRMED_ROLE, confirmed)
            item.setText(status_label(confirmed))
            item.setForeground(QColor(STATUS_COLORS[confirmed]))
        finally:
            self._updating_item = False

    def _update_summary(self) -> None:
        """Zeigt den Sichtungsfortschritt. Bei hunderten Kandidaten ist die reine Gesamtzahl
        wenig hilfreich — entscheidend ist, wie viel noch offen ist."""
        total = len(self._detections)
        if not total:
            self.summary_label.setText(self.tr("Keine Kandidaten."))
            return
        confirmed = sum(1 for d in self._detections if d.confirmed is True)
        rejected = sum(1 for d in self._detections if d.confirmed is False)
        self.summary_label.setText(
            self.tr("{total} Kandidaten · {confirmed} bestätigt · {rejected} verworfen · "
                    "{open} offen").format(
                total=total,
                confirmed=confirmed,
                rejected=rejected,
                open=total - confirmed - rejected,
            )
        )

    def _on_rated(self, row: int, confirmed: bool | None) -> None:
        """Bewertung über die Tastatur."""
        item = self.table.item(row, STATUS_COLUMN)
        if item is None:
            return
        self._apply_status(item, confirmed)
        self._sync_detection(item)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._updating_item or item.column() != STATUS_COLUMN:
            return
        # Änderung kam vom Auswahlfeld: Beschriftung und Farbe nachziehen.
        self._apply_status(item, item.data(CONFIRMED_ROLE))
        self._sync_detection(item)

    def _sync_detection(self, item: QTableWidgetItem) -> None:
        detection = item.data(DETECTION_ROLE)
        if detection is None:
            return
        detection.confirmed = item.data(CONFIRMED_ROLE)
        self._update_summary()
        self.confirmation_changed.emit()

    def detections(self) -> list[DetectionResult]:
        return list(self._detections)
