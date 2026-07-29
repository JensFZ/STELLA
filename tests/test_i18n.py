import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import i18n  # noqa: E402
from core.i18n import (  # noqa: E402
    LANGUAGE_ENV_VAR,
    SOURCE_LANGUAGE,
    SUPPORTED_LANGUAGES,
    install_translator,
    resolve_language,
    translations_directory,
)

#: Nicht unterstütztes Kürzel — steht für „diese Quelle liefert nichts Brauchbares“.
UNSUPPORTED = "kl"  # Klingonisch gibt es (noch) nicht


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolate_language_sources(monkeypatch):
    """Löst die Sprachwahl von der Umgebung des ausführenden Rechners.

    resolve_language() zieht neben der Umgebungsvariable auch die gespeicherte Einstellung
    und die Systemsprache heran. Ohne diese Isolierung hängt das Ergebnis davon ab, wo die
    Tests laufen: auf einem deutschen Windows ist die Systemsprache zufällig gleich der
    Quellsprache und der Rückfall lässt sich nicht von ihr unterscheiden — auf dem
    englischen CI-Runner dagegen gewinnt sie, und der Test scheitert. Wer die Systemsprache
    prüfen will, setzt sie hier gezielt.
    """
    monkeypatch.delenv(LANGUAGE_ENV_VAR, raising=False)
    monkeypatch.setattr(i18n, "saved_language", lambda: None)
    monkeypatch.setattr(i18n, "_system_language", lambda: UNSUPPORTED)


def test_source_language_is_supported():
    assert SOURCE_LANGUAGE in SUPPORTED_LANGUAGES


def test_every_supported_language_except_source_has_a_compiled_file():
    """Ohne .qm bliebe die Oberfläche stillschweigend in der Quellsprache — die Sprache
    stünde dann im Menü, ohne zu wirken."""
    for language in SUPPORTED_LANGUAGES:
        if language == SOURCE_LANGUAGE:
            continue
        path = translations_directory() / f"stella_{language}.qm"
        assert path.exists(), f"Übersetzungsdatei fehlt: {path} — scripts/update_translations.ps1"


def test_explicit_language_wins(monkeypatch):
    monkeypatch.setenv(LANGUAGE_ENV_VAR, "de")

    assert resolve_language("en") == "en"


def test_environment_variable_is_used(monkeypatch):
    monkeypatch.setenv(LANGUAGE_ENV_VAR, "en")

    assert resolve_language() == "en"


def test_unsupported_language_falls_back_to_source(monkeypatch):
    monkeypatch.setenv(LANGUAGE_ENV_VAR, UNSUPPORTED)

    assert resolve_language() == SOURCE_LANGUAGE


def test_saved_setting_is_used_when_no_environment_variable(monkeypatch):
    monkeypatch.setattr(i18n, "saved_language", lambda: "en")

    assert resolve_language() == "en"


def test_system_language_is_used_as_last_resort(monkeypatch):
    """Ohne jede Vorgabe folgt STELLA dem Betriebssystem — der übliche Fall beim
    Erststart. Das deckte bisher kein Test ab; auf einem deutschen Rechner war das
    Ergebnis von der Quellsprache nicht zu unterscheiden."""
    monkeypatch.setattr(i18n, "_system_language", lambda: "en")

    assert resolve_language() == "en"


def test_saved_setting_beats_system_language(monkeypatch):
    monkeypatch.setattr(i18n, "saved_language", lambda: "de")
    monkeypatch.setattr(i18n, "_system_language", lambda: "en")

    assert resolve_language() == "de"


def test_install_translator_translates_the_user_interface():
    app = _app()

    install_translator(app, "en")
    from gui.views.results_table import status_label

    assert status_label(True) == "Confirmed"

    install_translator(app, "de")
    assert status_label(True) == "Bestätigt"


def test_install_translator_returns_effective_language():
    app = _app()
    try:
        assert install_translator(app, "en") == "en"
        # Nicht unterstützt -> Rückfall auf die Quellsprache
        assert install_translator(app, "xx") == SOURCE_LANGUAGE
    finally:
        install_translator(app, SOURCE_LANGUAGE)
