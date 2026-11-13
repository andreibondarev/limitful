"""Local storage: raw flash pages in SQLite, audio exported as Ogg Opus files.

Raw page bytes are the source of truth. Audio files are derived from them, so a
bug in audio extraction can be fixed and the export re-run without the pendant.
"""

from __future__ import annotations

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
    session      INTEGER NOT NULL,
    idx          INTEGER NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    received_ms  INTEGER NOT NULL,
    raw          BLOB    NOT NULL,
    exported     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session, idx)
);
CREATE TABLE IF NOT EXISTS segments (
    path        TEXT PRIMARY KEY,
    start_ms    INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    session     INTEGER NOT NULL,
    first_idx   INTEGER NOT NULL,
    last_idx    INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class Segment:
    path: Path
    start_ms: int
    duration_ms: int


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
        if page.index is None:
            raise ValueError("page has no index")
        cur = self.db.execute(
            "INSERT OR IGNORE INTO pages (session, idx, timestamp_ms, received_ms, raw) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                page.session if page.session is not None else -1,
                page.index,
                page.timestamp_ms,
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
            "SELECT session, idx, timestamp_ms, received_ms, raw FROM pages "
            "WHERE exported = 0 ORDER BY session, idx"
        ).fetchall()

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
                f"{start.strftime('%H-%M-%S')}_s{seg['session']}_p{seg['first_idx']}.ogg"
            )
            path = self.data_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                duration_ms = write_ogg_opus(f, seg["frames"])
            self.db.execute(
                "INSERT OR REPLACE INTO segments VALUES (?, ?, ?, ?, ?, ?)",
                (str(rel), seg["start_ms"], duration_ms, seg["session"],
                 seg["first_idx"], seg["last_idx"]),
            )
            segments.append(Segment(path, seg["start_ms"], duration_ms))

        for session, idx, timestamp_ms, received_ms, raw in rows:
            frames = extract_opus_frames(raw)
            if not frames:
                continue  # diagnostic page, or audio we could not parse; raw is kept
            ts = timestamp_ms if timestamp_ms >= MIN_VALID_TIMESTAMP_MS else received_ms
            if current is not None:
                expected = current["start_ms"] + current["samples"] // 48
                contiguous = (
                    session == current["session"]
                    and idx == current["last_idx"] + 1
                    and abs(ts - expected) <= SEGMENT_GAP_MS
                )
                if not contiguous:
                    finish()
            if current is None:
                current = {"session": session, "first_idx": idx, "start_ms": ts,
                           "frames": [], "samples": 0}
            current["frames"].extend(frames)
            current["samples"] += sum(packet_samples(f) for f in frames)
            current["last_idx"] = idx
        finish()

        self.db.execute("UPDATE pages SET exported = 1 WHERE exported = 0")
        self.db.commit()
        return segments
