import logging
import os
import sys

# Logging wird vor allen weiteren Projekt-Importen eingerichtet, damit auch Fehler beim
# Laden der schweren Abhängigkeiten (astropy, photutils, torch) in der Logdatei landen.
# Genau solche Importfehler treten im gebauten Paket auf und sind ohne Konsole sonst nicht
# nachvollziehbar.
from core.logging_setup import configure_logging, install_excepthook, log_environment

LOG_PATH = configure_logging()
install_excepthook()

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.i18n import LANGUAGE_ENV_VAR, install_translator  # noqa: E402
from gui.main_window import MainWindow  # noqa: E402

#: Baut die Oberfläche auf und beendet sich sofort mit einem aussagekräftigen Rückgabewert,
#: statt in die Ereignisschleife zu gehen. Damit lässt sich ein gebautes Bundle auch dort
#: prüfen, wo kein sichtbares Fenster entsteht — siehe scripts/smoke_test_build.ps1.
SELFTEST_FLAG = "--selftest"


def _run_selftest(window: MainWindow, language: str) -> int:
    logger = logging.getLogger("stella.main")

    title = window.windowTitle()
    if title != "STELLA":
        logger.error("Selbsttest: unerwarteter Fenstertitel %r", title)
        return 1

    # Eine angeforderte Sprache, die nicht ankommt, heißt: die .qm fehlt im Bundle.
    # install_translator() fällt in dem Fall stillschweigend auf die Quellsprache zurück,
    # der Rückgabewert ist also der einzige Weg, das zu bemerken.
    requested = os.environ.get(LANGUAGE_ENV_VAR)
    if requested and requested != language:
        logger.error("Selbsttest: Sprache %r angefordert, aktiv ist %r", requested, language)
        return 1

    logger.info("Selbsttest bestanden (Sprache %s)", language)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    logger = logging.getLogger("stella.main")
    logger.info("Logdatei: %s", LOG_PATH)
    log_environment()

    app = QApplication(argv)
    # Muss vor dem Aufbau der Oberfläche geschehen: Beschriftungen werden beim Erzeugen
    # der Widgets übersetzt, ein späteres Installieren käme zu spät.
    language = install_translator(app)
    logger.info("Oberflächensprache: %s", language)

    window = MainWindow()

    if SELFTEST_FLAG in argv:
        return _run_selftest(window, language)

    window.show()

    exit_code = app.exec()
    logger.info("STELLA beendet (Rückgabewert %s)", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
