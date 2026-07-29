from __future__ import annotations

import numpy as np
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.astrometry import AstrometricSolution


def column_labels() -> list[str]:
    """Als Funktion statt als Konstante: eine Konstante würde beim Import ausgewertet,
    also bevor die Übersetzung installiert ist."""
    return [
        QCoreApplication.translate("AstrometryPanel", "Stern"),
        QCoreApplication.translate("AstrometryPanel", "Residuum"),
    ]


class AstrometryPanel(QWidget):
    """Zeigt das Ergebnis des Gaia-WCS-Fits dauerhaft an: Kennzahlen sowie die Residuen
    der einzelnen gematchten Sterne (nicht nur den RMS), damit Ausreißer im Fit sichtbar
    werden."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.summary_label = QLabel(self.tr("Keine Astrometrie berechnet."), self)
        self.summary_label.setWordWrap(True)

        self.table = QTableWidget(0, len(column_labels()), self)
        self.table.setHorizontalHeaderLabels(column_labels())
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)

    def set_solution(self, solution: AstrometricSolution) -> None:
        residuals = np.asarray(solution.residuals_arcsec, dtype=float)
        self.summary_label.setText(
            self.tr("{matches} Gaia-Matches — RMS {rms:.3f}″, Median {median:.3f}″, "
                    "Max {maximum:.3f}″").format(
                matches=solution.n_matches,
                rms=solution.rms_residual_arcsec,
                median=np.median(residuals),
                maximum=residuals.max(),
            )
        )

        # Größte Residuen zuerst: dort stecken Fehlzuordnungen oder verzerrte Sterne.
        order = np.argsort(residuals)[::-1]
        self.table.setRowCount(len(order))
        for row, star_index in enumerate(order):
            index_item = QTableWidgetItem(f"#{int(star_index) + 1}")
            residual_item = QTableWidgetItem(f"{residuals[star_index]:.3f}″")
            residual_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(row, 0, index_item)
            self.table.setItem(row, 1, residual_item)
