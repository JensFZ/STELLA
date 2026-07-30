from __future__ import annotations

from dataclasses import dataclass

from core.io_fits import pixel_scale_from_optics


@dataclass(frozen=True)
class TelescopeSpec:
    """Sensor- und Optikdaten eines konkreten Geräts, für die Presets im Suchdialog.

    Nur der Pixelmaßstab fließt tatsächlich in eine Suche ein; Blende und Sensor stehen
    dabei, damit sich der Wert gegen das Datenblatt nachvollziehen lässt.
    """

    name: str
    sensor: str
    aperture_mm: float
    focal_length_mm: float
    pixel_size_um: float

    @property
    def pixel_scale_arcsec(self) -> float:
        return pixel_scale_from_optics(self.pixel_size_um, self.focal_length_mm)


# Herstellerangaben (ZWO/Seestar, Stand 2026-07):
#   S50:      zwoastro.com/product/seestar-s50       — 50 mm / 250 mm / IMX462
#   S30:      seestar.com/blogs/faq/s30               — 30 mm / 150 mm / IMX662
#   S30 Pro:  seestar.com/products/seestar-s30-pro     — 30 mm / 160 mm / IMX585 (Teleobjektiv)
#
# Alle drei teilen sich die 2,9-µm-Pixelgröße der Sony-STARVIS2-Reihe (IMX462/IMX662/IMX585) —
# nur Sensorfläche und Auflösung unterscheiden sich, der Maßstab folgt allein aus Pixelgröße
# und Brennweite. Der berechnete Wert für den S50 (2,393″/px) deckt sich mit dem, was
# pixel_scale_from_header() aus echten S50-Rohframes ermittelt (siehe README, Abschnitt
# „Bayer-Muster“) — eine unabhängige Bestätigung der recherchierten Zahlen.
#
# Der S30 Pro hat zusätzlich eine Weitwinkelkamera (IMX586, 6 mm Brennweite, 0,8-µm-Pixel);
# die dient der Rahmenübersicht beim Positionieren, nicht der eigentlichen Aufnahme, und
# bleibt hier unberücksichtigt.
KNOWN_TELESCOPES: list[TelescopeSpec] = [
    TelescopeSpec(
        name="Seestar S50",
        sensor="Sony IMX462",
        aperture_mm=50.0,
        focal_length_mm=250.0,
        pixel_size_um=2.9,
    ),
    TelescopeSpec(
        name="Seestar S30",
        sensor="Sony IMX662",
        aperture_mm=30.0,
        focal_length_mm=150.0,
        pixel_size_um=2.9,
    ),
    TelescopeSpec(
        name="Seestar S30 Pro",
        sensor="Sony IMX585",
        aperture_mm=30.0,
        focal_length_mm=160.0,
        pixel_size_um=2.9,
    ),
]
