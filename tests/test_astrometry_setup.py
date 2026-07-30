import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from core.alignment import StarList  # noqa: E402
from core.telescopes import KNOWN_TELESCOPES  # noqa: E402
from gui.views import astrometry_setup as astrometry_setup_module  # noqa: E402
from gui.views.astrometry_setup import AstrometrySetupDialog  # noqa: E402

IMAGE_SHAPE = (256, 256)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stars(count: int) -> StarList:
    rng = np.random.default_rng(0)
    return StarList(
        x=rng.uniform(0, 256, size=count),
        y=rng.uniform(0, 256, size=count),
        flux=rng.uniform(100, 1000, size=count),
    )


class _FakeWorker:
    """Ersetzt PlateSolveWorker: kein echter Thread, kein Netzwerkzugriff im Test."""

    instances: list["_FakeWorker"] = []

    def __init__(self, pixel_x, pixel_y, image_shape, api_key, pixel_scale_arcsec, parent=None):
        self.pixel_x = pixel_x
        self.pixel_y = pixel_y
        self.image_shape = image_shape
        self.api_key = api_key
        self.pixel_scale_arcsec = pixel_scale_arcsec
        self.started = False
        type(self).instances.append(self)

    # Dialog verbindet drei Signale -- als schlichte Attribute mit .connect() genuegt es hier.
    class _Signal:
        def connect(self, *_a, **_kw):
            return None

    status = _Signal()
    finished_solve = _Signal()
    failed = _Signal()

    def start(self):
        self.started = True


@pytest.fixture(autouse=True)
def _reset_fake_worker():
    _FakeWorker.instances = []
    yield


def test_telescope_combo_lists_manual_and_known_telescopes():
    _app()
    dialog = AstrometrySetupDialog(reference_stars=_stars(5), image_shape=IMAGE_SHAPE)

    items = [dialog.telescope_combo.itemText(i) for i in range(dialog.telescope_combo.count())]

    assert items[0] == "— manuell —"
    assert items[1:] == [spec.name for spec in KNOWN_TELESCOPES]


def test_selecting_a_telescope_fills_pixel_scale():
    _app()
    dialog = AstrometrySetupDialog(reference_stars=_stars(5), image_shape=IMAGE_SHAPE)
    seestar_s50_index = 1 + [spec.name for spec in KNOWN_TELESCOPES].index("Seestar S50")

    dialog.telescope_combo.setCurrentIndex(seestar_s50_index)

    expected = next(s for s in KNOWN_TELESCOPES if s.name == "Seestar S50").pixel_scale_arcsec
    # abs statt rel: pixel_scale_spin rundet auf 4 Nachkommastellen (setDecimals(4)).
    assert dialog.pixel_scale_spin.value() == pytest.approx(expected, abs=1e-4)


def test_plate_solve_button_disabled_without_reference_stars():
    _app()
    dialog = AstrometrySetupDialog(reference_stars=None, image_shape=IMAGE_SHAPE)

    assert not dialog.plate_solve_button.isEnabled()


def test_plate_solve_button_disabled_with_too_few_stars():
    """astrometry.net braucht mindestens 4 Sterne fuer ein eindeutiges Muster -- der Button
    soll das nicht erst per Fehlermeldung nach dem Klick mitteilen."""
    _app()
    dialog = AstrometrySetupDialog(reference_stars=_stars(3), image_shape=IMAGE_SHAPE)

    assert not dialog.plate_solve_button.isEnabled()


def test_plate_solve_button_enabled_with_enough_stars():
    _app()
    dialog = AstrometrySetupDialog(reference_stars=_stars(4), image_shape=IMAGE_SHAPE)

    assert dialog.plate_solve_button.isEnabled()


def test_start_plate_solve_without_api_key_does_not_start_worker(monkeypatch):
    _app()
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
    monkeypatch.setattr(astrometry_setup_module, "PlateSolveWorker", _FakeWorker)
    dialog = AstrometrySetupDialog(reference_stars=_stars(5), image_shape=IMAGE_SHAPE)
    dialog.api_key_edit.setText("")

    dialog._start_plate_solve()

    assert dialog._plate_solve_worker is None
    assert _FakeWorker.instances == []


def test_start_plate_solve_with_manual_scale_omits_hint(monkeypatch):
    """Ohne ausgewaehltes Teleskop steht pixel_scale_spin auf einem beliebigen
    Platzhalterwert -- der darf nicht als Massstab-Hinweis an astrometry.net gehen."""
    _app()
    monkeypatch.setattr(astrometry_setup_module, "PlateSolveWorker", _FakeWorker)
    dialog = AstrometrySetupDialog(reference_stars=_stars(5), image_shape=IMAGE_SHAPE)
    dialog.api_key_edit.setText("mein-schluessel")

    dialog._start_plate_solve()

    assert len(_FakeWorker.instances) == 1
    worker = _FakeWorker.instances[0]
    assert worker.api_key == "mein-schluessel"
    assert worker.pixel_scale_arcsec is None
    assert worker.image_shape == IMAGE_SHAPE
    assert worker.started


def test_start_plate_solve_with_selected_telescope_passes_scale_hint(monkeypatch):
    _app()
    monkeypatch.setattr(astrometry_setup_module, "PlateSolveWorker", _FakeWorker)
    dialog = AstrometrySetupDialog(reference_stars=_stars(5), image_shape=IMAGE_SHAPE)
    dialog.api_key_edit.setText("mein-schluessel")
    seestar_s50_index = 1 + [spec.name for spec in KNOWN_TELESCOPES].index("Seestar S50")
    dialog.telescope_combo.setCurrentIndex(seestar_s50_index)

    dialog._start_plate_solve()

    expected = next(s for s in KNOWN_TELESCOPES if s.name == "Seestar S50").pixel_scale_arcsec
    worker = _FakeWorker.instances[0]
    assert worker.pixel_scale_arcsec == pytest.approx(expected)


def test_plate_solve_finished_fills_in_fields():
    _app()
    dialog = AstrometrySetupDialog(reference_stars=_stars(5), image_shape=IMAGE_SHAPE)
    dialog._set_plate_solving_busy(True)

    dialog._on_plate_solve_finished((83.822, -5.391, 2.393))

    assert dialog.center_ra_spin.value() == pytest.approx(83.822)
    assert dialog.center_dec_spin.value() == pytest.approx(-5.391)
    assert dialog.pixel_scale_spin.value() == pytest.approx(2.393)
    assert dialog.plate_solve_button.isEnabled()
    assert dialog.button_box.isEnabled()
