from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QCoreApplication, QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

#: Dauer eines vollen Pulszyklus (hell -> gedimmt -> hell) in Millisekunden.
PULSE_DURATION_MS = 1400
#: Untere Deckkraft des Pulses. Nicht bis 0, sonst wirkt die Zeile kurz wie ausgeschaltet
#: statt wie ein Atmen.
PULSE_MIN_OPACITY = 0.55


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

        # Sanftes Pulsieren markiert den Schritt, an dem es weitergeht — ohne einen
        # zusätzlichen "Weiter"-Button, der bei zwei parallel verfügbaren Schritten (siehe
        # WorkflowPanel-Docstring) ohnehin eine Reihenfolge vortäuschen würde, die es nicht
        # gibt. Läuft nur für StepState.AVAILABLE; DONE/RUNNING/LOCKED bleiben ruhig.
        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)
        self._pulse = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._pulse.setDuration(PULSE_DURATION_MS)
        self._pulse.setStartValue(1.0)
        self._pulse.setKeyValueAt(0.5, PULSE_MIN_OPACITY)
        self._pulse.setEndValue(1.0)
        self._pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse.setLoopCount(-1)

        self._apply_state()

    def set_state(self, state: StepState, detail: str = "") -> None:
        self._state = state
        self.detail_label.setText(detail)
        self.detail_label.setVisible(bool(detail))
        self._apply_state()
        if state == StepState.AVAILABLE:
            if self._pulse.state() != QPropertyAnimation.State.Running:
                self._pulse.start()
        else:
            self._pulse.stop()
            self._opacity_effect.setOpacity(1.0)

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

    @staticmethod
    def titles() -> list[str]:
        """Als Funktion statt als Konstante: eine Klassenkonstante würde beim Import
        ausgewertet, also bevor die Übersetzung installiert ist."""
        translate = QCoreApplication.translate
        return [
            translate("WorkflowPanel", "FITS-Ordner laden"),
            translate("WorkflowPanel", "Sterne erkennen & ausrichten"),
            translate("WorkflowPanel", "Kandidaten suchen"),
            translate("WorkflowPanel", "Astrometrie berechnen"),
            translate("WorkflowPanel", "MPC-Report exportieren"),
        ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        self.setFixedWidth(240)

        heading = QLabel(self.tr("Arbeitsablauf"), self)
        heading.setStyleSheet("font-weight: 600; padding: 10px 10px 4px 10px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        layout.addWidget(heading)

        self._rows: list[_StepRow] = []
        for index, title in enumerate(self.titles()):
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
