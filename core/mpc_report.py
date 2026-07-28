from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from astropy import units as u
from astropy.coordinates import Angle
from astropy.time import Time

LINE_LENGTH = 80


@dataclass
class MPCObservation:
    """Eine einzelne Beobachtung für den MPC-80-Spalten-Report.

    `designation` und `observatory_code` sind Platzhalter — vor einer echten Einreichung an das
    Minor Planet Center müssen sie durch offiziell zugewiesene Werte ersetzt werden."""

    ra_deg: float
    dec_deg: float
    obs_time: str  # FITS DATE-OBS
    magnitude: float | None = None
    band: str = "V"
    note1: str = " "
    note2: str = "C"  # C = CCD-Beobachtung
    designation: str = "       "  # 7 Zeichen Platzhalter für provisorische Bezeichnung
    observatory_code: str = "XXX"  # Platzhalter für den MPC-Stationscode


def _format_date(obs_time: str) -> str:
    dt = Time(obs_time, format="fits", scale="utc").datetime
    day_fraction = dt.day + (
        dt.hour + dt.minute / 60 + dt.second / 3600 + dt.microsecond / 3_600_000_000
    ) / 24
    return f"{dt.year:04d} {dt.month:02d} {day_fraction:09.6f}"


def _format_ra(ra_deg: float) -> str:
    hours, minutes, seconds = Angle(ra_deg, unit=u.deg).hms
    return f"{int(hours):02d} {int(minutes):02d} {seconds:05.2f} "


def _format_dec(dec_deg: float) -> str:
    sign = "+" if dec_deg >= 0 else "-"
    degrees, minutes, seconds = Angle(abs(dec_deg), unit=u.deg).dms
    return f"{sign}{int(degrees):02d} {int(minutes):02d} {abs(seconds):04.1f} "


def _format_magnitude(magnitude: float | None) -> str:
    return f"{magnitude:5.1f}" if magnitude is not None else " " * 5


def format_mpc_line(observation: MPCObservation) -> str:
    """Formatiert eine Beobachtung im klassischen MPC-80-Spalten-Format (Entwurf)."""
    line = (
        " " * 5  # 1-5: Paketierte Kleinplaneten-Nummer (unbekannt -> leer)
        + f"{observation.designation:<7s}"[:7]  # 6-12
        + " "  # 13: Discovery-Sternchen
        + observation.note1[:1]  # 14
        + observation.note2[:1]  # 15
        + _format_date(observation.obs_time)  # 16-32
        + _format_ra(observation.ra_deg)  # 33-44
        + _format_dec(observation.dec_deg)  # 45-56
        + " " * 9  # 57-65
        + _format_magnitude(observation.magnitude)  # 66-70
        + (observation.band[:1] if observation.band else " ")  # 71
        + " " * 6  # 72-77
        + f"{observation.observatory_code:<3s}"[:3]  # 78-80
    )
    return line[:LINE_LENGTH].ljust(LINE_LENGTH)


def write_mpc_report(observations: list[MPCObservation], path: str | Path) -> None:
    """Schreibt eine Liste von Beobachtungen als MPC-80-Spalten-Report-Datei."""
    lines = [format_mpc_line(obs) for obs in observations]
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")
