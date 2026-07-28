import numpy as np
import pytest
from astropy.wcs import WCS

from core.astrometry import (
    GaiaStar,
    build_approx_wcs,
    estimate_field_center_and_scale,
    fit_astrometric_solution,
    match_stars_to_gaia,
    pixel_to_sky,
)

IMAGE_SIZE = 200
PIXEL_SCALE_ARCSEC = 1.0
CENTER_RA_DEG = 180.0
CENTER_DEC_DEG = 10.0


def _make_wcs(crval_offset_deg: tuple[float, float] = (0.0, 0.0)) -> WCS:
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [IMAGE_SIZE / 2 + 0.5, IMAGE_SIZE / 2 + 0.5]
    wcs.wcs.cdelt = [-PIXEL_SCALE_ARCSEC / 3600.0, PIXEL_SCALE_ARCSEC / 3600.0]
    wcs.wcs.crval = [CENTER_RA_DEG + crval_offset_deg[0], CENTER_DEC_DEG + crval_offset_deg[1]]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def _make_synthetic_field(n_stars: int = 20, seed: int = 0):
    true_wcs = _make_wcs()
    rng = np.random.default_rng(seed)
    pixel_x = rng.uniform(10, IMAGE_SIZE - 10, size=n_stars)
    pixel_y = rng.uniform(10, IMAGE_SIZE - 10, size=n_stars)
    ra, dec = true_wcs.all_pix2world(pixel_x, pixel_y, 1)
    gaia_stars = [GaiaStar(ra_deg=float(r), dec_deg=float(d), mag=15.0) for r, d in zip(ra, dec)]
    # Pixelkoordinaten in unserer 0-indizierten Konvention (siehe fit_astrometric_solution).
    return true_wcs, pixel_x - 1, pixel_y - 1, gaia_stars


def test_match_stars_to_gaia_finds_nearest_neighbour_despite_rough_wcs():
    true_wcs, pixel_x, pixel_y, gaia_stars = _make_synthetic_field()
    # Grobe Näherungs-WCS mit Offset von einigen Pixeln (simuliert ungenauen Header-WCS).
    approx_wcs = _make_wcs(crval_offset_deg=(0.5 / 3600.0, 0.3 / 3600.0))

    matches = match_stars_to_gaia(
        pixel_x, pixel_y, approx_wcs, gaia_stars, max_separation_arcsec=3.0
    )

    assert len(matches) == len(gaia_stars)
    for match, expected in zip(matches, gaia_stars, strict=True):
        assert match.ra_deg == pytest.approx(expected.ra_deg, abs=1e-9)
        assert match.dec_deg == pytest.approx(expected.dec_deg, abs=1e-9)


def test_match_stars_to_gaia_respects_separation_threshold():
    true_wcs, pixel_x, pixel_y, gaia_stars = _make_synthetic_field(n_stars=5)
    # Näherungs-WCS ist um mehrere Bogenminuten daneben -> kein Match innerhalb der Schwelle.
    approx_wcs = _make_wcs(crval_offset_deg=(0.1, 0.1))

    matches = match_stars_to_gaia(
        pixel_x, pixel_y, approx_wcs, gaia_stars, max_separation_arcsec=3.0
    )

    assert matches == []


def test_fit_astrometric_solution_recovers_known_wcs():
    true_wcs, pixel_x, pixel_y, gaia_stars = _make_synthetic_field(n_stars=15)
    approx_wcs = _make_wcs(crval_offset_deg=(0.3 / 3600.0, 0.2 / 3600.0))

    matches = match_stars_to_gaia(pixel_x, pixel_y, approx_wcs, gaia_stars)
    solution = fit_astrometric_solution(matches)

    assert solution.n_matches == 15
    assert solution.rms_residual_arcsec < 0.01

    # Test an einem zusätzlichen, nicht im Fit verwendeten Punkt (Bildmitte).
    true_ra, true_dec = true_wcs.all_pix2world(IMAGE_SIZE / 2, IMAGE_SIZE / 2, 1)
    fitted_ra, fitted_dec = pixel_to_sky(
        solution.wcs, row=IMAGE_SIZE / 2 - 1, col=IMAGE_SIZE / 2 - 1
    )
    assert fitted_ra == pytest.approx(float(true_ra), abs=1e-4)
    assert fitted_dec == pytest.approx(float(true_dec), abs=1e-4)


def test_fit_astrometric_solution_requires_minimum_matches():
    _, pixel_x, pixel_y, gaia_stars = _make_synthetic_field(n_stars=2)
    matches = match_stars_to_gaia(pixel_x, pixel_y, _make_wcs(), gaia_stars)

    with pytest.raises(ValueError, match="Mindestens 3"):
        fit_astrometric_solution(matches)


def test_estimate_field_center_and_scale_returns_none_without_wcs():
    assert estimate_field_center_and_scale(None, (IMAGE_SIZE, IMAGE_SIZE)) is None


def test_estimate_field_center_and_scale_matches_known_wcs():
    wcs = _make_wcs()

    result = estimate_field_center_and_scale(wcs, (IMAGE_SIZE, IMAGE_SIZE))

    assert result is not None
    ra, dec, pixel_scale = result
    assert ra == pytest.approx(CENTER_RA_DEG, abs=1e-6)
    assert dec == pytest.approx(CENTER_DEC_DEG, abs=1e-6)
    assert pixel_scale == pytest.approx(PIXEL_SCALE_ARCSEC, abs=1e-6)


def test_build_approx_wcs_is_usable_for_matching():
    true_wcs, pixel_x, pixel_y, gaia_stars = _make_synthetic_field(n_stars=10)
    approx_wcs = build_approx_wcs(
        CENTER_RA_DEG, CENTER_DEC_DEG, PIXEL_SCALE_ARCSEC, (IMAGE_SIZE, IMAGE_SIZE)
    )

    matches = match_stars_to_gaia(
        pixel_x, pixel_y, approx_wcs, gaia_stars, max_separation_arcsec=5.0
    )

    assert len(matches) == len(gaia_stars)
