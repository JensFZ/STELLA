import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
from astropy.io import fits  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.io_fits import scan_folder  # noqa: E402
from gui.views.session_dialog import SessionSelectDialog  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write(path, when: str, shape=(16, 16)) -> None:
    header = fits.Header()
    header["DATE-OBS"] = when
    fits.writeto(path, np.zeros(shape, dtype=np.float32), header, overwrite=True)


def _folder_with_three_sessions(tmp_path):
    # Kurze Serie, lange Serie, mittlere Serie — bewusst nicht in Längen-Reihenfolge,
    # damit die Vorauswahl nicht zufällig die erste Zeile trifft.
    for i in range(2):
        _write(tmp_path / f"a{i}.fits", f"2025-02-09T02:00:{i:02d}")
    for i in range(6):
        _write(tmp_path / f"b{i}.fits", f"2025-02-16T23:00:{i:02d}")
    for i in range(4):
        _write(tmp_path / f"c{i}.fits", f"2025-03-19T21:00:{i:02d}")
    return scan_folder(tmp_path)


def test_dialog_lists_every_session(tmp_path):
    _app()
    scan = _folder_with_three_sessions(tmp_path)

    dialog = SessionSelectDialog(scan)

    assert dialog.table.rowCount() == 3


def test_dialog_preselects_longest_session(tmp_path):
    """Vorauswahl muss die längste Serie sein — sie ist praktisch immer die gesuchte."""
    _app()
    scan = _folder_with_three_sessions(tmp_path)

    dialog = SessionSelectDialog(scan)

    # Serien sind chronologisch sortiert: Index 1 ist die vom 16.02. mit 6 Frames.
    assert dialog.selected_session_index() == 1
    assert dialog.table.item(1, 3).text() == "6"


def test_dialog_returns_manually_chosen_session(tmp_path):
    _app()
    scan = _folder_with_three_sessions(tmp_path)
    dialog = SessionSelectDialog(scan)

    dialog.table.selectRow(2)

    assert dialog.selected_session_index() == 2


def test_dialog_shows_how_many_frames_fit_the_budget(tmp_path):
    """Die Spalte 'davon geladen' muss das Speicherbudget berücksichtigen, sonst verspricht
    der Dialog mehr Frames, als anschließend tatsächlich geladen werden."""
    _app()
    scan = _folder_with_three_sessions(tmp_path)
    per_frame = 16 * 16 * 4

    dialog = SessionSelectDialog(scan, memory_budget_bytes=3 * per_frame)

    assert dialog.table.item(1, 3).text() == "6"  # vorhandene Frames
    assert dialog.table.item(1, 4).text() == "3"  # davon ladbar
