from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from core.io_fits import (
    FitsInfo,
    bin_bayer_2x2,
    find_fits_files,
    group_into_sessions,
    load_fits_frame,
    load_frame_stack,
    make_thumbnail,
    pixel_scale_from_header,
    scan_folder,
    select_frames_to_load,
    stretch_to_uint8,
    to_mono,
)


def _write_fits(path, seed: int, shape: tuple[int, ...] = (64, 64)) -> None:
    """Schreibt einen Testframe. Die Zeitstempel liegen bewusst nur Sekunden auseinander,
    damit die Frames wie eine echte Aufnahmeserie zu einer Sitzung gehören — Frames mit
    Tagesabstand würde group_into_sessions() zu Recht in einzelne Sitzungen trennen."""
    rng = np.random.default_rng(seed)
    data = rng.normal(loc=100.0, scale=10.0, size=shape).astype(np.float32)
    header = fits.Header()
    header["DATE-OBS"] = f"2026-01-01T00:00:{seed:02d}"
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
    assert stack[0].obs_time == "2026-01-01T00:00:01"


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


def test_to_mono_passes_through_2d():
    data = np.ones((10, 12), dtype=np.float32)

    assert to_mono(data).shape == (10, 12)


def test_to_mono_averages_colour_planes():
    """Farbaufnahmen (z.B. entbayerte OSC-Frames) liegen als (Ebene, Zeile, Spalte) vor.
    Der übrige Code rechnet zweidimensional."""
    data = np.stack(
        [
            np.full((8, 9), 10.0),
            np.full((8, 9), 20.0),
            np.full((8, 9), 30.0),
        ]
    )

    mono = to_mono(data)

    assert mono.shape == (8, 9)
    assert np.allclose(mono, 20.0)


def test_to_mono_finds_plane_axis_regardless_of_position():
    data = np.zeros((8, 9, 3))

    assert to_mono(data).shape == (8, 9)


def test_to_mono_rejects_unsupported_dimensions():
    with pytest.raises(ValueError, match="Nicht unterstützte Bilddimension"):
        to_mono(np.zeros((2, 3, 4, 5)))


def test_load_fits_frame_converts_colour_to_mono(tmp_path):
    path = tmp_path / "colour.fits"
    _write_fits(path, 1, shape=(3, 16, 20))

    frame = load_fits_frame(path)

    assert frame.data.ndim == 2
    assert frame.data.shape == (16, 20)


def test_scan_folder_reports_shapes_without_loading_data(tmp_path):
    _write_fits(tmp_path / "a.fits", 1, shape=(32, 32))
    _write_fits(tmp_path / "b.fits", 2, shape=(32, 32))
    _write_fits(tmp_path / "c.fits", 3, shape=(3, 16, 16))

    scan = scan_folder(tmp_path)

    assert len(scan.infos) == 3
    assert scan.dominant_shape() == (32, 32)
    assert dict(scan.shape_groups()) == {(32, 32): 2, (16, 16): 1}
    colour = next(i for i in scan.infos if i.shape == (16, 16))
    assert colour.n_planes == 3


def test_scan_folder_records_unreadable_files(tmp_path):
    _write_fits(tmp_path / "ok.fits", 1)
    (tmp_path / "kaputt.fits").write_bytes(b"kein FITS")

    scan = scan_folder(tmp_path)

    assert len(scan.infos) == 1
    assert len(scan.unreadable) == 1
    assert scan.unreadable[0][0].name == "kaputt.fits"


def test_select_frames_skips_deviating_shapes(tmp_path):
    """Shift-and-Stack summiert auf ein gemeinsames Raster — gemischte Bildgrößen lassen
    sich nicht zusammen verarbeiten."""
    _write_fits(tmp_path / "a.fits", 1, shape=(32, 32))
    _write_fits(tmp_path / "b.fits", 2, shape=(32, 32))
    _write_fits(tmp_path / "gross.fits", 3, shape=(64, 64))

    selected = select_frames_to_load(scan_folder(tmp_path))

    assert len(selected) == 2
    assert all(info.shape == (32, 32) for info in selected)


def test_select_frames_respects_memory_budget(tmp_path):
    for i in range(1, 5):
        _write_fits(tmp_path / f"f{i}.fits", i, shape=(32, 32))
    per_frame = 32 * 32 * 4

    selected = select_frames_to_load(scan_folder(tmp_path), memory_budget_bytes=2 * per_frame)

    assert len(selected) == 2


