from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.wcs import WCS

logger = logging.getLogger(__name__)

FITS_EXTENSIONS = {".fits", ".fit", ".fts"}

#: Speicherobergrenze für einen Bildstapel. Ein Aufnahmeordner kann tausende Frames
#: enthalten (18 GB und mehr sind bei modernen Smart-Teleskopen normal); alle gleichzeitig
#: als float32 zu halten sprengt jeden Arbeitsspeicher. Der Wert begrenzt, wie viele Frames
#: geladen werden, bevor abgeschnitten wird.
DEFAULT_MEMORY_BUDGET_BYTES = 2 * 1024**3

#: Zeitlücke, ab der zwei aufeinanderfolgende Aufnahmen als getrennte Sitzungen gelten.
#: Aufnahmeordner enthalten oft mehrere Nächte. Frames verschiedener Nächte gemeinsam zu
#: stapeln ist sinnlos: das Teleskop stand anders ausgerichtet, und ein Objekt hätte sich
#: um ein Vielfaches des Bildfelds weiterbewegt.
DEFAULT_SESSION_GAP_SECONDS = 600


@dataclass
class FitsFrame:
    path: Path
    data: np.ndarray
    header: fits.Header
    wcs: WCS | None
    obs_time: str | None
    #: True, wenn das Bayer-Mosaik durch 2×2-Mittelung entfernt wurde. Dann ist die
    #: Auflösung halbiert und der Pixelmaßstab verdoppelt.
    bayer_binned: bool = False


@dataclass
class FrameStack:
    frames: list[FitsFrame]

    def __len__(self) -> int:
        return len(self.frames)

    def __getitem__(self, index: int) -> FitsFrame:
        return self.frames[index]


@dataclass
class FitsInfo:
    """Kopfdaten einer FITS-Datei, ohne die Bilddaten zu lesen."""

    path: Path
    shape: tuple[int, int]  # (Zeilen, Spalten) nach Mono-Wandlung und ggf. Bayer-Mittelung
    n_planes: int  # 1 = einkanalig, >1 = Farb-/Mehrebenenbild
    obs_time: str | None
    #: Bayer-Muster laut Header, z.B. "GRBG" — None bei bereits entbayerten Aufnahmen.
    bayer: str | None = None
    #: Geschätzter Pixelmaßstab in arcsec/px, passend zur oben angegebenen Form.
    pixel_scale_arcsec: float | None = None

    @property
    def bytes_as_float32(self) -> int:
        return self.shape[0] * self.shape[1] * 4


@dataclass
class Session:
    """Eine zusammenhängende Aufnahmeserie (eine Nacht, ein Durchlauf)."""

    infos: list[FitsInfo]

    def __len__(self) -> int:
        return len(self.infos)

    @property
    def start(self) -> str | None:
        return self.infos[0].obs_time if self.infos else None

    @property
    def end(self) -> str | None:
        return self.infos[-1].obs_time if self.infos else None

    @property
    def duration_minutes(self) -> float:
        if len(self.infos) < 2 or not self.start or not self.end:
            return 0.0
        return (_parse_time(self.end) - _parse_time(self.start)).total_seconds() / 60


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def group_into_sessions(
    infos: list[FitsInfo], max_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS
) -> list[Session]:
    """Teilt Frames anhand ihrer Aufnahmezeit in zusammenhängende Serien.

    Ohne diese Trennung würden Frames verschiedener Nächte gemeinsam gestapelt — das
    Ergebnis wäre wertlos, weil sich Ausrichtung und Objektposition dazwischen völlig
    ändern. Frames ohne Zeitstempel bleiben in ihrer Dateireihenfolge und bilden eine
    eigene Serie, da sich ihre Zusammengehörigkeit nicht beurteilen lässt.
    """
    timed = sorted((i for i in infos if i.obs_time), key=lambda i: i.obs_time)
    untimed = [i for i in infos if not i.obs_time]

    sessions: list[Session] = []
    current: list[FitsInfo] = []
    previous: datetime | None = None

    for info in timed:
        moment = _parse_time(info.obs_time)
        if previous is not None and (moment - previous).total_seconds() > max_gap_seconds:
            sessions.append(Session(infos=current))
            current = []
        current.append(info)
        previous = moment

    if current:
        sessions.append(Session(infos=current))
    if untimed:
        sessions.append(Session(infos=untimed))

    return sessions


