import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.detection import DetectionResult  # noqa: E402
from core.synthetic_tracking import VelocityVector  # noqa: E402
from gui.views.results_table import (  # noqa: E402
    CONFIRMED_ROLE,
    DETECTION_ROLE,
    STATUS_COLUMN,
    ResultsTable,
    status_label,
)


def _make_detection(snr: float, speed: float, confirmed: bool | None = None) -> DetectionResult:
    return DetectionResult(
        vector=VelocityVector(speed_arcsec_per_min=speed, angle_deg=0.0),
        position=(int(snr), int(speed)),
        snr=snr,
        peak_value=snr * 10,
        thumbnail=np.full((8, 8), snr),
        confirmed=confirmed,
    )


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_table_populates_and_sorts_by_snr_descending():
    _app()
    table = ResultsTable()

    table.set_detections([_make_detection(5.0, 1.0), _make_detection(50.0, 2.0)])

    assert table.table.rowCount() == 2
    assert table.table.item(0, 4).text() == "50.0"
    assert table.table.item(1, 4).text() == "5.0"


def test_numeric_columns_sort_numerically_not_lexicographically():
    _app()
    table = ResultsTable()
    # Rein textuell sortiert stünde "9.0" hinter "10.0" bzw. "100.0".
    table.set_detections(
        [_make_detection(9.0, 1.0), _make_detection(100.0, 2.0), _make_detection(10.0, 3.0)]
    )

    table.table.sortItems(4, Qt.SortOrder.AscendingOrder)

    values = [float(table.table.item(row, 4).text()) for row in range(table.table.rowCount())]
    assert values == [9.0, 10.0, 100.0]


def test_status_stays_with_its_candidate_after_sorting():
    """Regressionsschutz: Zellen-Widgets würden beim Sortieren an ihrer Bildschirmzeile
    kleben und dann zum falschen Kandidaten gehören. Die Zuordnung muss am Item hängen."""
    _app()
    table = ResultsTable()
    low, high = _make_detection(5.0, 1.0), _make_detection(50.0, 2.0)
    table.set_detections([low, high])

    # Nach absteigender SNR-Sortierung steht 'high' in Zeile 0 -> dort auf Bestätigt setzen.
    assert table.table.item(0, STATUS_COLUMN).data(DETECTION_ROLE) is high
    table.table.item(0, STATUS_COLUMN).setData(CONFIRMED_ROLE, True)
    assert high.confirmed is True
    assert low.confirmed is None

    # Umsortieren: 'high' rutscht auf Zeile 1, der Status muss mitwandern.
    table.table.sortItems(4, Qt.SortOrder.AscendingOrder)

    assert table.table.item(1, STATUS_COLUMN).data(DETECTION_ROLE) is high
    assert table.table.item(1, STATUS_COLUMN).data(CONFIRMED_ROLE) is True
    assert table.table.item(0, STATUS_COLUMN).data(DETECTION_ROLE) is low
    assert table.table.item(0, STATUS_COLUMN).data(CONFIRMED_ROLE) is None

    # Und ein Statuswechsel nach dem Sortieren trifft weiterhin den richtigen Kandidaten.
    table.table.item(0, STATUS_COLUMN).setData(CONFIRMED_ROLE, False)
    assert low.confirmed is False
    assert high.confirmed is True


def test_existing_confirmed_state_is_shown_on_load():
    _app()
    table = ResultsTable()

    table.set_detections([_make_detection(50.0, 1.0, confirmed=True)])

    item = table.table.item(0, STATUS_COLUMN)
    assert item.data(CONFIRMED_ROLE) is True
    assert item.text() == status_label(True)


def test_detections_accessor_returns_all_candidates():
    _app()
    table = ResultsTable()
    detections = [_make_detection(5.0, 1.0), _make_detection(50.0, 2.0)]

    table.set_detections(detections)

    assert table.detections() == detections


def test_keyboard_rates_current_row_and_advances():
    """Kernpfad der Triage: J bewertet und springt weiter, damit hunderte Kandidaten
    ohne Mausweg durchgesehen werden koennen."""
    _app()
    table = ResultsTable()
    high, low = _make_detection(50.0, 1.0), _make_detection(5.0, 2.0)
    table.set_detections([high, low])

    # Nach absteigender Sortierung steht 'high' in Zeile 0 und ist vorausgewaehlt.
    assert table.table.currentRow() == 0
    QTest.keyClick(table.table, Qt.Key.Key_J)

    assert high.confirmed is True
    assert table.table.currentRow() == 1, "muss automatisch zum naechsten Kandidaten springen"

    QTest.keyClick(table.table, Qt.Key.Key_N)
    assert low.confirmed is False


def test_keyboard_zero_resets_to_open():
    _app()
    table = ResultsTable()
    detection = _make_detection(50.0, 1.0, confirmed=True)
    table.set_detections([detection])

    QTest.keyClick(table.table, Qt.Key.Key_0)

    assert detection.confirmed is None


def test_keyboard_rating_hits_the_right_candidate_after_sorting():
    """Wie beim Mausweg muss die Zuordnung das Umsortieren ueberstehen."""
    _app()
    table = ResultsTable()
    high, low = _make_detection(50.0, 1.0), _make_detection(5.0, 2.0)
    table.set_detections([high, low])

    table.table.sortItems(4, Qt.SortOrder.AscendingOrder)  # jetzt steht 'low' oben
    table.table.selectRow(0)
    QTest.keyClick(table.table, Qt.Key.Key_J)

    assert low.confirmed is True
    assert high.confirmed is None


def test_summary_counts_progress():
    _app()
    table = ResultsTable()
    a, b, c = (
        _make_detection(50.0, 1.0),
        _make_detection(40.0, 2.0),
        _make_detection(30.0, 3.0),
    )
    table.set_detections([a, b, c])

    table.table.selectRow(0)
    QTest.keyClick(table.table, Qt.Key.Key_J)
    QTest.keyClick(table.table, Qt.Key.Key_N)

    text = table.summary_label.text()
    assert "3 Kandidaten" in text
    assert "1 bestätigt" in text
    assert "1 verworfen" in text
    assert "1 offen" in text


def test_unhandled_keys_are_passed_through():
    """Navigationstasten duerfen nicht verschluckt werden."""
    _app()
    table = ResultsTable()
    table.set_detections([_make_detection(50.0, 1.0), _make_detection(5.0, 2.0)])

    table.table.selectRow(0)
    QTest.keyClick(table.table, Qt.Key.Key_Down)

    assert table.table.currentRow() == 1
