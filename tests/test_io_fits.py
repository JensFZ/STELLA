import numpy as np
from astropy.io import fits

from core.io_fits import find_fits_files, load_frame_stack, make_thumbnail, stretch_to_uint8


def _write_fits(path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    data = rng.normal(loc=100.0, scale=10.0, size=(64, 64)).astype(np.float32)
    header = fits.Header()
    header["DATE-OBS"] = f"2026-01-0{seed}T00:00:00"
    fits.writeto(path, data, header, overwrite=True)


def test_find_fits_files_sorted(tmp_path):
    _write_fits(tmp_path / "b.fits", 2)
    _write_fits(tmp_path / "a.fits", 1)

    files = find_fits_files(tmp_path)

    assert [f.name for f in files] == ["a.fits", "b.fits"]


def test_load_frame_stack_reads_data_and_header(tmp_path):
    _write_fits(tmp_path / "frame1.fits", 1)
    _write_fits(tmp_path / "frame2.fits", 2)

    stack = load_frame_stack(tmp_path)

    assert len(stack) == 2
    assert stack[0].data.shape == (64, 64)
    assert stack[0].obs_time == "2026-01-01T00:00:00"


def test_stretch_to_uint8_range():
    data = np.array([[0.0, 50.0], [100.0, np.nan]], dtype=np.float32)

    result = stretch_to_uint8(data, low_pct=0.0, high_pct=100.0)

    assert result.dtype == np.uint8
    assert result.min() >= 0
    assert result.max() <= 255


def test_make_thumbnail_downsamples():
    data = np.zeros((512, 256), dtype=np.float32)

    thumb = make_thumbnail(data, size=128)

    assert max(thumb.shape) <= 128
