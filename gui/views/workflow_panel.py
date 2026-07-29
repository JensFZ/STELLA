from __future__ import annotations

from enum import Enum

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class StepState(Enum):
    """Zustand eines Arbeitsschritts."""

    LOCKED = "gesperrt"  # Voraussetzung fehlt noch
    AVAILABLE = "verfügbar"  # kann jetzt ausgeführt werden
    RUNNING = "läuft"
    DONE = "erledigt"


_MARKERS = {
    StepState.LOCKED: "○",
    StepState.AVAILABLE: "●",
    StepState.RUNNING: "◌",
    StepState.DONE: "✓",
}

_COLORS = {
    StepState.LOCKED: "#6b6b6b",
    StepState.AVAILABLE: "#4da3ff",
    StepState.RUNNING: "#4da3ff",
    StepState.DONE: "#5fbf7f",
}


class _StepRow(QFrame):
    """Eine Zeile der Schrittleiste. Klickbar, sobald der Schritt verfügbar ist."""

    activated = Signal()

    def __init__(self, number: int, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._state = StepState.LOCKED

        self.title_label = QLabel(f"{number}  {title}", self)
        self.title_label.setWordWrap(True)
        self.detail_label = QLabel("", self)
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("color: #9a9a9a; font-size: 11px;")
        self.detail_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        layout.addWidget(self.title_label)
        layout.addWidget(self.detail_label)

        self._apply_state()

    def set_state(self, state: StepState, detail: str = "") -> None:
        self._state = state
        self.detail_label.setText(detail)
        self.detail_label.setVisible(bool(detail))
        self._apply_state()

    def state(self) -> StepState:
        return self._state

    def _apply_state(self) -> None:
        colour = _COLORS[self._state]
        marker = _MARKERS[self._state]
        text = self.title_label.text()
        # Markierung nur austauschen, Titel unverändert lassen.
        if text and text[0] in _MARKERS.values():
            text = text[1:].lstrip()
        self.title_label.setText(f"{marker}  {text.lstrip()}")

        clickable = self._state in (StepState.AVAILABLE, StepState.DONE)
        self.title_label.setStyleSheet(
            f"color: {colour}; font-weight: {'600' if self._state != StepState.LOCKED else '400'};"
        )
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor
        )
        self.setStyleSheet(
            "_StepRow { border-radius: 4px; }"
            + (
                "_StepRow:hover { background: rgba(255,255,255,0.06); }"
                if clickable
                else ""
            )
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt-Namenskonvention)
        if self._state in (StepState.AVAILABLE, StepState.DONE):
            self.activated.emit()
        super().mousePressEvent(event)


class WorkflowPanel(QWidget):
    """Zeigt den Arbeitsablauf als Schrittfolge.

    STELLA hat einen streng sequenziellen Ablauf — jeder Schritt setzt den vorherigen
    voraus. Bisher war das nur an ausgegrauten Menüeinträgen erkennbar, also praktisch
    unsichtbar. Die Leiste macht Reihenfolge *und* Fortschritt sichtbar und ist zugleich
    der direkte Weg, den nächsten Schritt auszulösen.
    """

    step_activated = Signal(int)

    STEP_LOAD = 0
    STEP_ALIGN = 1
    STEP_DETECT = 2
    STEP_ASTROMETRY = 3
    STEP_EXPORT = 4

    TITLES = [
        "FITS-Ordner laden",
        "Sterne erkennen & ausrichten",
        "Kandidaten suchen",
        "Astrometrie berechnen",
        "MPC-Report exportieren",
    ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.setFixedWidth(240)

        heading = QLabel("Arbeitsablauf", self)
        heading.setStyleSheet("font-weight: 600; padding: 10px 10px 4px 10px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addWidget(heading)

        self._rows: list[_StepRow] = []
        for index, title in enumerate(self.TITLES):
            row = _StepRow(index + 1, title, self)
            row.activated.connect(lambda i=index: self.step_activated.emit(i))
            self._rows.append(row)
            layout.addWidget(row)

        layout.addStretch(1)
        self.set_state(self.STEP_LOAD, StepState.AVAILABLE)

    def set_state(self, step: int, state: StepState, detail: str = "") -> None:
        self._rows[step].set_state(state, detail)

    def state(self, step: int) -> StepState:
        return self._rows[step].state()

    def reset_from(self, step: int) -> None:
        """Setzt diesen und alle folgenden Schritte auf gesperrt zurück.

        Nötig, wenn ein früherer Schritt erneut ausgeführt wird: die Ergebnisse der
        späteren Schritte gelten dann nicht mehr.
        """
        for index in range(step, len(self._rows)):
            self._rows[index].set_state(StepState.LOCKED, "")
