import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from astropy.io import fits
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.io_fits import load_frame_stack  # noqa: E402
from gui.views.image_viewer import ImageViewer  # noqa: E402


def _write_fits(path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    data = rng.normal(loc=100.0, scale=10.0, size=(32, 32)).astype(np.float32)
    fits.writeto(path, data, overwrite=True)


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
