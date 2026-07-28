from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.gpu_tracking import get_device


class SearchSetupDialog(QDialog):
    """Parameter für das Vektor-Gitter (Geschwindigkeit/Winkel) und die GPU-Auswahl."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Kandidaten suchen")

        self.pixel_scale_spin = QDoubleSpinBox(self)
        self.pixel_scale_spin.setRange(0.001, 100.0)
        self.pixel_scale_spin.setDecimals(3)
        self.pixel_scale_spin.setValue(1.0)
        self.pixel_scale_spin.setSuffix(" arcsec/px")

        self.speed_min_spin = QDoubleSpinBox(self)
        self.speed_min_spin.setRange(0.0, 1000.0)
        self.speed_min_spin.setValue(0.0)
        self.speed_min_spin.setSuffix(" arcsec/min")

        self.speed_max_spin = QDoubleSpinBox(self)
        self.speed_max_spin.setRange(0.0, 1000.0)
        self.speed_max_spin.setValue(10.0)
        self.speed_max_spin.setSuffix(" arcsec/min")

        self.speed_step_spin = QDoubleSpinBox(self)
        self.speed_step_spin.setRange(0.01, 100.0)
        self.speed_step_spin.setValue(1.0)
        self.speed_step_spin.setSuffix(" arcsec/min")

        self.angle_step_spin = QDoubleSpinBox(self)
        self.angle_step_spin.setRange(1.0, 180.0)
        self.angle_step_spin.setValue(15.0)
        self.angle_step_spin.setSuffix(" °")

        self.snr_threshold_spin = QDoubleSpinBox(self)
        self.snr_threshold_spin.setRange(1.0, 100.0)
        self.snr_threshold_spin.setValue(5.0)

        self.use_gpu_checkbox = QCheckBox("PyTorch-Batch verwenden (GPU falls verfügbar)", self)
        self.use_gpu_checkbox.setChecked(True)

        form = QFormLayout()
        form.addRow("Pixelmaßstab:", self.pixel_scale_spin)
        form.addRow("Geschwindigkeit von:", self.speed_min_spin)
        form.addRow("Geschwindigkeit bis:", self.speed_max_spin)
        form.addRow("Geschwindigkeit-Schritt:", self.speed_step_spin)
        form.addRow("Winkel-Schritt:", self.angle_step_spin)
        form.addRow("SNR-Schwelle:", self.snr_threshold_spin)
        form.addRow(self.use_gpu_checkbox)
        form.addRow(QLabel(f"Erkanntes Gerät: {get_device()}", self))

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
            "pixel_scale_arcsec": self.pixel_scale_spin.value(),
            "speed_range_arcsec_per_min": (
                self.speed_min_spin.value(),
                self.speed_max_spin.value(),
            ),
            "speed_step_arcsec_per_min": self.speed_step_spin.value(),
            "angle_step_deg": self.angle_step_spin.value(),
            "snr_threshold": self.snr_threshold_spin.value(),
            "use_gpu": self.use_gpu_checkbox.isChecked(),
        }