@dataclass
class FolderScan:
    """Ergebnis der Voranalyse eines Ordners. Ermöglicht es, dem Nutzer *vor* dem Laden zu
    sagen, was ihn erwartet, statt nach Minuten am Speicher zu scheitern."""

    folder: Path
    infos: list[FitsInfo]
    unreadable: list[tuple[Path, str]]

    def shape_groups(self) -> list[tuple[tuple[int, int], int]]:
        """Bildgrößen mit ihrer Häufigkeit, häufigste zuerst."""
        return Counter(info.shape for info in self.infos).most_common()

    def dominant_shape(self) -> tuple[int, int] | None:
        groups = self.shape_groups()
        return groups[0][0] if groups else None

    def for_shape(self, shape: tuple[int, int]) -> list[FitsInfo]:
        return [info for info in self.infos if info.shape == shape]

    def bayer_patterns(self) -> set[str]:
        """Im Ordner vorkommende Bayer-Muster. Leer, wenn alle Aufnahmen entbayert sind."""
        return {info.bayer for info in self.infos if info.bayer}

    def pixel_scale_arcsec(self) -> float | None:
        """Pixelmaßstab der häufigsten Bildgröße, sofern aus den Headern ableitbar."""
        shape = self.dominant_shape()
        if shape is None:
            return None
        for info in self.for_shape(shape):
            if info.pixel_scale_arcsec:
                return info.pixel_scale_arcsec
        return None


def find_fits_files(folder: Path) -> list[Path]:
    folder = Path(folder)
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in FITS_EXTENSIONS)


def bayer_pattern(header: fits.Header) -> str | None:
    """Bayer-Muster aus dem Header, falls die Aufnahme unentbayert vorliegt."""
    value = header.get("BAYERPAT")
    return str(value).strip() if value else None


def bin_bayer_2x2(data: np.ndarray) -> np.ndarray:
    """Mittelt je 2×2-Block zu einem Pixel und entfernt damit das Bayer-Mosaik.

    Rohaufnahmen von Farbsensoren enthalten das Sensormosaik: benachbarte Pixel messen
    verschiedene Farben und damit systematisch verschiedene Helligkeiten. Gemessen an
    Seestar-S50-Aufnahmen unterscheiden sich die vier Positionen eines Blocks um rund 19 %
    — als Schachbrettmuster sichtbar.

    Für die Detektion ist das schädlich: das Muster geht in die Hintergrundstatistik ein und
    hebt deren Streuung (gemessen um Faktor 1,46). Da STELLA die SNR-Schwelle daran bemisst,
    fallen lichtschwache Objekte unter die Schwelle — genau die gesuchten. Zusätzlich
    verwechselt die Sternerkennung das Mosaik mit Struktur, und Shift-and-Stack vermischt
    bei Subpixel-Verschiebungen die Farbkanäle.

    Die Mittelung über den Block ist das übliche Vorgehen für Farbsensordaten in Astrometrie
    und Photometrie. Preis: die Auflösung halbiert sich, der Pixelmaßstab verdoppelt sich.
    """
    height, width = data.shape[-2:]
    # Ungerade Randzeile/-spalte abschneiden, sonst passt das 2×2-Raster nicht auf.
    trimmed = data[: height - height % 2, : width - width % 2]
    return (
        trimmed[0::2, 0::2] + trimmed[0::2, 1::2] + trimmed[1::2, 0::2] + trimmed[1::2, 1::2]
    ) / 4.0


def to_mono(data: np.ndarray) -> np.ndarray:
    """Reduziert ein Mehrebenenbild auf eine Ebene.

    Farbaufnahmen (etwa entbayerte Bilder von One-Shot-Colour-Kameras) liegen als
    (Ebene, Zeile, Spalte) vor. Für die Detektion ist die Farbinformation ohne Nutzen, ein
    Mittel über die Kanäle verbessert sogar das Rauschverhalten. Der gesamte übrige Code
    rechnet mit zweidimensionalen Bildern.
    """
    if data.ndim == 2:
        return data
    if data.ndim == 3:
        # Ebenen-Achse ist die kürzeste (typisch 3 oder 4 Kanäle gegenüber >100 Pixeln).
        plane_axis = int(np.argmin(data.shape))
        return data.mean(axis=plane_axis)
    raise ValueError(f"Nicht unterstützte Bilddimension: {data.shape}")


