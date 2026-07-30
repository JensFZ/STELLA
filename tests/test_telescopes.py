import pytest

from core.telescopes import KNOWN_TELESCOPES, TelescopeSpec


def test_known_telescopes_cover_all_three_seestar_models():
    assert {spec.name for spec in KNOWN_TELESCOPES} == {
        "Seestar S50",
        "Seestar S30",
        "Seestar S30 Pro",
    }


def test_known_telescopes_have_unique_names():
    """seed_presets() legt Presets über den Namen an -- Dubletten würden sich gegenseitig
    verdecken, ohne dass das auffiele."""
    names = [spec.name for spec in KNOWN_TELESCOPES]
    assert len(names) == len(set(names))


@pytest.mark.parametrize(
    ("name", "expected_arcsec_per_px"),
    [
        # Herstellerangaben (siehe core/telescopes.py): 2,9-µm-Pixel, Brennweite laut
        # Datenblatt. arcsec/px = 206265 * (Pixelgröße_µm / 1000) / Brennweite_mm.
        ("Seestar S50", 2.3927),  # 2,9 µm / 250 mm
        ("Seestar S30", 3.9878),  # 2,9 µm / 150 mm
        ("Seestar S30 Pro", 3.7386),  # 2,9 µm / 160 mm (Teleobjektiv)
    ],
)
def test_pixel_scale_matches_manufacturer_specs(name, expected_arcsec_per_px):
    spec = next(spec for spec in KNOWN_TELESCOPES if spec.name == name)

    assert spec.pixel_scale_arcsec == pytest.approx(expected_arcsec_per_px, abs=1e-3)


def test_pixel_scale_matches_real_s50_measurement():
    """Unabhängige Gegenprobe: pixel_scale_from_header() hat an echten S50-Rohframes
    2,39 arcsec/px ermittelt (siehe README, Abschnitt „Bayer-Muster“) -- vor der
    Binning-Verdopplung. Die recherchierten Herstellerdaten müssen dazu passen."""
    s50 = next(spec for spec in KNOWN_TELESCOPES if spec.name == "Seestar S50")

    assert s50.pixel_scale_arcsec == pytest.approx(2.39, abs=0.01)


def test_pixel_scale_arcsec_uses_the_documented_formula():
    spec = TelescopeSpec(
        name="Testgerät", sensor="Test", aperture_mm=1.0, focal_length_mm=1000.0, pixel_size_um=5.0
    )

    assert spec.pixel_scale_arcsec == pytest.approx(206265.0 * (5.0 / 1000.0) / 1000.0)
