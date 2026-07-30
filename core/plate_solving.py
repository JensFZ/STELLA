from __future__ import annotations

import numpy as np
from astropy.wcs import WCS

from core.astrometry import estimate_field_center_and_scale
from core.settings import settings

_SETTINGS_KEY = "astrometry/astrometry_net_api_key"


def saved_api_key() -> str:
    value = settings().value(_SETTINGS_KEY)
    return str(value) if value else ""


def save_api_key(api_key: str) -> None:
    settings().setValue(_SETTINGS_KEY, api_key)


def solve_plate(
    pixel_x: np.ndarray,
    pixel_y: np.ndarray,
    image_shape: tuple[int, int],
    api_key: str,
    pixel_scale_arcsec: float | None = None,
    pixel_scale_tolerance_percent: float = 20.0,
    timeout_seconds: int = 120,
) -> tuple[float, float, float]:
    """Blindes Plate Solving über astrometry.net (nova.astrometry.net): bestimmt Feldzentrum
    und Pixelmaßstab rein aus dem Sternmuster — ganz ohne WCS im FITS-Header und ohne
    manuelle Schätzung. Ersetzt für den Fall "kein Header-WCS" die bisher einzige Option,
    Feldzentrum und Pixelmaßstab von Hand einzutragen.

    `pixel_scale_arcsec`, falls angegeben (etwa aus core.telescopes für ein bekanntes
    Teleskop), grenzt den durchsuchten Skalenbereich stark ein und beschleunigt die Suche
    erheblich — ohne ihn durchsucht astrometry.net den gesamten Himmel über alle Maßstäbe,
    was deutlich länger dauert und öfter ganz erfolglos bleibt.

    `pixel_x`/`pixel_y` sollten nach Helligkeit absteigend sortiert sein (wie sie
    core.alignment.detect_stars bereits liefert) — astrometry.net bevorzugt beim Aufbau
    seiner Sternmuster die vorderen Einträge der Liste.

    Erfordert einen kostenlosen API-Schlüssel von https://nova.astrometry.net/api_help.
    STELLA registriert dieses Konto nicht selbst — das muss die Nutzerin einmalig dort tun.
    """
    if not api_key:
        raise ValueError(
            "Kein astrometry.net-API-Schlüssel hinterlegt. Kostenlos erhältlich unter "
            "https://nova.astrometry.net/api_help."
        )
    if len(pixel_x) < 4:
        # astrometry.net braucht mehrere Sterne, um ein eindeutiges Muster (Quad) zu bilden;
        # mit weniger lohnt der Netzwerk-Roundtrip nicht.
        raise ValueError(
            f"Nur {len(pixel_x)} Sterne erkannt — für Plate Solving werden mindestens 4 "
            "benötigt."
        )

    from astroquery.astrometry_net import AstrometryNet  # Import erst hier: Netzwerkzugriff.

    height, width = image_shape
    client = AstrometryNet()
    client.api_key = api_key

    scale_settings: dict[str, float | str] = {}
    if pixel_scale_arcsec:
        scale_settings["scale_units"] = "arcsecperpix"
        scale_settings["scale_type"] = "ev"
        scale_settings["scale_est"] = pixel_scale_arcsec
        scale_settings["scale_err"] = pixel_scale_tolerance_percent

    header = client.solve_from_source_list(
        pixel_x,
        pixel_y,
        width,
        height,
        solve_timeout=timeout_seconds,
        verbose=False,
        **scale_settings,
    )
    if not header:
        raise RuntimeError(
            "astrometry.net konnte keine Lösung finden. Häufige Ursachen: zu wenige "
            "erkannte Sterne, ein falscher Pixelmaßstab-Hinweis oder ein Bildausschnitt "
            "ohne eindeutiges Sternmuster."
        )

    return estimate_field_center_and_scale(WCS(header), image_shape)