def pixel_scale_from_header(header: fits.Header, binned: bool = False) -> float | None:
    """Schätzt den Pixelmaßstab in arcsec/px aus Pixelgröße und Brennweite.

    Rohaufnahmen enthalten oft kein WCS (die Frames des Seestar S50 etwa nicht), wohl aber
    XPIXSZ und FOCALLEN. Daraus ergibt sich der Maßstab über die Kleinwinkelnäherung —
    sonst müsste der Wert geraten werden, und er bestimmt maßgeblich, welche
    Objektgeschwindigkeiten die Suche überhaupt trifft.
    """
    pixel_size_um = header.get("XPIXSZ")
    focal_length_mm = header.get("FOCALLEN")
    if not pixel_size_um or not focal_length_mm:
        return None
    # 206265 arcsec entsprechen einem Radiant; Pixelgröße in mm / Brennweite in mm.
    scale = 206265.0 * (float(pixel_size_um) / 1000.0) / float(focal_length_mm)
    return scale * 2.0 if binned else scale


def _shape_after_mono(header: fits.Header) -> tuple[tuple[int, int], int]:
    """(Zeilen, Spalten) und Ebenenzahl aus dem Header, ohne die Daten zu lesen."""
    naxis = int(header.get("NAXIS", 0))
    axes = [int(header[f"NAXIS{i}"]) for i in range(naxis, 0, -1)]  # langsamste Achse zuerst
    if len(axes) == 2:
        return (axes[0], axes[1]), 1
    if len(axes) == 3:
        plane_axis = int(np.argmin(axes))
        spatial = [size for i, size in enumerate(axes) if i != plane_axis]
        return (spatial[0], spatial[1]), axes[plane_axis]
    raise ValueError(f"Nicht unterstützte Achsenzahl: NAXIS={naxis}")


