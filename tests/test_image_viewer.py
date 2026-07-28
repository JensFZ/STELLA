import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from astropy.io import fits
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.alignment import register_stack  # noqa: E402
from core.io_fits import load_frame_stack  # noqa: E402
from gui.views.image_viewer import ImageViewer  # noqa: E402


def _write_fits(path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    data = rng.normal(loc=100.0, scale=10.0, size=(32, 32)).astype(np.float32)
    fits.writeto(path, data, overwrite=True)


def _write_star_field_fits(
    path, star_positions: list[tuple[float, float]], size: int = 128
) -> None:
    y, x = np.mgrid[0:size, 0:size]
    rng = np.random.default_rng(0)
    data = np.full((size, size), 50.0, dtype=np.float64) + rng.normal(scale=1.0, size=(size, size))
    for star_x, star_y in star_positions:
        data += 2000.0 * np.exp(-(((x - star_x) ** 2 + (y - star_y) ** 2) / (2 * 2.0**2)))
    fits.writeto(path, data.astype(np.float32), overwrite=True)


def test_image_viewer_loads_stack_and_navigates(tmp_path):
    _app = QApplication.instance() or QApplication([])
    _write_fits(tmp_path / "a.fits", 1)
    _write_fits(tmp_path / "b.fits", 2)
    _write_fits(tmp_path / "c.fits", 3)
    stack = load_frame_stack(tmp_path)

    viewer = ImageViewer()
    viewer.set_stack(stack)

    assert viewer.thumbnail_list.count() == 3
    assert viewer.frame_slider.maximum() == 2
    assert "1 / 3" in viewer.frame_label.text()

    viewer.set_frame_index(2)

    assert "3 / 3" in viewer.frame_label.text()
    assert viewer.thumbnail_list.currentRow() == 2


def test_image_viewer_shows_star_overlay_after_registration(tmp_path):
    _app = QApplication.instance() or QApplication([])
    positions = [(20.0, 30.0), (80.0, 40.0), (60.0, 90.0)]
    _write_star_field_fits(tmp_path / "a.fits", positions)
    _write_star_field_fits(tmp_path / "b.fits", [(x + 4.0, y - 2.0) for x, y in positions])
    stack = load_frame_stack(tmp_path)
    registered = register_stack(stack, reference_index=0)

    viewer = ImageViewer()
    viewer.set_stack(stack)
    viewer.set_registered_stack(registered)

    assert viewer.star_overlay_button.isEnabled()
    assert viewer.star_overlay_button.isChecked()
    assert len(viewer._star_items) == len(positions)
    assert "Sterne gematcht" in viewer.frame_label.text()