def test_select_frames_respects_max_frames(tmp_path):
    for i in range(1, 5):
        _write_fits(tmp_path / f"f{i}.fits", i, shape=(32, 32))

    selected = select_frames_to_load(scan_folder(tmp_path), max_frames=3)

    assert len(selected) == 3


def test_load_frame_stack_applies_limits(tmp_path):
    for i in range(1, 6):
        _write_fits(tmp_path / f"f{i}.fits", i, shape=(32, 32))

    stack = load_frame_stack(tmp_path, max_frames=2)

    assert len(stack) == 2


def _write_fits_at(path, when: str, shape: tuple[int, ...] = (32, 32)) -> None:
    data = np.zeros(shape, dtype=np.float32)
    header = fits.Header()
    header["DATE-OBS"] = when
    fits.writeto(path, data, header, overwrite=True)


def test_group_into_sessions_splits_on_time_gap():
    infos = [
        FitsInfo(Path("a.fits"), (32, 32), 1, "2025-02-16T23:00:00"),
        FitsInfo(Path("b.fits"), (32, 32), 1, "2025-02-16T23:00:10"),
        # Eine Woche später: eindeutig eine andere Nacht.
        FitsInfo(Path("c.fits"), (32, 32), 1, "2025-02-23T22:00:00"),
    ]

    sessions = group_into_sessions(infos)

    assert [len(s) for s in sessions] == [2, 1]
    assert sessions[0].start == "2025-02-16T23:00:00"


def test_group_into_sessions_keeps_continuous_run_together():
    infos = [
        FitsInfo(Path(f"f{i}.fits"), (32, 32), 1, f"2025-02-16T23:{i:02d}:00") for i in range(10)
    ]

    sessions = group_into_sessions(infos)

    assert len(sessions) == 1
    assert sessions[0].duration_minutes == pytest.approx(9.0)


def test_group_into_sessions_isolates_frames_without_timestamp():
    infos = [
        FitsInfo(Path("a.fits"), (32, 32), 1, "2025-02-16T23:00:00"),
        FitsInfo(Path("ohne.fits"), (32, 32), 1, None),
    ]

    sessions = group_into_sessions(infos)

    assert len(sessions) == 2
    assert sessions[-1].infos[0].path.name == "ohne.fits"


def test_select_frames_uses_only_the_longest_session(tmp_path):
    """Regressionsschutz für echte Aufnahmeordner: die enthalten oft mehrere Nächte.
    Frames verschiedener Nächte gemeinsam zu stapeln ist wertlos — das Teleskop stand
    anders und ein bewegtes Objekt wäre längst aus dem Bildfeld gewandert."""
    # Kurze Serie (2 Frames) eine Woche vor der langen Serie (4 Frames).
    _write_fits_at(tmp_path / "alt1.fits", "2025-02-09T02:00:00")
    _write_fits_at(tmp_path / "alt2.fits", "2025-02-09T02:00:20")
    for i in range(4):
        _write_fits_at(tmp_path / f"neu{i}.fits", f"2025-02-16T23:0{i}:00")

    selected = select_frames_to_load(scan_folder(tmp_path))

    assert len(selected) == 4
    assert all(info.obs_time.startswith("2025-02-16") for info in selected)


def test_select_frames_can_pick_a_specific_session(tmp_path):
    _write_fits_at(tmp_path / "alt1.fits", "2025-02-09T02:00:00")
    _write_fits_at(tmp_path / "alt2.fits", "2025-02-09T02:00:20")
    for i in range(4):
        _write_fits_at(tmp_path / f"neu{i}.fits", f"2025-02-16T23:0{i}:00")

    selected = select_frames_to_load(scan_folder(tmp_path), session_index=0)

    assert len(selected) == 2
    assert all(info.obs_time.startswith("2025-02-09") for info in selected)


def _write_bayer_fits(path, pattern: str = "GRBG", size: int = 64) -> np.ndarray:
    """Schreibt ein Frame mit kuenstlichem Bayer-Muster: die vier Positionen im 2x2-Block
    haben verschiedene Grundhelligkeiten, wie bei einer echten Farbmatrix."""
    data = np.zeros((size, size), dtype=np.float32)
    data[0::2, 0::2] = 900.0  # G
    data[0::2, 1::2] = 800.0  # R
    data[1::2, 0::2] = 700.0  # B
    data[1::2, 1::2] = 900.0  # G
    header = fits.Header()
    header["DATE-OBS"] = "2026-01-01T00:00:00"
    header["BAYERPAT"] = pattern
    header["XPIXSZ"] = 2.9
    header["FOCALLEN"] = 250.0
    fits.writeto(path, data, header, overwrite=True)
    return data


