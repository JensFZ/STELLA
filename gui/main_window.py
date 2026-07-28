from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox

from core.io_fits import FrameStack
from gui.views.image_viewer import ImageViewer
from gui.workers import FrameStackLoader


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STELLA")
        self.resize(1200, 800)

        self._loader: FrameStackLoader | None = None
        self.image_viewer = ImageViewer(self)
        self.setCentralWidget(self.image_viewer)
        self.statusBar()

        self._build_menu()

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&Datei")
        open_action = QAction("FITS-Ordner öffnen...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_fits_folder)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        exit_action = QAction("Beenden", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        project_menu = menu_bar.addMenu("&Projekt")
        project_menu.addAction(QAction("Neues Projekt...", self))
        project_menu.addAction(QAction("Projekt öffnen...", self))

        help_menu = menu_bar.addMenu("&Hilfe")
        about_action = QAction("Über STELLA", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "Über STELLA",
            "STELLA — Synthetic Tracking Engine for Locating & Logging Asteroids\n"
            "Open-Source Synthetic-Tracking-Tool für Asteroiden-Detektion.",
        )

    def _open_fits_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "FITS-Ordner öffnen")
        if not folder:
            return

        self._loader = FrameStackLoader(folder, self)
        self._loader.progress.connect(self._on_load_progress)
        self._loader.finished_loading.connect(self._on_load_finished)
        self._loader.failed.connect(self._on_load_failed)
        self.statusBar().showMessage(f"Lade FITS-Frames aus {folder} ...")
        self._loader.start()

    def _on_load_progress(self, current: int, total: int) -> None:
        self.statusBar().showMessage(f"Lade Frame {current} / {total} ...")

    def _on_load_finished(self, stack: FrameStack) -> None:
        self.image_viewer.set_stack(stack)
        self.statusBar().showMessage(f"{len(stack)} Frames geladen.", 5000)

    def _on_load_failed(self, message: str) -> None:
        self.statusBar().clearMessage()
        QMessageBox.critical(self, "Fehler beim Laden", message)
