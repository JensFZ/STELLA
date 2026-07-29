import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.i18n import (  # noqa: E402
    LANGUAGE_ENV_VAR,
    SOURCE_LANGUAGE,
    SUPPORTED_LANGUAGES,
    install_translator,
    resolve_language,
    translations_directory,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv(LANGUAGE_ENV_VAR, raising=False)


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
    monkeypatch.setenv(LANGUAGE_ENV_VAR, "kl")  # Klingonisch gibt es (noch) nicht

    assert resolve_language() == SOURCE_LANGUAGE


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
