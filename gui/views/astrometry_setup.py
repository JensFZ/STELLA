from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class AstrometrySetupDialog(QDialog):
    """Parameter für die Gaia-Abfrage und den WCS-Fit. Wird, falls vorhanden, mit Feldzentrum
    und Pixelmaßstab aus dem FITS-Header des Referenzframes vorbelegt."""

    def __init__(
        self,
        parent: QWidget | None = None,
        prefill: tuple[float, float, float] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Astrometrie berechnen"))

        center_ra, center_dec, pixel_scale = prefill or (0.0, 0.0, 1.0)

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
                        "Pixelmaßstab manuell eingeben."
                    ),
                    self,
                )
            )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def parameters(self) -> dict:
        return {
            "center_ra_deg": self.center_ra_spin.value(),
            "center_dec_deg": self.center_dec_spin.value(),
            "pixel_scale_arcsec": self.pixel_scale_spin.value(),
            "radius_deg": self.radius_spin.value(),
            "mag_limit": self.mag_limit_spin.value(),
            "max_separation_arcsec": self.match_tolerance_spin.value(),
        }
