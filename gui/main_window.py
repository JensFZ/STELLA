import logging
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
)

from core.alignment import RegisteredStack
from core.astrometry import AstrometricSolution, estimate_field_center_and_scale, pixel_to_sky
from core.detection import DetectionResult
from core.io_fits import FrameStack
from core.logging_setup import log_file_path
from core.mpc_report import MPCObservation, write_mpc_report
from core.project import Project, ProjectStore
from core.synthetic_tracking import candidate_positions_per_frame
from gui.views.astrometry_panel import AstrometryPanel
from gui.views.astrometry_setup import AstrometrySetupDialog
from gui.views.image_viewer import ImageViewer
from gui.views.progress_panel import ProgressPanel
from gui.views.project_dialog import OpenProjectDialog
from gui.views.results_table import ResultsTable
from gui.views.search_setup import SearchSetupDialog
from gui.workers import AlignmentWorker, AstrometryWorker, DetectionWorker, FrameStackLoader

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STELLA")
        self.resize(1200, 800)

        self._loader: FrameStackLoader | None = None
        self._alignment_worker: AlignmentWorker | None = None
        self._detection_worker: DetectionWorker | None = None
        self._astrometry_worker: AstrometryWorker | None = None
        self._stack: FrameStack | None = None
        self._registered: RegisteredStack | None = None
        self._astrometric_solution: AstrometricSolution | None = None
        self._search_pixel_scale_arcsec: float | None = None
        self._project_store: ProjectStore | None = None
        self._current_project: Project | None = None
        self._restore_project_on_load: Project | None = None
        self.image_viewer = ImageViewer(self)
        self.setCentralWidget(self.image_viewer)

        self.progress_panel = ProgressPanel(self)
        self.progress_panel.cancel_requested.connect(self._cancel_detection)
        self.statusBar().addPermanentWidget(self.progress_panel, 1)

        self.results_table = ResultsTable(self)
        self.results_dock = QDockWidget("Kandidaten", self)
        self.results_dock.setWidget(self.results_table)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.results_dock)
        self.results_dock.hide()

        self.astrometry_panel = AstrometryPanel(self)
        self.astrometry_dock = QDockWidget("Astrometrie", self)
        self.astrometry_dock.setWidget(self.astrometry_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.astrometry_dock)
        self.astrometry_dock.hide()

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
        new_project_action = QAction("Neues Projekt...", self)
        new_project_action.triggered.connect(self._new_project)
        project_menu.addAction(new_project_action)

        open_project_action = QAction("Projekt öffnen...", self)
        open_project_action.triggered.connect(self._open_project)
        project_menu.addAction(open_project_action)

        self.save_session_action = QAction("Sitzung speichern", self)
        self.save_session_action.setEnabled(False)
        self.save_session_action.triggered.connect(self._save_session)
        project_menu.addAction(self.save_session_action)
        project_menu.addSeparator()
        self.align_action = QAction("Sterne erkennen && ausrichten...", self)
        self.align_action.setEnabled(False)
        self.align_action.triggered.connect(self._run_alignment)
        project_menu.addAction(self.align_action)

        self.detect_action = QAction("Kandidaten suchen...", self)
        self.detect_action.setEnabled(False)
        self.detect_action.triggered.connect(self._open_search_setup)
        project_menu.addAction(self.detect_action)

        project_menu.addSeparator()
        self.astrometry_action = QAction("Astrometrie berechnen...", self)
        self.astrometry_action.setEnabled(False)
        self.astrometry_action.triggered.connect(self._open_astrometry_setup)
        project_menu.addAction(self.astrometry_action)

        self.export_mpc_action = QAction("MPC-Report exportieren...", self)
        self.export_mpc_action.setEnabled(False)
        self.export_mpc_action.triggered.connect(self._export_mpc_report)
        project_menu.addAction(self.export_mpc_action)

        help_menu = menu_bar.addMenu("&Hilfe")
        show_log_action = QAction("Logdatei anzeigen", self)
        show_log_action.triggered.connect(self._show_log_file)
        help_menu.addAction(show_log_action)
        help_menu.addSeparator()
        about_action = QAction("Über STELLA", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_log_file(self) -> None:
        """Öffnet den Ordner mit der Logdatei im Dateimanager. Bewusst der Ordner und nicht
        die Datei selbst: so sind auch die rotierten älteren Logs greifbar, und es braucht
        keine Annahme darüber, womit .log-Dateien geöffnet werden."""
        path = log_file_path()
        if not path.exists():
            QMessageBox.information(
                self, "Logdatei", f"Noch keine Logdatei vorhanden.\nErwartet unter:\n{path}"
            )
            return
        try:
            if sys.platform == "win32":
                subprocess.run(["explorer", "/select,", str(path)], check=False)
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path.parent)], check=False)
        except Exception:  # noqa: BLE001
            logger.exception("Logordner konnte nicht geöffnet werden")
            QMessageBox.information(self, "Logdatei", f"Die Logdatei liegt unter:\n{path}")

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
        self._load_folder(folder)

    def _load_folder(self, folder: str) -> None:
        self._loader = FrameStackLoader(folder, parent=self)
        self._loader.status.connect(self.progress_panel.set_label)
        self._loader.progress.connect(self.progress_panel.set_progress)
        self._loader.finished_loading.connect(self._on_load_finished)
        self._loader.failed.connect(self._on_load_failed)
        self.progress_panel.start("FITS-Frames laden")
        self._loader.start()

    def _on_load_finished(self, stack: FrameStack) -> None:
        self.progress_panel.finish()
        self._stack = stack
        self.image_viewer.set_stack(stack)
        self.align_action.setEnabled(len(stack) > 1)
        self.statusBar().showMessage(f"{len(stack)} Frames geladen.", 5000)

        if self._restore_project_on_load is not None:
            project = self._restore_project_on_load
            self._restore_project_on_load = None
            detections = self._get_project_store().load_detections(project.id)
            if detections:
                self.results_table.set_detections(detections)
                self.results_dock.show()
                self.statusBar().showMessage(
                    f"{len(stack)} Frames geladen, {len(detections)} gespeicherte "
                    "Kandidat(en) wiederhergestellt.",
                    5000,
                )

    def _on_load_failed(self, message: str) -> None:
        self.progress_panel.finish()
        self.statusBar().clearMessage()
        QMessageBox.critical(self, "Fehler beim Laden", message)

    def _run_alignment(self) -> None:
        if self._stack is None:
            return
        self._alignment_worker = AlignmentWorker(self._stack, reference_index=0, parent=self)
        self._alignment_worker.progress.connect(self.progress_panel.set_progress)
        self._alignment_worker.finished_alignment.connect(self._on_align_finished)
        self._alignment_worker.failed.connect(self._on_align_failed)
        self.progress_panel.start("Sterne erkennen und ausrichten")
        self.align_action.setEnabled(False)
        self._alignment_worker.start()

    def _on_align_finished(self, registered: RegisteredStack) -> None:
        self.progress_panel.finish()
        self._registered = registered
        self.image_viewer.set_registered_stack(registered)
        self.align_action.setEnabled(True)
        self.detect_action.setEnabled(True)
        self.astrometry_action.setEnabled(True)
        self.statusBar().showMessage("Ausrichtung abgeschlossen.", 5000)

    def _on_align_failed(self, message: str) -> None:
        self.progress_panel.finish()
        self.align_action.setEnabled(True)
        self.statusBar().clearMessage()
        QMessageBox.critical(self, "Fehler bei der Ausrichtung", message)

    def _open_search_setup(self) -> None:
        if self._stack is None or self._registered is None:
            return
        dialog = SearchSetupDialog(self, project_store=self._get_project_store())
        if dialog.exec() != SearchSetupDialog.DialogCode.Accepted:
            return

        params = dialog.parameters()
        # Für die Positions-Rückrechnung beim MPC-Export wird derselbe Pixelmaßstab
        # gebraucht, mit dem die Vektor-Geschwindigkeiten in Pixel umgerechnet wurden.
        self._search_pixel_scale_arcsec = params["pixel_scale_arcsec"]

        self._detection_worker = DetectionWorker(
            self._stack, self._registered, params, parent=self
        )
        self._detection_worker.status.connect(self._on_detect_status)
        self._detection_worker.progress.connect(self.progress_panel.set_progress)
        self._detection_worker.finished_detection.connect(self._on_detect_finished)
        self._detection_worker.failed.connect(self._on_detect_failed)
        self.detect_action.setEnabled(False)
        self.progress_panel.start("Kandidatensuche", cancellable=True)
        self._detection_worker.start()

    def _on_detect_status(self, message: str) -> None:
        self.progress_panel.set_label(message)

    def _cancel_detection(self) -> None:
        if self._detection_worker is not None:
            self._detection_worker.cancel()

    def _on_detect_finished(self, detections: list[DetectionResult]) -> None:
        self.progress_panel.finish()
        self.detect_action.setEnabled(True)
        if not detections:
            self.statusBar().showMessage("Keine Kandidaten gefunden.", 5000)
            return
        self.results_table.set_detections(detections)
        self.results_dock.show()
        self.statusBar().showMessage(f"{len(detections)} Kandidat(en) gefunden.", 5000)

    def _on_detect_failed(self, message: str) -> None:
        self.progress_panel.finish()
        self.detect_action.setEnabled(True)
        self.statusBar().clearMessage()
        QMessageBox.critical(self, "Fehler bei der Kandidatensuche", message)

    def _open_astrometry_setup(self) -> None:
        if self._registered is None:
            return
        reference_index = self._registered.reference_index
        reference_frame = self._registered[reference_index].frame
        prefill = estimate_field_center_and_scale(reference_frame.wcs, reference_frame.data.shape)

        dialog = AstrometrySetupDialog(self, prefill=prefill)
        if dialog.exec() != AstrometrySetupDialog.DialogCode.Accepted:
            return

        reference_stars = self._registered[reference_index].stars
        self._astrometry_worker = AstrometryWorker(
            reference_stars, reference_frame.data.shape, dialog.parameters(), parent=self
        )
        self._astrometry_worker.status.connect(self.progress_panel.set_label)
        self._astrometry_worker.finished_astrometry.connect(self._on_astrometry_finished)
        self._astrometry_worker.failed.connect(self._on_astrometry_failed)
        self.astrometry_action.setEnabled(False)
        self.progress_panel.start("Astrometrie berechnen")
        self._astrometry_worker.start()

    def _on_astrometry_finished(self, solution: AstrometricSolution) -> None:
        self.progress_panel.finish()
        self._astrometric_solution = solution
        self.astrometry_action.setEnabled(True)
        self.export_mpc_action.setEnabled(True)
        self.astrometry_panel.set_solution(solution)
        self.astrometry_dock.show()
        self.statusBar().showMessage(
            f"Astrometrie: {solution.n_matches} Gaia-Matches, "
            f"RMS-Residuum {solution.rms_residual_arcsec:.3f}\"",
            8000,
        )

    def _on_astrometry_failed(self, message: str) -> None:
        self.progress_panel.finish()
        self.astrometry_action.setEnabled(True)
        self.statusBar().clearMessage()
        QMessageBox.critical(self, "Fehler bei der Astrometrie", message)

    def _export_mpc_report(self) -> None:
        if self._astrometric_solution is None or self._registered is None:
            return
        confirmed = [d for d in self.results_table.detections() if d.confirmed is True]
        if not confirmed:
            QMessageBox.warning(
                self,
                "Keine bestätigten Kandidaten",
                "Bitte zunächst mindestens einen Kandidaten in der Tabelle als "
                '"Bestätigt" markieren.',
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "MPC-Report speichern", "report.txt", "Textdateien (*.txt)"
        )
        if not path:
            return

        obs_times = [rf.frame.obs_time for rf in self._registered.frames]
        # Bei einer aus der Datenbank wiederhergestellten Sitzung lief in diesem Fenster
        # keine Suche — dann als bester verfügbarer Wert der Maßstab der gefitteten WCS.
        pixel_scale = self._search_pixel_scale_arcsec
        if pixel_scale is None:
            reference_frame = self._registered[self._registered.reference_index].frame
            estimate = estimate_field_center_and_scale(
                self._astrometric_solution.wcs, reference_frame.data.shape
            )
            pixel_scale = estimate[2]

        observations = []
        for detection in confirmed:
            # Kernalgorithmus Schritt 6: Position des Kandidaten pro Frame zurückrechnen,
            # damit der Report eine zeitlich verteilte Beobachtungsreihe enthält (eine
            # Einzelposition reicht dem MPC nicht für eine Bahnbestimmung).
            positions = candidate_positions_per_frame(
                detection.position,
                detection.vector,
                obs_times,
                self._registered.reference_index,
                pixel_scale,
            )
            for (row, col), obs_time in zip(positions, obs_times, strict=True):
                ra_deg, dec_deg = pixel_to_sky(self._astrometric_solution.wcs, row, col)
                observations.append(
                    MPCObservation(ra_deg=ra_deg, dec_deg=dec_deg, obs_time=obs_time)
                )

        write_mpc_report(observations, path)
        logger.info(
            "MPC-Report geschrieben: %s (%d Beobachtungen aus %d Kandidaten über %d Frames, "
            "Pixelmaßstab %.4f arcsec/px)",
            path,
            len(observations),
            len(confirmed),
            len(obs_times),
            pixel_scale,
        )
        self.statusBar().showMessage(
            f"MPC-Report gespeichert: {len(observations)} Beobachtung(en) "
            f"aus {len(confirmed)} Kandidat(en) über {len(obs_times)} Frames.",
            5000,
        )

    def _get_project_store(self) -> ProjectStore:
        if self._project_store is None:
            self._project_store = ProjectStore()
        return self._project_store

    def _new_project(self) -> None:
        name, ok = QInputDialog.getText(self, "Neues Projekt", "Projektname:")
        if not ok or not name.strip():
            return
        folder = QFileDialog.getExistingDirectory(self, "FITS-Ordner öffnen")
        if not folder:
            return

        self._current_project = self._get_project_store().create_project(name.strip(), folder)
        self.save_session_action.setEnabled(True)
        self.setWindowTitle(f"STELLA — {self._current_project.name}")
        self._load_folder(folder)

    def _open_project(self) -> None:
        dialog = OpenProjectDialog(self, self._get_project_store())
        if dialog.exec() != OpenProjectDialog.DialogCode.Accepted:
            return
        project = dialog.selected_project()
        if project is None:
            return

        self._current_project = project
        self.save_session_action.setEnabled(True)
        self.setWindowTitle(f"STELLA — {project.name}")
        self._restore_project_on_load = project
        self._load_folder(project.fits_folder)

    def _save_session(self) -> None:
        if self._current_project is None:
            return
        detections = self.results_table.detections()
        self._get_project_store().save_detections(self._current_project.id, detections)
        confirmed = sum(1 for d in detections if d.confirmed is True)
        logger.info(
            "Sitzung '%s' (ID %d) gespeichert: %d Kandidaten, davon %d bestätigt",
            self._current_project.name,
            self._current_project.id,
            len(detections),
            confirmed,
        )
        self.statusBar().showMessage(f"Sitzung „{self._current_project.name}“ gespeichert.", 5000)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._project_store is not None:
            self._project_store.close()
        super().closeEvent(event)
