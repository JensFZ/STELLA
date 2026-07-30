from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.alignment import StarList
from core.plate_solving import save_api_key, saved_api_key
from core.telescopes import KNOWN_TELESCOPES
from gui.workers import PlateSolveWorker


class AstrometrySetupDialog(QDialog):
    """Parameter für die Gaia-Abfrage und den WCS-Fit. Wird, falls vorhanden, mit Feldzentrum
    und Pixelmaßstab aus dem FITS-Header des Referenzframes vorbelegt.

    Fehlt ein Header-WCS, ließ sich das Feldzentrum bisher nur von Hand schätzen — die
    einzige Angabe, die nicht aus einem Teleskop-Datenblatt folgt, sondern von der
    tatsächlichen Zeigerichtung in dieser Nacht abhängt. Plate Solving (astrometry.net)
    bestimmt es stattdessen blind aus dem erkannten Sternmuster."""

    def __init__(
        self,
        parent: QWidget | None = None,
        prefill: tuple[float, float, float] | None = None,
        reference_stars: StarList | None = None,
        image_shape: tuple[int, int] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Astrometrie berechnen"))
        self._reference_stars = reference_stars
        self._image_shape = image_shape
        #: Muss am Dialog hängen bleiben, sonst reißt Python den QThread mitten im Lauf ab.
        self._plate_solve_worker: PlateSolveWorker | None = None

        center_ra, center_dec, pixel_scale = prefill or (0.0, 0.0, 1.0)

        # Nur der Pixelmaßstab ist geräteabhängig — Feldzentrum ist die tatsächliche
        # Zeigerichtung dieser Nacht und kann nie aus einem Gerätepreset kommen.
        self.telescope_combo = QComboBox(self)
        self.telescope_combo.addItem(self.tr("— manuell —"), None)
        for spec in KNOWN_TELESCOPES:
            self.telescope_combo.addItem(spec.name, spec.pixel_scale_arcsec)
        self.telescope_combo.currentIndexChanged.connect(self._apply_telescope_pixel_scale)

        self.center_ra_spin = QDoubleSpinBox(self)
        self.center_ra_spin.setRange(0.0, 360.0)
        self.center_ra_spin.setDecimals(5)
        self.center_ra_spin.setValue(center_ra)
        self.center_ra_spin.setSuffix(" °")

        self.center_dec_spin = QDoubleSpinBox(self)
        self.center_dec_spin.setRange(-90.0, 90.0)
        self.center_dec_spin.setDecimals(5)
        self.center_dec_spin.setValue(center_dec)
        self.center_dec_spin.setSuffix(" °")

        self.pixel_scale_spin = QDoubleSpinBox(self)
        self.pixel_scale_spin.setRange(0.001, 100.0)
        self.pixel_scale_spin.setDecimals(4)
        self.pixel_scale_spin.setValue(pixel_scale)
        self.pixel_scale_spin.setSuffix(" arcsec/px")

        self.radius_spin = QDoubleSpinBox(self)
        self.radius_spin.setRange(0.001, 5.0)
        self.radius_spin.setDecimals(3)
        self.radius_spin.setValue(0.2)
        self.radius_spin.setSuffix(" °")

        self.mag_limit_spin = QDoubleSpinBox(self)
        self.mag_limit_spin.setRange(1.0, 21.0)
        self.mag_limit_spin.setValue(18.0)

        self.match_tolerance_spin = QDoubleSpinBox(self)
        self.match_tolerance_spin.setRange(0.1, 60.0)
        self.match_tolerance_spin.setValue(3.0)
        self.match_tolerance_spin.setSuffix(" arcsec")

        form = QFormLayout()
        form.addRow(self.tr("Teleskop:"), self.telescope_combo)
        form.addRow(self.tr("Feldzentrum RA:"), self.center_ra_spin)
        form.addRow(self.tr("Feldzentrum Dec:"), self.center_dec_spin)
        form.addRow(self.tr("Pixelmaßstab:"), self.pixel_scale_spin)
        form.addRow(self.tr("Suchradius:"), self.radius_spin)
        form.addRow(self.tr("Grenzmagnitude (Gaia G):"), self.mag_limit_spin)
        form.addRow(self.tr("Match-Toleranz:"), self.match_tolerance_spin)
        if prefill is None:
            form.addRow(
                QLabel(
                    self.tr(
                        "Kein WCS im FITS-Header gefunden — bitte Feldzentrum und\n"
                        "Pixelmaßstab manuell eingeben oder unten per Plate Solving bestimmen."
                    ),
                    self,
                )
            )

        plate_solve_heading = QLabel(self.tr("Plate Solving (astrometry.net)"), self)
        plate_solve_heading.setStyleSheet("font-weight: 600; margin-top: 6px;")

        self.api_key_edit = QLineEdit(self)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setText(saved_api_key())
        self.api_key_edit.setPlaceholderText(
            self.tr("API-Schlüssel — kostenlos unter nova.astrometry.net/api_help")
        )

        self.plate_solve_button = QPushButton(
            self.tr("Feldzentrum automatisch bestimmen"), self
        )
        # Ohne erkannte Sterne oder Bildgröße (z.B. Dialog ohne main_window-Kontext in
        # Tests) gibt es nichts zu lösen.
        self.plate_solve_button.setEnabled(
            bool(reference_stars) and len(reference_stars) >= 4 and image_shape is not None
        )
        self.plate_solve_button.clicked.connect(self._start_plate_solve)

        self.plate_solve_progress = QProgressBar(self)
        self.plate_solve_progress.setRange(0, 0)  # unbestimmt: Dauer eines Netzwerk-Solves
        self.plate_solve_progress.setTextVisible(False)
        self.plate_solve_progress.setFixedHeight(self.plate_solve_button.sizeHint().height())
        self.plate_solve_progress.hide()

        self.plate_solve_status = QLabel("", self)
        self.plate_solve_status.setWordWrap(True)
        self.plate_solve_status.setStyleSheet("color: #9a9a9a; font-size: 11px;")

        plate_solve_row = QHBoxLayout()
        plate_solve_row.addWidget(self.plate_solve_button)
        plate_solve_row.addWidget(self.plate_solve_progress, 1)

        # Qt beschriftet die Standardknöpfe nach Systemsprache; auf einem englischen
        # Windows stünde "Cancel" neben ansonsten deutscher Oberfläche.
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(plate_solve_heading)
        layout.addWidget(self.api_key_edit)
        layout.addLayout(plate_solve_row)
        layout.addWidget(self.plate_solve_status)
        layout.addWidget(self.button_box)

    def _apply_telescope_pixel_scale(self, index: int) -> None:
        pixel_scale = self.telescope_combo.itemData(index)
        if pixel_scale is not None:
            self.pixel_scale_spin.setValue(pixel_scale)

    def _start_plate_solve(self) -> None:
        api_key = self.api_key_edit.text().strip()
        if not api_key:
            QMessageBox.warning(
                self,
                self.tr("Kein API-Schlüssel"),
                self.tr(
                    "Für Plate Solving wird ein kostenloser API-Schlüssel von "
                    "nova.astrometry.net benötigt."
                ),
            )
            return
        save_api_key(api_key)

        # Nur bei ausgewähltem Teleskop als Hinweis mitgeben: der Pixelmaßstab-Spinner steht
        # sonst auf einem beliebigen Platzhalterwert (0.001–100, Default 1.0), der die blinde
        # Suche eher in die Irre führen als beschleunigen würde.
        telescope_pixel_scale = self.telescope_combo.currentData()

        self._plate_solve_worker = PlateSolveWorker(
            self._reference_stars.x,
            self._reference_stars.y,
            self._image_shape,
            api_key,
            pixel_scale_arcsec=telescope_pixel_scale,
            parent=self,
        )
        self._plate_solve_worker.status.connect(self.plate_solve_status.setText)
        self._plate_solve_worker.finished_solve.connect(self._on_plate_solve_finished)
        self._plate_solve_worker.failed.connect(self._on_plate_solve_failed)
        self._set_plate_solving_busy(True)
        self._plate_solve_worker.start()

    def _set_plate_solving_busy(self, busy: bool) -> None:
        self.plate_solve_button.setEnabled(not busy)
        self.plate_solve_progress.setVisible(busy)
        # Der Dialog bleibt während des Solvens geschlossen, nicht nur die Eingaben: der
        # QThread hängt am Dialog (parent=self) und würde beim Schließen mitten im
        # Netzwerk-Roundtrip zerstört, was Qt zu Recht mit einer Warnung quittiert.
        self.button_box.setEnabled(not busy)
        for widget in (
            self.telescope_combo,
            self.center_ra_spin,
            self.center_dec_spin,
            self.pixel_scale_spin,
            self.api_key_edit,
        ):
            widget.setEnabled(not busy)

    def _on_plate_solve_finished(self, result: tuple) -> None:
        self._set_plate_solving_busy(False)
        ra_deg, dec_deg, pixel_scale_arcsec = result
        self.center_ra_spin.setValue(ra_deg)
        self.center_dec_spin.setValue(dec_deg)
        self.pixel_scale_spin.setValue(pixel_scale_arcsec)
        self.plate_solve_status.setText(
            self.tr("Gelöst: RA {ra:.5f}°, Dec {dec:.5f}°, {scale:.3f}″/px").format(
                ra=ra_deg, dec=dec_deg, scale=pixel_scale_arcsec
            )
        )

    def _on_plate_solve_failed(self, message: str) -> None:
        self._set_plate_solving_busy(False)
        self.plate_solve_status.setText("")
        QMessageBox.critical(self, self.tr("Plate Solving fehlgeschlagen"), message)

    def parameters(self) -> dict:
        return {
            "center_ra_deg": self.center_ra_spin.value(),
            "center_dec_deg": self.center_dec_spin.value(),
            "pixel_scale_arcsec": self.pixel_scale_spin.value(),
            "radius_deg": self.radius_spin.value(),
            "mag_limit": self.mag_limit_spin.value(),
            "max_separation_arcsec": self.match_tolerance_spin.value(),
        }
