import logging
import sys

import pytest

from core.logging_setup import configure_logging, install_excepthook, log_file_path


@pytest.fixture(autouse=True)
def _restore_logging():
    """Das Logging-Setup verändert globalen Zustand (Root-Logger, sys.excepthook) —
    nach jedem Test zurücksetzen, damit andere Tests nicht beeinflusst werden."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_hook = sys.excepthook
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    for handler in saved_handlers:
        root.addHandler(handler)
    root.setLevel(saved_level)
    sys.excepthook = saved_hook


def test_configure_logging_creates_file_and_writes(tmp_path):
    path = configure_logging(level="INFO", log_dir=tmp_path)

    logging.getLogger("stella.test").info("Testeintrag %d", 42)
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert path == log_file_path(tmp_path)
    assert path.exists()
    assert "Testeintrag 42" in path.read_text(encoding="utf-8")


def test_configure_logging_respects_level(tmp_path):
    configure_logging(level="WARNING", log_dir=tmp_path)

    logging.getLogger("stella.test").info("darf nicht erscheinen")
    logging.getLogger("stella.test").warning("muss erscheinen")
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file_path(tmp_path).read_text(encoding="utf-8")
    assert "darf nicht erscheinen" not in content
    assert "muss erscheinen" in content


def test_configure_logging_is_idempotent(tmp_path):
    """Mehrfaches Einrichten darf keine doppelten Handler anhängen — sonst stünde jede
    Zeile mehrfach in der Datei."""
    configure_logging(level="INFO", log_dir=tmp_path)
    configure_logging(level="INFO", log_dir=tmp_path)

    logging.getLogger("stella.test").info("einmalig")
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file_path(tmp_path).read_text(encoding="utf-8")
    assert content.count("einmalig") == 1


def test_configure_logging_without_stderr(tmp_path, monkeypatch):
    """Im mit console=False gebauten Programm ist sys.stderr None. Das darf das Einrichten
    nicht scheitern lassen und muss trotzdem in die Datei schreiben."""
    monkeypatch.setattr(sys, "stderr", None)

    configure_logging(level="INFO", log_dir=tmp_path)
    logging.getLogger("stella.test").info("ohne Konsole")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "ohne Konsole" in log_file_path(tmp_path).read_text(encoding="utf-8")


def test_install_excepthook_logs_traceback(tmp_path):
    configure_logging(level="INFO", log_dir=tmp_path)
    install_excepthook()

    try:
        raise ValueError("absichtlicher Testfehler")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file_path(tmp_path).read_text(encoding="utf-8")
    assert "Unbehandelte Ausnahme" in content
    assert "absichtlicher Testfehler" in content
    assert "ValueError" in content
