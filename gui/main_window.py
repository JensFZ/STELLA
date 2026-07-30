import logging
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from core.alignment import RegisteredStack
from core.astrometry import AstrometricSolution, estimate_field_center_and_scale, pixel_to_sky
from core.detection import DetectionResult
from core.i18n import SUPPORTED_LANGUAGES, current_language, save_language
from core.io_fits import FolderScan, FrameStack, group_into_sessions
from core.logging_setup import log_file_path
from core.mpc_report import MPCObservation, write_mpc_report
from core.project import Project, ProjectStore
from core.settings import settings
from core.synthetic_tracking import candidate_positions_per_frame
from core.telescopes import KNOWN_TELESCOPES
from gui.views.astrometry_panel import AstrometryPanel
from gui.views.astrometry_setup import AstrometrySetupDialog
from gui.views.empty_state import EmptyState
from gui.views.image_viewer import ImageViewer
from gui.views.progress_panel import ProgressPanel
from gui.views.project_dialog import OpenProjectDialog
from gui.views.results_table import ResultsTable
from gui.views.search_setup import PRESET_KIND, SearchSetupDialog, default_parameters
from gui.views.session_dialog import SessionSelectDialog
from gui.views.workflow_panel import StepState, WorkflowPanel
from gui.workers import (
    AlignmentWorker,
    AstrometryWorker,
    DetectionWorker,
    FolderScanWorker,
    FrameStackLoader,
)

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STELLA")
        self.resize(1200, 800)

        self._scan_worker: FolderScanWorker | None = None
        self._loader: FrameStackLoader | None = None
        self._alignment_worker: AlignmentWorker | None = None
        self._detection_worker: DetectionWorker | None = None
        self._astrometry_worker: AstrometryWorker | None = None
        self._stack: FrameStack | None = None
        self._registered: RegisteredStack | None = None
        self._astrometric_solution: AstrometricSolution | None = None
        self._search_pixel_scale_arcsec: float | None = None
        self._header_pixel_scale_arcsec: float | None = None
        self._project_store: ProjectStore | None = None
        self._current_project: Project | None = None
        self._restore_project_on_load: Project | None = None
        # Zentralbereich: solange nichts geladen ist, der Einstiegsbildschirm statt einer
        # leeren schwarzen Fläche.
        self.image_viewer = ImageViewer(self)
        self.empty_state = EmptyState(self)
        self.empty_state.open_folder_requested.connect(self._open_fits_folder)
        self.central_stack = QStackedWidget(self)
        self.central_stack.addWidget(self.empty_state)
        self.central_stack.addWidget(self.image_viewer)

        self.workflow_panel = WorkflowPanel(self)
        self.workflow_panel.step_activated.connect(self._on_workflow_step)

        central = QWidget(self)
        central_layout = QHBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.workflow_panel)
        central_layout.addWidget(self.central_stack, stretch=1)
        self.setCentralWidget(central)

        self.progress_panel = ProgressPanel(self)
        self.progress_panel.cancel_requested.connect(self._cancel_detection)
        self.statusBar().addPermanentWidget(self.progress_panel, 1)

        self.results_table = ResultsTable(self)
        self.results_table.confirmation_changed.connect(self._update_export_step)
        self.results_dock = QDockWidget(self.tr("Kandidaten"), self)
        # Ein Objektname ist Voraussetzung dafür, dass Qt die Anordnung speichern und
        # wiederherstellen kann.
        self.results_dock.setObjectName("results_dock")
        self.results_dock.setWidget(self.results_table)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.results_dock)
        self.results_dock.hide()

        self.astrometry_panel = AstrometryPanel(self)
        self.astrometry_dock = QDockWidget(self.tr("Astrometrie"), self)
        self.astrometry_dock.setObjectName("astrometry_dock")
        self.astrometry_dock.setWidget(self.astrometry_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.astrometry_dock)
        self.astrometry_dock.hide()

        self._build_menu()
        self._apply_default_layout()
        self._restore_layout()

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu(self.tr("&Datei"))
        open_action = QAction(self.tr("FITS-Ordner öffnen..."), self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self._open_fits_folder)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        exit_action = QAction(self.tr("Beenden"), self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        project_menu = menu_bar.addMenu(self.tr("&Projekt"))
        new_project_action = QAction(self.tr("Neues Projekt..."), self)
        new_project_action.triggered.connect(self._new_project)
        project_menu.addAction(new_project_action)

        open_project_action = QAction(self.tr("Projekt öffnen..."), self)
        open_project_action.triggered.connect(self._open_project)
        project_menu.addAction(open_project_action)

        self.save_session_action = QAction(self.tr("Sitzung speichern"), self)
        self.save_session_action.setEnabled(False)
        self.save_session_action.triggered.connect(self._save_session)
        project_menu.addAction(self.save_session_action)
        project_menu.addSeparator()
        self.align_action = QAction(self.tr("Sterne erkennen && ausrichten..."), self)
        self.align_action.setEnabled(False)
        self.align_action.triggered.connect(self._run_alignment)
        project_menu.addAction(self.align_action)

        self.detect_action = QAction(self.tr("Kandidaten suchen..."), self)
        self.detect_action.setEnabled(False)
        self.detect_action.triggered.connect(self._open_search_setup)
        project_menu.addAction(self.detect_action)

        project_menu.addSeparator()
        self.astrometry_action = QAction(self.tr("Astrometrie berechnen..."), self)
        self.astrometry_action.setEnabled(False)
        self.astrometry_action.triggered.connect(self._open_astrometry_setup)
        project_menu.addAction(self.astrometry_action)

        self.export_mpc_action = QAction(self.tr("MPC-Report exportieren..."), self)
        self.export_mpc_action.setEnabled(False)
        self.export_mpc_action.triggered.connect(self._export_mpc_report)
        project_menu.addAction(self.export_mpc_action)

        view_menu = menu_bar.addMenu(self.tr("&Ansicht"))
        view_menu.addAction(self.results_dock.toggleViewAction())
        view_menu.addAction(self.astrometry_dock.toggleViewAction())
        view_menu.addSeparator()
        reset_layout_action = QAction(self.tr("Anordnung zurücksetzen"), self)
        reset_layout_action.triggered.connect(self._reset_layout)
        view_menu.addAction(reset_layout_action)

        language_menu = menu_bar.addMenu(self.tr("&Sprache"))
        language_group = QActionGroup(self)
        language_group.setExclusive(True)
        for code, name in SUPPORTED_LANGUAGES.items():
            action = QAction(name, self)
            action.setCheckable(True)
            action.setChecked(code == current_language())
            action.triggered.connect(lambda _checked, c=code: self._change_language(c))
            language_group.addAction(action)
            language_menu.addAction(action)

        help_menu = menu_bar.addMenu(self.tr("&Hilfe"))
        show_log_action = QAction(self.tr("Logdatei anzeigen"), self)
        show_log_action.triggered.connect(self._show_log_file)
        help_menu.addAction(show_log_action)
        help_menu.addSeparator()
        about_action = QAction(self.tr("Über STELLA"), self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _change_language(self, language: str) -> None:
        """Speichert die Sprachwahl und bittet um einen Neustart.

        Ein Wechsel im laufenden Programm würde erfordern, dass jedes Fenster und jeder
        Dialog seine Beschriftungen neu setzt. Der Neustart ist hier der ehrlichere Weg —
        er lässt keine halb übersetzte Oberfläche zurück.
        """
        if language == current_language():
            return
        save_language(language)
        logger.info("Sprache gewechselt auf %s (wirksam nach Neustart)", language)
        QMessageBox.information(
            self,
            self.tr("Sprache geändert"),
            self.tr(
                "Die Sprache wird beim nächsten Start von STELLA verwendet."
            ),
        )

    def _show_log_file(self) -> None:
        """Öffnet den Ordner mit der Logdatei im Dateimanager. Bewusst der Ordner und nicht
        die Datei selbst: so sind auch die rotierten älteren Logs greifbar, und es braucht
        keine Annahme darüber, womit .log-Dateien geöffnet werden."""
        path = log_file_path()
        if not path.exists():
            QMessageBox.information(
                self,
                self.tr("Logdatei"),
                self.tr("Noch keine Logdatei vorhanden.\nErwartet unter:\n{path}").format(
                    path=path
                ),
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
            QMessageBox.information(
                self,
                self.tr("Logdatei"),
                self.tr("Die Logdatei liegt unter:\n{path}").format(path=path),
            )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            self.tr("Über STELLA"),
            self.tr(
                "STELLA — Synthetic Tracking Engine for Locating & Logging Asteroids\n"
                "Open-Source Synthetic-Tracking-Tool für Asteroiden-Detektion."
            ),
        )

    def _apply_default_layout(self) -> None:
        """Startaufteilung: das Bild ist der Hauptinhalt und bekommt den Raum.

        Die beiden Panels zeigen Begleitinformationen — die Astrometrie eine Zahlenliste,
        die Kandidaten eine Auswahlliste. Beide bekommen daher nur so viel Platz, wie sie
        zum Lesen brauchen, statt wie zuvor über ein Drittel des Fensters.
        """
        self.resizeDocks([self.astrometry_dock], [280], Qt.Orientation.Horizontal)
        self.resizeDocks([self.results_dock], [240], Qt.Orientation.Vertical)

    def _restore_layout(self) -> None:
        """Stellt Fenstergröße und Anordnung des letzten Laufs wieder her.

        Wichtiger als jede von mir gewählte Startaufteilung: welche Verteilung sinnvoll ist,
        hängt von Bildformat, Bildschirm und Arbeitsweise ab. Wer einmal angepasst hat, soll
        das nicht bei jedem Start wiederholen müssen.
        """
        stored = settings()
        geometry = stored.value("window/geometry")
        state = stored.value("window/state")
        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)

    def _save_layout(self) -> None:
        stored = settings()
        stored.setValue("window/geometry", self.saveGeometry())
        stored.setValue("window/state", self.saveState())

    def _reset_layout(self) -> None:
        """Verwirft die gespeicherte Anordnung und stellt die Startaufteilung wieder her."""
        stored = settings()
        stored.remove("window/geometry")
        stored.remove("window/state")
        self.resize(1200, 800)
        self._apply_default_layout()
        self.image_viewer.reset_layout()
        logger.info("Fensteranordnung zurückgesetzt")

    def _update_export_step(self) -> None:
        """Der Export braucht beides: eine WCS-Lösung und mindestens einen bestätigten
        Kandidaten. Solange eines fehlt, zeigt die Schrittleiste, was noch aussteht."""
        confirmed = sum(1 for d in self.results_table.detections() if d.confirmed is True)
        has_solution = self._astrometric_solution is not None

        if has_solution and confirmed:
            self.workflow_panel.set_state(
                WorkflowPanel.STEP_EXPORT,
                StepState.AVAILABLE,
                f"{confirmed} bestätigt",
            )
            return

        missing = []
        if not has_solution:
            missing.append(self.tr("Astrometrie"))
        if not confirmed:
            missing.append(self.tr("bestätigte Kandidaten"))
        self.workflow_panel.set_state(
            WorkflowPanel.STEP_EXPORT,
            StepState.LOCKED,
            self.tr("fehlt: {what}").format(what=self.tr(" und ").join(missing)),
        )

    def _on_workflow_step(self, step: int) -> None:
        """Schrittleiste und Menü lösen dieselben Aktionen aus."""
        handlers = {
            WorkflowPanel.STEP_LOAD: self._open_fits_folder,
            WorkflowPanel.STEP_ALIGN: self._run_alignment,
            WorkflowPanel.STEP_DETECT: self._open_search_setup,
            WorkflowPanel.STEP_ASTROMETRY: self._open_astrometry_setup,
            WorkflowPanel.STEP_EXPORT: self._export_mpc_report,
        }
        handlers[step]()

    def _open_fits_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("FITS-Ordner öffnen"))
        if not folder:
            return
        self._load_folder(folder)

    def _debayer_setting(self) -> bool:
        """Zuletzt gewählte Einstellung für die Bayer-Mittelung; standardmäßig aktiv."""
        value = settings().value("load/debayer", True)
        return value if isinstance(value, bool) else str(value).lower() in ("true", "1")

    def _load_folder(self, folder: str) -> None:
        """Ordner einlesen — zunächst nur die Header, damit die Serienauswahl möglich ist,
        bevor Gigabytes an Bilddaten gelesen werden."""
        self._scan_worker = FolderScanWorker(
            folder, debayer=self._debayer_setting(), parent=self
        )
        self._scan_worker.finished_scan.connect(self._on_scan_finished)
        self._scan_worker.failed.connect(self._on_load_failed)
        self.progress_panel.start(self.tr("Ordner analysieren"))
        self._scan_worker.start()

    def _on_scan_finished(self, scan: FolderScan) -> None:
        self.progress_panel.finish()

        session_index = None
        debayer = self._debayer_setting()
        sessions = group_into_sessions(scan.for_shape(scan.dominant_shape()))

        # Der Dialog erscheint auch bei nur einer Serie, sobald Bayer-Daten vorliegen: die
        # Mittelung verändert Auflösung und Pixelmaßstab, das soll niemand unbemerkt
        # geschehen.
        if len(sessions) > 1 or scan.bayer_patterns():
            dialog = SessionSelectDialog(scan, parent=self, debayer=debayer)
            if dialog.exec() != SessionSelectDialog.DialogCode.Accepted:
                self.statusBar().showMessage(self.tr("Laden abgebrochen."), 5000)
                return
            session_index = dialog.selected_session_index()
            chosen_debayer = dialog.debayer_enabled()

            if chosen_debayer != debayer:
                # Die Bildgrößen im Scan hängen von dieser Entscheidung ab — bei einer
                # Änderung muss der Ordner erneut analysiert werden.
                settings().setValue("load/debayer", chosen_debayer)
                logger.info("Bayer-Mittelung umgestellt auf %s — analysiere erneut", chosen_debayer)
                self._load_folder(str(scan.folder))
                return

        # Rohaufnahmen enthalten oft kein WCS; der aus Pixelgröße und Brennweite berechnete
        # Maßstab ist dann die einzige belastbare Vorgabe für Suche und Astrometrie.
        self._header_pixel_scale_arcsec = scan.pixel_scale_arcsec()

        self._loader = FrameStackLoader(
            scan, session_index=session_index, debayer=debayer, parent=self
        )
        self._loader.status.connect(self.progress_panel.set_label)
        self._loader.progress.connect(self.progress_panel.set_progress)
        self._loader.finished_loading.connect(self._on_load_finished)
        self._loader.failed.connect(self._on_load_failed)
        self.progress_panel.start(self.tr("FITS-Frames laden"))
        self._loader.start()

    def _on_load_finished(self, stack: FrameStack) -> None:
        self.progress_panel.finish()
        self._stack = stack
        # Erst umschalten, dann befüllen: als verdeckte Seite des Stapels hat der Viewer
        # noch keine sinnvolle Größe, und das Einpassen des Bildes würde danebengreifen.
        self.central_stack.setCurrentWidget(self.image_viewer)
        self.image_viewer.set_stack(stack)
        self.align_action.setEnabled(len(stack) > 1)
        self.statusBar().showMessage(f"{len(stack)} Frames geladen.", 5000)

        # Ein neuer Stapel entwertet alle späteren Ergebnisse.
        self._registered = None
        self._astrometric_solution = None
        self.detect_action.setEnabled(False)
        self.astrometry_action.setEnabled(False)
        self.export_mpc_action.setEnabled(False)
        self.workflow_panel.reset_from(WorkflowPanel.STEP_ALIGN)

        start = (stack[0].obs_time or "")[11:16]
        detail = f"{len(stack)} Frames"
        if start:
            detail += f" ab {start} Uhr"
        self.workflow_panel.set_state(WorkflowPanel.STEP_LOAD, StepState.DONE, detail)
        if len(stack) > 1:
            self.workflow_panel.set_state(WorkflowPanel.STEP_ALIGN, StepState.AVAILABLE)

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
        QMessageBox.critical(self, self.tr("Fehler beim Laden"), message)

    def _run_alignment(self) -> None:
        if self._stack is None:
            return
        self._alignment_worker = AlignmentWorker(self._stack, reference_index=0, parent=self)
        self._alignment_worker.progress.connect(self.progress_panel.set_progress)
        self._alignment_worker.finished_alignment.connect(self._on_align_finished)
        self._alignment_worker.failed.connect(self._on_align_failed)
        self.progress_panel.start(self.tr("Sterne erkennen und ausrichten"))
        self.align_action.setEnabled(False)
        self._alignment_worker.start()

    def _on_align_finished(self, registered: RegisteredStack) -> None:
        self.progress_panel.finish()
        self._registered = registered
        self.image_viewer.set_registered_stack(registered)
        self.align_action.setEnabled(True)
        self.detect_action.setEnabled(True)
        self.astrometry_action.setEnabled(True)
        self.statusBar().showMessage(self.tr("Ausrichtung abgeschlossen."), 5000)

        stars = len(registered[registered.reference_index].stars)
        max_shift = max(
            max(abs(f.alignment.dx), abs(f.alignment.dy)) for f in registered.frames
        )
        self.workflow_panel.set_state(
            WorkflowPanel.STEP_ALIGN,
            StepState.DONE,
            f"{stars} Sterne, max. Drift {max_shift:.1f} px",
        )
        self.workflow_panel.set_state(WorkflowPanel.STEP_DETECT, StepState.AVAILABLE)
        self.workflow_panel.set_state(WorkflowPanel.STEP_ASTROMETRY, StepState.AVAILABLE)

    def _on_align_failed(self, message: str) -> None:
        self.progress_panel.finish()
        self.align_action.setEnabled(True)
        self.statusBar().clearMessage()
        QMessageBox.critical(self, self.tr("Fehler bei der Ausrichtung"), message)

    def _open_search_setup(self) -> None:
        if self._stack is None or self._registered is None:
            return
        dialog = SearchSetupDialog(
            self,
            project_store=self._get_project_store(),
            frame_count=len(self._stack),
            pixel_scale_arcsec=self._header_pixel_scale_arcsec,
        )
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
        self.progress_panel.start(self.tr("Kandidatensuche"), cancellable=True)
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
            self.statusBar().showMessage(self.tr("Keine Kandidaten gefunden."), 5000)
            self.workflow_panel.set_state(
                WorkflowPanel.STEP_DETECT, StepState.AVAILABLE, self.tr("keine Kandidaten")
            )
            return
        self.results_table.set_detections(detections)
        self.results_dock.show()
        self.statusBar().showMessage(f"{len(detections)} Kandidat(en) gefunden.", 5000)
        self.workflow_panel.set_state(
            WorkflowPanel.STEP_DETECT, StepState.DONE, f"{len(detections)} Kandidaten"
        )
        self._update_export_step()

    def _on_detect_failed(self, message: str) -> None:
        self.progress_panel.finish()
        self.detect_action.setEnabled(True)
        self.statusBar().clearMessage()
        QMessageBox.critical(self, self.tr("Fehler bei der Kandidatensuche"), message)

    def _open_astrometry_setup(self) -> None:
        if self._registered is None:
            return
        reference_index = self._registered.reference_index
        reference_frame = self._registered[reference_index].frame
        prefill = estimate_field_center_and_scale(reference_frame.wcs, reference_frame.data.shape)

        dialog = AstrometrySetupDialog(
            self,
            prefill=prefill,
            reference_stars=self._registered[reference_index].stars,
            image_shape=reference_frame.data.shape,
        )
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
        self.progress_panel.start(self.tr("Astrometrie berechnen"))
        self._astrometry_worker.start()

    def _on_astrometry_finished(self, solution: AstrometricSolution) -> None:
        self.progress_panel.finish()
        self._astrometric_solution = solution
        self.astrometry_action.setEnabled(True)
        self.export_mpc_action.setEnabled(True)
        self.astrometry_panel.set_solution(solution)
        self.astrometry_dock.show()
        self.workflow_panel.set_state(
            WorkflowPanel.STEP_ASTROMETRY,
            StepState.DONE,
            f"{solution.n_matches} Gaia-Matches, RMS {solution.rms_residual_arcsec:.3f}″",
        )
        self._update_export_step()
        self.statusBar().showMessage(
            f"Astrometrie: {solution.n_matches} Gaia-Matches, "
            f"RMS-Residuum {solution.rms_residual_arcsec:.3f}\"",
            8000,
        )

    def _on_astrometry_failed(self, message: str) -> None:
        self.progress_panel.finish()
        self.astrometry_action.setEnabled(True)
        self.statusBar().clearMessage()
        QMessageBox.critical(self, self.tr("Fehler bei der Astrometrie"), message)

    def _export_mpc_report(self) -> None:
        if self._astrometric_solution is None or self._registered is None:
            return
        confirmed = [d for d in self.results_table.detections() if d.confirmed is True]
        if not confirmed:
            QMessageBox.warning(
                self,
                self.tr("Keine bestätigten Kandidaten"),
                "Bitte zunächst mindestens einen Kandidaten in der Tabelle als "
                '"Bestätigt" markieren.',
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self, self.tr("MPC-Report speichern"), "report.txt", self.tr("Textdateien (*.txt)")
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
            self._seed_builtin_presets_once()
        return self._project_store

    def _seed_builtin_presets_once(self) -> None:
        """Legt Suchparameter-Presets für bekannte Teleskope einmalig an.

        Nur beim allerersten Aufruf, markiert über QSettings: sonst würde ein von der
        Nutzerin gelöschtes oder umbenanntes Preset bei jedem Neustart wieder auftauchen.
        seed_presets() selbst überschreibt nichts — die Absicherung hier verhindert
        zusätzlich, dass es überhaupt erneut aufgerufen wird.
        """
        seeded_key = "presets/builtin_telescopes_seeded"
        if settings().value(seeded_key, False, type=bool):
            return
        self._project_store.seed_presets(
            PRESET_KIND,
            {spec.name: default_parameters(spec.pixel_scale_arcsec) for spec in KNOWN_TELESCOPES},
        )
        settings().setValue(seeded_key, True)

    def _new_project(self) -> None:
        name, ok = QInputDialog.getText(self, self.tr("Neues Projekt"), self.tr("Projektname:"))
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
        self._save_layout()
        if self._project_store is not None:
            self._project_store.close()
        super().closeEvent(event)
