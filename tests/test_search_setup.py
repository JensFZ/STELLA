import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.views.search_setup import DEFAULT_SEARCH_PARAMS, default_parameters  # noqa: E402


def test_default_parameters_combines_pixel_scale_with_the_dialog_defaults():
    """default_parameters() erzeugt die eingebauten Teleskop-Presets. Nur der Pixelmaßstab
    ist geräteabhängig -- alle übrigen Werte müssen mit den Dialog-Startwerten
    übereinstimmen, sonst weichen Presets unbemerkt vom regulären Dialog ab."""
    params = default_parameters(2.393)

    assert params["pixel_scale_arcsec"] == 2.393
    for key, value in DEFAULT_SEARCH_PARAMS.items():
        assert params[key] == value


def test_default_parameters_has_all_keys_search_setup_dialog_expects():
    """_load_selected_preset() greift auf diese Schlüssel per [] zu -- ein fehlender
    Schlüssel wäre ein KeyError beim Laden eines eingebauten Presets, nicht beim Seeden."""
    params = default_parameters(1.0)

    assert set(params) == {
        "pixel_scale_arcsec",
        "speed_range_arcsec_per_min",
        "speed_step_arcsec_per_min",
        "angle_step_deg",
        "snr_threshold",
        "use_gpu",
    }
