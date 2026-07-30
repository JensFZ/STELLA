import numpy as np
import pytest

from core.astrometry import build_approx_wcs
from core.plate_solving import solve_plate

# Genug erfundene Sternpositionen, um an der Mindestanzahl (4) nicht zu scheitern.
PIXEL_X = np.array([10.0, 200.0, 400.0, 350.0, 50.0])
PIXEL_Y = np.array([15.0, 220.0, 60.0, 410.0, 300.0])
IMAGE_SHAPE = (512, 512)
CENTER_RA_DEG = 83.822
CENTER_DEC_DEG = -5.391
PIXEL_SCALE_ARCSEC = 2.393


class _FakeAstrometryNetClient:
    """Ersetzt astroquery.astrometry_net.AstrometryNet — kein echter Netzwerkzugriff im Test."""

    def __init__(self, response=None):
        self._response = response
        self.api_key = None
        self.calls: list[dict] = []

    def solve_from_source_list(self, x, y, image_width, image_height, **kwargs):
        self.calls.append(
            {"x": x, "y": y, "image_width": image_width, "image_height": image_height, **kwargs}
        )
        return self._response


def _solved_header():
    """Ein Header, wie ihn astrometry.net bei Erfolg liefert: eine gültige WCS."""
    wcs = build_approx_wcs(CENTER_RA_DEG, CENTER_DEC_DEG, PIXEL_SCALE_ARCSEC, IMAGE_SHAPE)
    return wcs.to_header()


def _install_fake_client(monkeypatch, response=None):
    """Ersetzt astroquery.astrometry_net.AstrometryNet direkt im bereits importierten Modul --
    core.plate_solving.solve_plate importiert den Namen bei jedem Aufruf frisch von dort
    (`from astroquery.astrometry_net import AstrometryNet`), holt sich also diesen Ersatz."""
    client = _FakeAstrometryNetClient(response)
    monkeypatch.setattr("astroquery.astrometry_net.AstrometryNet", lambda: client)
    return client


def test_solve_plate_requires_api_key():
    with pytest.raises(ValueError, match="API-Schlüssel"):
        solve_plate(PIXEL_X, PIXEL_Y, IMAGE_SHAPE, api_key="")


def test_solve_plate_requires_minimum_star_count():
    with pytest.raises(ValueError, match="4"):
        solve_plate(PIXEL_X[:2], PIXEL_Y[:2], IMAGE_SHAPE, api_key="dummy")


def test_solve_plate_raises_when_astrometry_net_finds_no_solution(monkeypatch):
    _install_fake_client(monkeypatch, response={})

    with pytest.raises(RuntimeError, match="keine Lösung"):
        solve_plate(PIXEL_X, PIXEL_Y, IMAGE_SHAPE, api_key="dummy")


def test_solve_plate_returns_center_and_scale_on_success(monkeypatch):
    _install_fake_client(monkeypatch, response=_solved_header())

    ra_deg, dec_deg, pixel_scale_arcsec = solve_plate(
        PIXEL_X, PIXEL_Y, IMAGE_SHAPE, api_key="dummy"
    )

    assert ra_deg == pytest.approx(CENTER_RA_DEG, abs=1e-3)
    assert dec_deg == pytest.approx(CENTER_DEC_DEG, abs=1e-3)
    assert pixel_scale_arcsec == pytest.approx(PIXEL_SCALE_ARCSEC, rel=1e-3)


def test_solve_plate_passes_scale_hint_when_given(monkeypatch):
    client = _install_fake_client(monkeypatch, response=_solved_header())

    solve_plate(
        PIXEL_X, PIXEL_Y, IMAGE_SHAPE, api_key="dummy", pixel_scale_arcsec=PIXEL_SCALE_ARCSEC
    )

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["scale_units"] == "arcsecperpix"
    assert call["scale_est"] == PIXEL_SCALE_ARCSEC
    assert call["scale_err"] == pytest.approx(20.0)


def test_solve_plate_omits_scale_hint_when_not_given(monkeypatch):
    """Ohne bekanntes Teleskop soll die Suche wirklich blind laufen -- ein erratener
    Maßstab-Hinweis würde astrometry.net eher in die Irre führen als beschleunigen."""
    client = _install_fake_client(monkeypatch, response=_solved_header())

    solve_plate(PIXEL_X, PIXEL_Y, IMAGE_SHAPE, api_key="dummy", pixel_scale_arcsec=None)

    call = client.calls[0]
    assert "scale_est" not in call
    assert "scale_units" not in call


def test_solve_plate_sets_api_key_on_client(monkeypatch):
    client = _install_fake_client(monkeypatch, response=_solved_header())

    solve_plate(PIXEL_X, PIXEL_Y, IMAGE_SHAPE, api_key="geheim-123")

    assert client.api_key == "geheim-123"
