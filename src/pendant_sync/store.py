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
from typing import Callable

from .ogg import packet_samples, write_ogg_opus
from .protocol import MIN_VALID_TIMESTAMP_MS, FlashPage, extract_opus_frames
from .transcribe import Transcriber

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
CREATE TABLE IF NOT EXISTS transcriptions (
    segment        TEXT PRIMARY KEY,    -- segments.path
    engine         TEXT NOT NULL,
    transcribed_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS utterances (
    id       INTEGER PRIMARY KEY,
    segment  TEXT    NOT NULL,          -- segments.path
    start_ms INTEGER NOT NULL,          -- wall-clock time
    end_ms   INTEGER NOT NULL,
    text     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS utterances_start ON utterances (start_ms);
"""

# Too short to hold a word; Whisper only produces noise on these.
MIN_TRANSCRIBE_MS = 500


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

    def pending_transcription(self) -> list[tuple[str, int, int]]:
        """(path, start_ms, duration_ms) of audio files not yet transcribed."""
        return self.db.execute(
            "SELECT path, start_ms, duration_ms FROM segments "
            "WHERE path NOT IN (SELECT segment FROM transcriptions) ORDER BY start_ms"
        ).fetchall()

    def transcribe_pending(
        self,
        transcriber: Transcriber,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[int, list[Path]]:
        """Transcribe new audio files. Returns (utterances added, transcript files written)."""
        pending = self.pending_transcription()
        added = 0
        days: set[str] = set()
        for n, (path, start_ms, duration_ms) in enumerate(pending, 1):
            utterances = []
            if duration_ms >= MIN_TRANSCRIBE_MS:
                utterances = transcriber.transcribe(self.data_dir / path)
            # Replace rather than append, so an interrupted run cannot duplicate text.
            self.db.execute("DELETE FROM utterances WHERE segment = ?", (path,))
            self.db.executemany(
                "INSERT INTO utterances (segment, start_ms, end_ms, text) VALUES (?, ?, ?, ?)",
                [(path, start_ms + u.start_ms, start_ms + u.end_ms, u.text) for u in utterances],
            )
            self.db.execute(
                "INSERT OR REPLACE INTO transcriptions VALUES (?, ?, ?)",
                (path, transcriber.name, int(time.time() * 1000)),
            )
            self.db.commit()
            added += len(utterances)
            if utterances:
                days.add(datetime.fromtimestamp(start_ms / 1000).strftime("%Y-%m-%d"))
            if on_progress:
                on_progress(n, len(pending))
        return added, [self.write_transcript(day) for day in sorted(days)]

    def write_transcript(self, day: str) -> Path:
        """Rewrite the Markdown transcript for one local-time day (YYYY-MM-DD)."""
        start = datetime.strptime(day, "%Y-%m-%d")
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(start.replace(hour=23, minute=59, second=59).timestamp() * 1000) + 1000
        rows = self.db.execute(
            "SELECT start_ms, text FROM utterances WHERE start_ms >= ? AND start_ms < ? "
            "ORDER BY start_ms, id",
            (start_ms, end_ms),
        ).fetchall()
        lines = [f"# {day}", ""]
        for ts, text in rows:
            clock = datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")
            lines.append(f"- **{clock}** {text}")
        path = self.data_dir / "transcripts" / f"{day}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
        return path
