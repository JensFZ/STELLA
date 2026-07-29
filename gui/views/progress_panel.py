from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QWidget,
)


class ProgressPanel(QWidget):
    """Fortschrittsanzeige für lang laufende Jobs (Gittersuche, Alignment). Blendet sich
    selbst aus, solange nichts läuft, und bietet optional einen Abbrechen-Knopf."""

    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self.label = QLabel("", self)
        self.bar = QProgressBar(self)
        self.bar.setMinimum(0)
        self.bar.setMaximum(1)
        self.bar.setValue(0)

        self.cancel_button = QPushButton("Abbrechen", self)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.addWidget(self.label)
        layout.addWidget(self.bar, stretch=1)
        layout.addWidget(self.cancel_button)

        self.hide()

    def start(self, label: str, cancellable: bool = False) -> None:
        self.label.setText(label)
        self.cancel_button.setVisible(cancellable)
        self.cancel_button.setEnabled(cancellable)
        # Unbestimmter Zustand (0/0), bis der erste echte Fortschrittswert eintrifft.
        self.bar.setMaximum(0)
        self.bar.setValue(0)
        self.show()

    def set_progress(self, current: int, total: int) -> None:
        if total <= 0:
            self.bar.setMaximum(0)
            return
        self.bar.setMaximum(total)
        self.bar.setValue(current)

    def set_label(self, text: str) -> None:
        self.label.setText(text)

    def finish(self) -> None:
        self.hide()
        self.bar.setMaximum(1)
        self.bar.setValue(0)
        self.label.setText("")

    def _on_cancel_clicked(self) -> None:
        self.cancel_button.setEnabled(False)
        self.label.setText("Abbruch angefordert ...")
        self.cancel_requested.emit()
