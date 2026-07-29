from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.gpu_tracking import get_device
from core.project import ProjectStore
from core.synthetic_tracking import build_velocity_grid

PRESET_KIND = "search"


class SearchSetupDialog(QDialog):
    """Parameter für das Vektor-Gitter (Geschwindigkeit/Winkel) und die GPU-Auswahl.

    Wird ein `project_store` übergeben, können die aktuellen Parameter als benannter Preset
    gespeichert bzw. ein zuvor gespeicherter Preset geladen werden (PLAN.md Phase 7)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        project_store: ProjectStore | None = None,
        frame_count: int = 0,
    ):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Kandidaten suchen"))
        self._project_store = project_store
        self._frame_count = frame_count

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

        self.use_gpu_checkbox = QCheckBox(
            self.tr("PyTorch-Batch verwenden (GPU falls verfügbar)"), self
        )
        self.use_gpu_checkbox.setChecked(True)

        form = QFormLayout()
        form.addRow(self.tr("Pixelmaßstab:"), self.pixel_scale_spin)
        form.addRow(self.tr("Geschwindigkeit von:"), self.speed_min_spin)
        form.addRow(self.tr("Geschwindigkeit bis:"), self.speed_max_spin)
        form.addRow(self.tr("Geschwindigkeit-Schritt:"), self.speed_step_spin)
        form.addRow(self.tr("Winkel-Schritt:"), self.angle_step_spin)
        form.addRow(self.tr("SNR-Schwelle:"), self.snr_threshold_spin)
        form.addRow(self.use_gpu_checkbox)
        form.addRow(QLabel(f"Erkanntes Gerät: {get_device()}", self))

        # Qt beschriftet die Standardknöpfe nach Systemsprache; auf einem englischen
        # Windows stünde "Cancel" neben ansonsten deutscher Oberfläche.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr("Suche starten"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(self.tr("Abbrechen"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # Aufwandsabschätzung: das Gitter wächst multiplikativ mit den Parametern, eine
        # unbedacht feine Einstellung kann die Suche von Minuten auf Stunden verlängern.
        self.cost_label = QLabel("", self)
        self.cost_label.setStyleSheet("color: #9a9a9a;")
        for widget in (
            self.speed_min_spin,
            self.speed_max_spin,
            self.speed_step_spin,
            self.angle_step_spin,
        ):
            widget.valueChanged.connect(self._update_cost)
        self._update_cost()

        layout = QVBoxLayout(self)
        if project_store is not None:
            layout.addLayout(self._build_preset_bar())
        layout.addLayout(form)
        layout.addWidget(self.cost_label)
        layout.addWidget(buttons)

    def vector_count(self) -> int:
        """Anzahl Vektoren, die das eingestellte Gitter ergibt."""
        return len(
            build_velocity_grid(
                speed_range_arcsec_per_min=(
                    self.speed_min_spin.value(),
                    self.speed_max_spin.value(),
                ),
                speed_step_arcsec_per_min=self.speed_step_spin.value(),
                angle_step_deg=self.angle_step_spin.value(),
            )
        )

    def _update_cost(self) -> None:
        count = self.vector_count()
        text = f"Suchraum: {count} Bewegungsvektoren"
        if self._frame_count:
            text += f" × {self._frame_count} Frames"
        self.cost_label.setText(text)

    def _build_preset_bar(self) -> QHBoxLayout:
        self.preset_combo = QComboBox(self)
        self._reload_presets()

        load_button = QPushButton(self.tr("Laden"), self)
        load_button.clicked.connect(self._load_selected_preset)
        save_button = QPushButton(self.tr("Speichern als..."), self)
        save_button.clicked.connect(self._save_as_preset)

        bar = QHBoxLayout()
        bar.addWidget(QLabel(self.tr("Preset:"), self))
        bar.addWidget(self.preset_combo, stretch=1)
        bar.addWidget(load_button)
        bar.addWidget(save_button)
        return bar

    def _reload_presets(self) -> None:
        self.preset_combo.clear()
        for preset in self._project_store.list_presets(PRESET_KIND):
            self.preset_combo.addItem(preset.name, preset.params)

    def _load_selected_preset(self) -> None:
        params = self.preset_combo.currentData()
        if params is None:
            return
        self.pixel_scale_spin.setValue(params["pixel_scale_arcsec"])
        speed_low, speed_high = params["speed_range_arcsec_per_min"]
        self.speed_min_spin.setValue(speed_low)
        self.speed_max_spin.setValue(speed_high)
        self.speed_step_spin.setValue(params["speed_step_arcsec_per_min"])
        self.angle_step_spin.setValue(params["angle_step_deg"])
        self.snr_threshold_spin.setValue(params["snr_threshold"])
        self.use_gpu_checkbox.setChecked(params["use_gpu"])

    def _save_as_preset(self) -> None:
        name, ok = QInputDialog.getText(self, self.tr("Preset speichern"), self.tr("Name:"))
        if not ok or not name.strip():
            return
        self._project_store.save_preset(name.strip(), PRESET_KIND, self.parameters())
        self._reload_presets()
        self.preset_combo.setCurrentText(name.strip())
        QMessageBox.information(
            self,
            self.tr("Preset gespeichert"),
            self.tr('Preset "{name}" gespeichert.').format(name=name.strip()),
        )

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