def scan_folder(folder: Path, debayer: bool = True) -> FolderScan:
    """Liest nur die Header aller FITS-Dateien im Ordner.

    Das ist um Größenordnungen schneller als die Bilddaten zu laden und beantwortet die
    entscheidenden Fragen vorab: wie viele Frames, welche Bildgrößen, wie viel Speicher.

    `debayer` muss hier bereits bekannt sein, weil die 2×2-Mittelung die Bildgröße halbiert
    — und die Größe bestimmt Gruppierung und Speicherbedarf.
    """
    folder = Path(folder)
    infos: list[FitsInfo] = []
    unreadable: list[tuple[Path, str]] = []

    for path in find_fits_files(folder):
        try:
            header = fits.getheader(path)
            shape, n_planes = _shape_after_mono(header)
            pattern = bayer_pattern(header)
            binned = debayer and pattern is not None
            if binned:
                shape = (shape[0] // 2, shape[1] // 2)
            infos.append(
                FitsInfo(
                    path=path,
                    shape=shape,
                    n_planes=n_planes,
                    obs_time=header.get("DATE-OBS"),
                    bayer=pattern,
                    pixel_scale_arcsec=pixel_scale_from_header(header, binned=binned),
                )
            )
        except Exception as exc:  # noqa: BLE001
            unreadable.append((path, str(exc)))

    return FolderScan(folder=folder, infos=infos, unreadable=unreadable)


def select_frames_to_load(
    scan: FolderScan,
    shape: tuple[int, int] | None = None,
    session_index: int | None = None,
    max_frames: int | None = None,
    memory_budget_bytes: int = DEFAULT_MEMORY_BUDGET_BYTES,
    max_gap_seconds: float = DEFAULT_SESSION_GAP_SECONDS,
) -> list[FitsInfo]:
    """Wählt aus einem Scan die tatsächlich zu ladenden Frames aus.

    Drei Einschränkungen, jede aus einem harten Grund:

    1. **Einheitliche Bildgröße** — Shift-and-Stack summiert alle Frames auf ein
       gemeinsames Raster; gemischte Größen sind dort nicht verarbeitbar.
    2. **Eine Aufnahmeserie** — Frames verschiedener Nächte gemeinsam zu stapeln liefert
       Unsinn. Ohne Angabe wird die längste Serie gewählt.
    3. **Speicherbudget** — ein Ordner kann tausende Frames enthalten, die zusammen nicht
       in den Arbeitsspeicher passen.
    """
    shape = shape or scan.dominant_shape()
    if shape is None:
        return []

    sessions = group_into_sessions(scan.for_shape(shape), max_gap_seconds=max_gap_seconds)
    if not sessions:
        return []

    if session_index is None:
        candidates = list(max(sessions, key=len).infos)
    else:
        candidates = list(sessions[session_index].infos)

    if max_frames is not None:
        candidates = candidates[:max_frames]

    if memory_budget_bytes is not None and candidates:
        per_frame = candidates[0].bytes_as_float32
        affordable = max(1, memory_budget_bytes // per_frame)
        candidates = candidates[:affordable]

    return candidates


def load_fits_frame(path: Path, debayer: bool = True) -> FitsFrame:
    with fits.open(path) as hdul:
        hdu = next(h for h in hdul if h.data is not None)
        header = hdu.header
        data = to_mono(hdu.data)

        binned = debayer and bayer_pattern(header) is not None
        if binned:
            data = bin_bayer_2x2(data)

        data = np.asarray(data, dtype=np.float32)
        try:
            wcs = WCS(header)
            wcs = wcs if wcs.has_celestial else None
        except Exception:
            wcs = None
        if binned and wcs is not None:
            # Nach der Mittelung stimmt ein vorhandenes WCS nicht mehr: ein Pixel deckt die
            # doppelte Fläche ab. Ohne Anpassung wären alle daraus abgeleiteten Positionen
            # um den Faktor zwei daneben.
            wcs = wcs.slice((np.s_[::2], np.s_[::2]))
        obs_time = header.get("DATE-OBS")

    return FitsFrame(
        path=Path(path),
        data=data,
        header=header,
        wcs=wcs,
        obs_time=obs_time,
        bayer_binned=binned,
    )


def load_frame_stack(
    folder: Path,
    max_frames: int | None = None,
    memory_budget_bytes: int = DEFAULT_MEMORY_BUDGET_BYTES,
    debayer: bool = True,
) -> FrameStack:
    scan = scan_folder(folder, debayer=debayer)
    selected = select_frames_to_load(
        scan, max_frames=max_frames, memory_budget_bytes=memory_budget_bytes
    )
    return FrameStack(
        frames=[load_fits_frame(info.path, debayer=debayer) for info in selected]
    )


def background_stats(data: np.ndarray) -> tuple[float, float]:
    """Hintergrund-Median und -Rauschen, robust gegen Sterne (sigma-clipped)."""
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return 0.0, 1.0
    _, median, sigma = sigma_clipped_stats(finite, sigma=3.0)
    # Ein flaches Bild hat kein Rauschen; ohne Untergrenze wuerde durch null geteilt.
    return float(median), float(sigma) if sigma > 0 else 1.0


def stretch_to_uint8(
    data: np.ndarray,
    low_sigma: float = -1.0,
    high_sigma: float = 20.0,
    stats: tuple[float, float] | None = None,
) -> np.ndarray:
    """Lineares Stretch nach 0-255 uint8, verankert am Hintergrundrauschen.

    Die Grenzen liegen bei `median + n * sigma`. Ein Perzentil-Stretch taugt hier nicht:
    in einer Astroaufnahme sind über 99 % der Pixel Hintergrund, seine Grenzen liegen also
    beide im Rauschen und spannen wenige Sigma über die ganze Graustufenskala — der
    Hintergrund erscheint dann als Bildrauschen statt als schwarzer Himmel."""
    median, sigma = stats if stats is not None else background_stats(data)
    lo = median + low_sigma * sigma
    hi = median + high_sigma * sigma
    if hi <= lo:
        hi = lo + 1.0
    clipped = np.clip((np.nan_to_num(data, nan=lo) - lo) / (hi - lo), 0.0, 1.0)
    return (clipped * 255).astype(np.uint8)


def make_thumbnail(data: np.ndarray, size: int = 128) -> np.ndarray:
    """Downsampled, gestrecktes Vorschaubild (uint8) mit max. Kantenlänge `size`."""
    h, w = data.shape[-2:]
    step = max(1, max(h, w) // size)
    return stretch_to_uint8(data[::step, ::step])