def test_bin_bayer_2x2_removes_the_checkerboard():
    """Kern der Sache: nach der Mittelung darf kein Unterschied zwischen benachbarten
    Pixeln mehr vom Muster stammen."""
    data = np.zeros((8, 8))
    data[0::2, 0::2], data[0::2, 1::2] = 900.0, 800.0
    data[1::2, 0::2], data[1::2, 1::2] = 700.0, 900.0

    binned = bin_bayer_2x2(data)

    assert binned.shape == (4, 4)
    assert np.allclose(binned, (900 + 800 + 700 + 900) / 4)


def test_bin_bayer_2x2_lowers_background_noise():
    """Das Muster geht sonst in die Hintergrundstatistik ein und hebt die SNR-Schwelle,
    sodass lichtschwache Objekte uebersehen werden."""
    from astropy.stats import sigma_clipped_stats

    rng = np.random.default_rng(0)
    data = rng.normal(800.0, 20.0, size=(128, 128))
    data[0::2, 1::2] -= 100.0  # R dunkler
    data[1::2, 0::2] -= 140.0  # B noch dunkler

    _, _, std_raw = sigma_clipped_stats(data, sigma=3.0)
    _, _, std_binned = sigma_clipped_stats(bin_bayer_2x2(data), sigma=3.0)

    assert std_binned < std_raw / 2


def test_bin_bayer_2x2_handles_odd_dimensions():
    """Ungerade Kantenlaengen duerfen nicht zum Absturz fuehren."""
    binned = bin_bayer_2x2(np.ones((9, 7)))

    assert binned.shape == (4, 3)


def test_load_fits_frame_applies_bayer_binning(tmp_path):
    path = tmp_path / "roh.fit"
    _write_bayer_fits(path, size=64)

    frame = load_fits_frame(path)

    assert frame.bayer_binned is True
    assert frame.data.shape == (32, 32)
    assert np.allclose(frame.data, 825.0)


def test_load_fits_frame_can_keep_the_bayer_mosaic(tmp_path):
    path = tmp_path / "roh.fit"
    _write_bayer_fits(path, size=64)

    frame = load_fits_frame(path, debayer=False)

    assert frame.bayer_binned is False
    assert frame.data.shape == (64, 64)


def test_load_fits_frame_leaves_debayered_data_untouched(tmp_path):
    """Ohne BAYERPAT im Header darf nichts gemittelt werden — sonst verloere man bei
    bereits entbayerten Aufnahmen grundlos die halbe Aufloesung."""
    path = tmp_path / "fertig.fits"
    _write_fits(path, 1, shape=(64, 64))

    frame = load_fits_frame(path)

    assert frame.bayer_binned is False
    assert frame.data.shape == (64, 64)


def test_scan_reports_bayer_pattern_and_halved_shape(tmp_path):
    _write_bayer_fits(tmp_path / "a.fit", size=64)

    scan = scan_folder(tmp_path)

    assert scan.bayer_patterns() == {"GRBG"}
    assert scan.dominant_shape() == (32, 32), "Bildgroesse muss die Mittelung beruecksichtigen"


def test_scan_without_debayering_keeps_full_shape(tmp_path):
    _write_bayer_fits(tmp_path / "a.fit", size=64)

    scan = scan_folder(tmp_path, debayer=False)

    assert scan.dominant_shape() == (64, 64)


def test_pixel_scale_from_header_doubles_when_binned(tmp_path):
    _write_bayer_fits(tmp_path / "a.fit", size=64)
    header = fits.getheader(tmp_path / "a.fit")

    unbinned = pixel_scale_from_header(header, binned=False)
    binned = pixel_scale_from_header(header, binned=True)

    # 206265 * 0.0029 mm / 250 mm = 2.393 arcsec/px
    assert unbinned == pytest.approx(2.393, abs=0.01)
    assert binned == pytest.approx(2 * unbinned)


def test_pixel_scale_is_none_without_the_needed_headers():
    assert pixel_scale_from_header(fits.Header()) is None
