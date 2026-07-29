from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from astropy.io import fits
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
    shape: tuple[int, int]  # (Zeilen, Spalten) nach einer eventuellen Mono-Wandlung
    n_planes: int  # 1 = einkanalig, >1 = Farb-/Mehrebenenbild
    obs_time: str | None

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


def find_fits_files(folder: Path) -> list[Path]:
    folder = Path(folder)
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in FITS_EXTENSIONS)


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


def scan_folder(folder: Path) -> FolderScan:
    """Liest nur die Header aller FITS-Dateien im Ordner.

    Das ist um Größenordnungen schneller als die Bilddaten zu laden und beantwortet die
    entscheidenden Fragen vorab: wie viele Frames, welche Bildgrößen, wie viel Speicher.
    """
    folder = Path(folder)
    infos: list[FitsInfo] = []
    unreadable: list[tuple[Path, str]] = []

    for path in find_fits_files(folder):
        try:
            header = fits.getheader(path)
            shape, n_planes = _shape_after_mono(header)
            infos.append(
                FitsInfo(
                    path=path,
                    shape=shape,
                    n_planes=n_planes,
                    obs_time=header.get("DATE-OBS"),
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


def load_fits_frame(path: Path) -> FitsFrame:
    with fits.open(path) as hdul:
        hdu = next(h for h in hdul if h.data is not None)
        data = np.asarray(to_mono(hdu.data), dtype=np.float32)
        header = hdu.header
        try:
            wcs = WCS(header)
            wcs = wcs if wcs.has_celestial else None
        except Exception:
            wcs = None
        obs_time = header.get("DATE-OBS")
    return FitsFrame(path=Path(path), data=data, header=header, wcs=wcs, obs_time=obs_time)


def load_frame_stack(
    folder: Path,
    max_frames: int | None = None,
    memory_budget_bytes: int = DEFAULT_MEMORY_BUDGET_BYTES,
) -> FrameStack:
    scan = scan_folder(folder)
    selected = select_frames_to_load(
        scan, max_frames=max_frames, memory_budget_bytes=memory_budget_bytes
    )
    return FrameStack(frames=[load_fits_frame(info.path) for info in selected])


def stretch_to_uint8(data: np.ndarray, low_pct: float = 1.0, high_pct: float = 99.5) -> np.ndarray:
    """Percentile-basiertes Histogram-Stretch nach 0-255 uint8."""
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        return np.zeros_like(data, dtype=np.uint8)
    lo, hi = np.percentile(finite, [low_pct, high_pct])
    if hi <= lo:
        hi = lo + 1.0
    clipped = np.clip((np.nan_to_num(data, nan=lo) - lo) / (hi - lo), 0.0, 1.0)
    return (clipped * 255).astype(np.uint8)


def make_thumbnail(data: np.ndarray, size: int = 128) -> np.ndarray:
    """Downsampled, gestrecktes Vorschaubild (uint8) mit max. Kantenlänge `size`."""
    h, w = data.shape[-2:]
    step = max(1, max(h, w) // size)
    return stretch_to_uint8(data[::step, ::step])
