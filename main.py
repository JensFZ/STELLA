import logging
import sys

# Logging wird vor allen weiteren Projekt-Importen eingerichtet, damit auch Fehler beim
# Laden der schweren Abhängigkeiten (astropy, photutils, torch) in der Logdatei landen.
# Genau solche Importfehler treten im gebauten Paket auf und sind ohne Konsole sonst nicht
# nachvollziehbar.
from core.logging_setup import configure_logging, install_excepthook, log_environment

LOG_PATH = configure_logging()
install_excepthook()

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.main_window import MainWindow  # noqa: E402


def main() -> int:
    logger = logging.getLogger("stella.main")
    logger.info("Logdatei: %s", LOG_PATH)
    log_environment()

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()

    exit_code = app.exec()
    logger.info("STELLA beendet (Rückgabewert %s)", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
