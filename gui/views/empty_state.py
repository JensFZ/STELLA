from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class EmptyState(QWidget):
    """Einstiegsbildschirm, solange nichts geladen ist.

    Ersetzt die zuvor leere schwarze Fläche: die gab keinen Hinweis darauf, was zu tun ist,
    und die einzige sinnvolle Aktion versteckte sich im Menü.
    """

    open_folder_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        title = QLabel(self.tr("Kein Bildstapel geladen"), self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")

        description = QLabel(
            self.tr(
                "Wählen Sie einen Ordner mit kalibrierten FITS-Aufnahmen einer Nacht.\n"
                "Die Aufnahmen benötigen einen DATE-OBS-Zeitstempel im Header — er ist die "
                "Grundlage der Bewegungsrechnung."
            ),
            self,
        )
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)
        description.setStyleSheet("color: #9a9a9a;")
        # Feste statt maximaler Breite: bei umbrechendem Text berechnet Qt die nötige Höhe
        # aus der Breite. Ohne feste Breite fällt die Höhe zu klein aus und der Text wird
        # abgeschnitten.
        description.setFixedWidth(520)

        button = QPushButton(self.tr("FITS-Ordner öffnen ..."), self)
        button.setMinimumWidth(200)
        button.setDefault(True)
        button.clicked.connect(self.open_folder_requested)

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(description, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(20)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(2)
