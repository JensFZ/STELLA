from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
from astropy.wcs.utils import fit_wcs_from_points, proj_plane_pixel_scales


@dataclass
class GaiaStar:
    ra_deg: float
    dec_deg: float
    mag: float


@dataclass
class StarMatch:
    pixel_x: float
    pixel_y: float
    ra_deg: float
    dec_deg: float


@dataclass
class AstrometricSolution:
    wcs: WCS
    n_matches: int
    residuals_arcsec: np.ndarray
    rms_residual_arcsec: float


def query_gaia_stars(
    center_ra_deg: float, center_dec_deg: float, radius_deg: float, mag_limit: float = 18.0
) -> list[GaiaStar]:
    """Fragt den Gaia-Katalog (via astroquery, benötigt Netzwerkzugriff) nach Sternen im
    Suchradius um ein Feldzentrum ab."""
    from astroquery.gaia import Gaia  # Import erst hier: benötigt Netzwerk beim ersten Zugriff.

    center = SkyCoord(ra=center_ra_deg * u.deg, dec=center_dec_deg * u.deg, frame="icrs")
    table = Gaia.query_object(coordinate=center, radius=radius_deg * u.deg)

    stars = []
    for row in table:
        mag = row["phot_g_mean_mag"]
        mag_value = None if mag is None or np.ma.is_masked(mag) else float(mag)
        if mag_value is not None and mag_value > mag_limit:
            continue
        stars.append(
            GaiaStar(
                ra_deg=float(row["ra"]), dec_deg=float(row["dec"]), mag=mag_value or float("nan")
            )
        )
    return stars


def match_stars_to_gaia(
    pixel_x: np.ndarray,
    pixel_y: np.ndarray,
    approx_wcs: WCS,
    gaia_stars: list[GaiaStar],
    max_separation_arcsec: float = 3.0,
) -> list[StarMatch]:
    """Ordnet erkannte Sterne (Pixelkoordinaten) über eine grobe Näherungs-WCS den
    nächstgelegenen Gaia-Katalogeinträgen zu (Nearest-Neighbour mit Abstandsschwelle)."""
    if len(gaia_stars) == 0 or len(pixel_x) == 0:
        return []

    approx_ra, approx_dec = approx_wcs.all_pix2world(pixel_x, pixel_y, 0)
    detected_coords = SkyCoord(ra=approx_ra * u.deg, dec=approx_dec * u.deg)
    gaia_coords = SkyCoord(
        ra=[s.ra_deg for s in gaia_stars] * u.deg, dec=[s.dec_deg for s in gaia_stars] * u.deg
    )

    catalog_index, separation, _ = detected_coords.match_to_catalog_sky(gaia_coords)

    matches = []
    for i, (star_idx, sep) in enumerate(zip(catalog_index, separation, strict=True)):
        if sep.arcsec <= max_separation_arcsec:
            gaia_star = gaia_stars[int(star_idx)]
            matches.append(
                StarMatch(
                    pixel_x=float(pixel_x[i]),
                    pixel_y=float(pixel_y[i]),
                    ra_deg=gaia_star.ra_deg,
                    dec_deg=gaia_star.dec_deg,
                )
            )
    return matches


def fit_astrometric_solution(matches: list[StarMatch]) -> AstrometricSolution:
    """Fittet eine WCS-Lösung (TAN-Projektion) aus gematchten Pixel/Himmel-Koordinatenpaaren
    und berechnet die Residuen des Fits."""
    if len(matches) < 3:
        raise ValueError("Mindestens 3 Sternpaare für einen WCS-Fit erforderlich")

    # fit_wcs_from_points liefert eine WCS, die trotz abweichendem Docstring mit origin=0
    # (0-indizierte Pixelkoordinaten, wie im restlichen STELLA-Code) korrekt rundtrippt —
    # empirisch verifiziert in tests/test_astrometry.py.
    x = np.array([m.pixel_x for m in matches])
    y = np.array([m.pixel_y for m in matches])
    world = SkyCoord(
        ra=[m.ra_deg for m in matches] * u.deg, dec=[m.dec_deg for m in matches] * u.deg
    )

    wcs = fit_wcs_from_points((x, y), world)

    fitted_ra, fitted_dec = wcs.all_pix2world(x, y, 0)
    fitted_coords = SkyCoord(ra=fitted_ra * u.deg, dec=fitted_dec * u.deg)
    residuals_arcsec = fitted_coords.separation(world).arcsec
    rms_residual_arcsec = float(np.sqrt(np.mean(residuals_arcsec**2)))

    return AstrometricSolution(
        wcs=wcs,
        n_matches=len(matches),
        residuals_arcsec=residuals_arcsec,
        rms_residual_arcsec=rms_residual_arcsec,
    )


def pixel_to_sky(wcs: WCS, row: float, col: float) -> tuple[float, float]:
    """Rechnet eine (row, col)-Pixelposition (0-indiziert, wie im restlichen STELLA-Code) über
    die gegebene WCS (siehe fit_astrometric_solution) in (RA, Dec) in Grad um."""
    ra, dec = wcs.all_pix2world(col, row, 0)
    return float(ra), float(dec)


def estimate_field_center_and_scale(
    wcs: WCS | None, image_shape: tuple[int, int]
) -> tuple[float, float, float] | None:
    """Schätzt Feldzentrum (RA/Dec in Grad) und Pixelmaßstab (arcsec/px) aus einer vorhandenen,
    ggf. groben Header-WCS als Startwert für die Gaia-Suche. Gibt None zurück, wenn keine WCS
    vorhanden ist (dann müssen Zentrum/Maßstab manuell eingegeben werden)."""
    if wcs is None:
        return None
    height, width = image_shape
    ra, dec = wcs.all_pix2world((width - 1) / 2, (height - 1) / 2, 0)
    pixel_scale_arcsec = float(np.mean(proj_plane_pixel_scales(wcs))) * 3600.0
    return float(ra), float(dec), pixel_scale_arcsec


def build_approx_wcs(
    center_ra_deg: float,
    center_dec_deg: float,
    pixel_scale_arcsec: float,
    image_shape: tuple[int, int],
) -> WCS:
    """Baut eine grobe, unrotierte TAN-Näherungs-WCS aus Feldzentrum und Pixelmaßstab — dient
    nur als Startpunkt für das Gaia-Cross-Matching, nicht als endgültige Lösung."""
    height, width = image_shape
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [(width + 1) / 2, (height + 1) / 2]
    wcs.wcs.cdelt = [-pixel_scale_arcsec / 3600.0, pixel_scale_arcsec / 3600.0]
    wcs.wcs.crval = [center_ra_deg, center_dec_deg]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs
