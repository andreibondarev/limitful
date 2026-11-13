"""Local storage: raw flash pages in SQLite, audio exported as Ogg Opus files.

Raw page bytes are the source of truth. Audio files are derived from them, so a
bug in audio extraction can be fixed and the export re-run without the pendant.

Pages are identified by a hash of their content, not by their index: the
pendant restarts its page and session counters from zero when it is reset
(entering pairing mode does this), so an index can be reused for new audio.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .ogg import packet_samples, write_ogg_opus
from .protocol import MIN_VALID_TIMESTAMP_MS, FlashPage, extract_opus_frames

# A jump this large between consecutive pages starts a new audio file.
SEGMENT_GAP_MS = 3000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id           INTEGER PRIMARY KEY,   -- arrival order = recording order
    hash         BLOB    NOT NULL UNIQUE,
    session      INTEGER NOT NULL,
    idx          INTEGER NOT NULL,
    timestamp_ms INTEGER NOT NULL,      -- pendant clock; not valid until it is set
    uptime_ms    INTEGER NOT NULL,      -- time since the pendant booted
    received_ms  INTEGER NOT NULL,
    raw          BLOB    NOT NULL,
    exported     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS segments (
    path        TEXT PRIMARY KEY,
    start_ms    INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    first_page  INTEGER NOT NULL,
    last_page   INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class Segment:
    path: Path
    start_ms: int
    duration_ms: int


def _resolve_times(rows: list[tuple]) -> list[int]:
    """Wall-clock start time for each row of (timestamp_ms, uptime_ms, received_ms).

    Pages recorded before the clock was set only carry time-since-boot. Recover
    their wall time from the nearest page of the same boot that has both.
    """
    def valid(i: int) -> bool:
        return rows[i][0] >= MIN_VALID_TIMESTAMP_MS

    times = []
    for i, (ts, uptime, received) in enumerate(rows):
        if valid(i):
            times.append(ts)
            continue
        resolved = received
        for j in range(i + 1, len(rows)):  # later page, same boot: uptime keeps rising
            if rows[j][1] < uptime:
                break
            if valid(j):
                resolved = rows[j][0] - rows[j][1] + uptime
                break
        else:
            for j in range(i - 1, -1, -1):
                if rows[j][1] > uptime:
                    break
                if valid(j):
                    resolved = rows[j][0] - rows[j][1] + uptime
                    break
        times.append(resolved)
    return times


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.data_dir / "pendant.db")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")  # commit() must mean "on disk"
        self.db.executescript(_SCHEMA)

    def close(self) -> None:
        self.db.close()

    def add_page(self, page: FlashPage) -> bool:
        """Queue a page for the next commit. Returns False if already stored."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO pages "
            "(hash, session, idx, timestamp_ms, uptime_ms, received_ms, raw) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                hashlib.sha256(page.data).digest(),
                page.session,
                page.index,
                page.timestamp_ms,
                page.uptime_ms,
                int(time.time() * 1000),
                page.data,
            ),
        )
        return cur.rowcount > 0

    def commit(self) -> None:
        self.db.commit()

    def page_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]

    def export_audio(self) -> list[Segment]:
        """Write not-yet-exported pages as Ogg Opus files, split at gaps."""
        rows = self.db.execute(
            "SELECT id, idx, timestamp_ms, uptime_ms, received_ms, raw FROM pages "
            "WHERE exported = 0 ORDER BY id"
        ).fetchall()
        times = _resolve_times([(r[2], r[3], r[4]) for r in rows])

        segments: list[Segment] = []
        current: dict | None = None

        def finish() -> None:
            nonlocal current
            if current is None:
                return
            seg = current
            current = None
            start = datetime.fromtimestamp(seg["start_ms"] / 1000)
            rel = Path("audio") / start.strftime("%Y-%m-%d") / (
                f"{start.strftime('%H-%M-%S')}_{seg['first_page']}.ogg"
            )
            path = self.data_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                duration_ms = write_ogg_opus(f, seg["frames"])
            self.db.execute(
                "INSERT OR REPLACE INTO segments VALUES (?, ?, ?, ?, ?)",
                (str(rel), seg["start_ms"], duration_ms, seg["first_page"], seg["last_page"]),
            )
            segments.append(Segment(path, seg["start_ms"], duration_ms))

        for (page_id, idx, _ts, _uptime, _received, raw), ts in zip(rows, times):
            frames = extract_opus_frames(raw)
            if not frames:
                continue  # diagnostic page, or audio we could not parse; raw is kept
            if current is not None:
                expected = current["start_ms"] + current["samples"] // 48
                contiguous = (
                    idx == current["last_idx"] + 1
                    and abs(ts - expected) <= SEGMENT_GAP_MS
                )
                if not contiguous:
                    finish()
            if current is None:
                current = {"first_page": page_id, "start_ms": ts, "frames": [], "samples": 0}
            current["frames"].extend(frames)
            current["samples"] += sum(packet_samples(f) for f in frames)
            current["last_idx"] = idx
            current["last_page"] = page_id
        finish()

        self.db.execute("UPDATE pages SET exported = 1 WHERE exported = 0")
        self.db.commit()
        return segments
