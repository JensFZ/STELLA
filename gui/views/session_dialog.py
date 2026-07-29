from __future__ import annotations

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.io_fits import (
    DEFAULT_MEMORY_BUDGET_BYTES,
    FolderScan,
    Session,
    group_into_sessions,
    select_frames_to_load,
)


def column_labels() -> list[str]:
    """Als Funktion statt als Konstante: eine Konstante würde beim Import ausgewertet,
    also bevor die Übersetzung installiert ist."""
    translate = QCoreApplication.translate
    return [
        translate("SessionSelectDialog", "Beginn"),
        translate("SessionSelectDialog", "Ende"),
        translate("SessionSelectDialog", "Dauer"),
        translate("SessionSelectDialog", "Frames"),
        translate("SessionSelectDialog", "davon geladen"),
    ]


def _format_time(value: str | None, with_date: bool = True) -> str:
    if not value:
        return "—"
    date, _, time = value.partition("T")
    return f"{date} {time[:8]}" if with_date else time[:8]


class SessionSelectDialog(QDialog):
    """Auswahl der Aufnahmeserie, die geladen werden soll.

    Aufnahmeordner enthalten häufig mehrere Nächte. Gestapelt werden kann immer nur eine
    zusammenhängende Serie — daher die explizite Auswahl statt einer stillen Entscheidung.
    Vorausgewählt ist die längste Serie, weil sie in aller Regel die gesuchte ist.
    """

    def __init__(
        self,
        scan: FolderScan,
        parent: QWidget | None = None,
        memory_budget_bytes: int = DEFAULT_MEMORY_BUDGET_BYTES,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Aufnahmeserie auswählen"))
        self.resize(700, 320)

        self._shape = scan.dominant_shape()
        self._sessions: list[Session] = group_into_sessions(scan.for_shape(self._shape))

        skipped = len(scan.infos) - len(scan.for_shape(self._shape))
        summary = self.tr(
            "{files} FITS-Dateien, Bildgröße {width}×{height} px, {sessions} Aufnahmeserie(n)."
        ).format(
            files=len(scan.infos),
            width=self._shape[1],
            height=self._shape[0],
            sessions=len(self._sessions),
        )
        if skipped:
            summary += "\n" + self.tr(
                "{skipped} Datei(en) mit abweichender Bildgröße werden übersprungen — "
                "gemeinsames Stapeln setzt ein einheitliches Bildraster voraus."
            ).format(skipped=skipped)

        self.table = QTableWidget(len(self._sessions), len(column_labels()), self)
        self.table.setHorizontalHeaderLabels(column_labels())
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(self.accept)

        for row, session in enumerate(self._sessions):
            loadable = len(
                select_frames_to_load(
                    scan,
                    shape=self._shape,
                    session_index=row,
                    memory_budget_bytes=memory_budget_bytes,
                )
            )
            values = [
                _format_time(session.start),
                _format_time(session.end, with_date=False),
                f"{session.duration_minutes:.0f} min",
                str(len(session)),
                str(loadable),
            ]
            for column, text in enumerate(values):
                item = QTableWidgetItem(text)
                if column >= 2:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(row, column, item)

        longest_index = max(range(len(self._sessions)), key=lambda i: len(self._sessions[i]))
        self.table.selectRow(longest_index)

        hint = QLabel(
            self.tr(
                "Es kann nur eine zusammenhängende Serie verarbeitet werden: zwischen zwei "
                "Nächten ändert sich die Ausrichtung des Teleskops, und ein bewegtes Objekt "
                "hätte das Bildfeld längst verlassen.\n"
                "Passen nicht alle Frames einer Serie in den Speicher, wird ihr Anfang geladen."
            ),
            self,
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(summary, self))
        layout.addWidget(self.table)
        layout.addWidget(hint)
        layout.addWidget(buttons)

    def selected_session_index(self) -> int:
        row = self.table.currentRow()
        return row if row >= 0 else 0
