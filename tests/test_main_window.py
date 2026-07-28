import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.main_window import MainWindow  # noqa: E402


def test_main_window_has_expected_menus():
    _app = QApplication.instance() or QApplication([])
    window = MainWindow()

    menu_titles = [action.text() for action in window.menuBar().actions()]

    assert any("Datei" in title for title in menu_titles)
    assert any("Projekt" in title for title in menu_titles)
    assert any("Hilfe" in title for title in menu_titles)

    window.close()
