"""Local storage: raw flash pages in SQLite, audio exported as Ogg Opus files.

Raw page bytes are the source of truth. Audio files are derived from them, so a
bug in audio extraction can be fixed and the export re-run without the pendant.

Pages are identified by a hash of their content, not by their index: the
pendant restarts its page and session counters from zero when it is reset
(entering pairing mode does this), so an index can be reused for new audio.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import numpy as np

from .digest import DigestDeclined, Summarizer
from .ogg import packet_samples, write_ogg_opus
from .protocol import MIN_VALID_TIMESTAMP_MS, FlashPage, extract_opus_frames
from .speakers import MATCH_THRESHOLD, MIN_FINGERPRINTS, MIN_SPEAKER_MS, SAMPLE_RATE, Embedder
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
CREATE TABLE IF NOT EXISTS speakers (
    id        INTEGER PRIMARY KEY,
    name      TEXT    NOT NULL,
    voice_sum BLOB    NOT NULL,         -- sum of this speaker's fingerprints
    lines     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id       INTEGER PRIMARY KEY,
    start_ms INTEGER NOT NULL,
    end_ms   INTEGER NOT NULL,
    status   TEXT    NOT NULL,          -- pending, done, short (too little said), skipped
    title    TEXT,
    summary  TEXT,                      -- JSON list of sentences
    engine   TEXT
);
CREATE INDEX IF NOT EXISTS conversations_start ON conversations (start_ms);
CREATE TABLE IF NOT EXISTS reminders (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL,
    text            TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'suggested',  -- suggested, accepted, done, dismissed
    created_ms      INTEGER NOT NULL
);
"""

# A silence this long ends a conversation.
CONVERSATION_GAP_MS = 5 * 60 * 1000
# Conversations with fewer words than this are not worth summarising.
MIN_DIGEST_WORDS = 25
REMINDER_STATUSES = ("suggested", "accepted", "done", "dismissed")

# Columns added after the first release; applied to existing databases on open.
_MIGRATIONS = [
    ("utterances", "embedding", "BLOB"),       # voice fingerprint, float32
    ("utterances", "speaker_id", "INTEGER"),
]

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
        # Transcription runs in a worker thread; callers never use the store from
        # two threads at once, so sharing one connection is safe.
        self.db = sqlite3.connect(self.data_dir / "pendant.db", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")  # commit() must mean "on disk"
        self.db.executescript(_SCHEMA)
        for table, column, kind in _MIGRATIONS:
            have = {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        self.db.commit()

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

    def forget_transcriptions(self) -> None:
        """Mark every audio file as not transcribed, so the next run redoes them."""
        self.db.execute("DELETE FROM transcriptions")
        self.db.commit()

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
            # Rewrite the day even with no lines: a redo can leave it with fewer.
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
            "SELECT u.start_ms, u.text, s.name FROM utterances u "
            "LEFT JOIN speakers s ON s.id = u.speaker_id "
            "WHERE u.start_ms >= ? AND u.start_ms < ? ORDER BY u.start_ms, u.id",
            (start_ms, end_ms),
        ).fetchall()
        digests = self.db.execute(
            "SELECT start_ms, end_ms, title, summary FROM conversations "
            "WHERE status = 'done' AND end_ms >= ? AND start_ms < ? ORDER BY start_ms",
            (start_ms, end_ms),
        ).fetchall()
        lines = [f"# {day}", ""]
        for ts, text, speaker in rows:
            clock = datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")
            while digests and digests[0][0] <= ts:
                d_start, d_end, title, summary = digests.pop(0)
                if ts > d_end:
                    continue
                lines += ["", f"## {clock[:5]} {title}", ""]
                lines += [f"> {point}" for point in json.loads(summary or "[]")]
                lines.append("")
            who = f"{speaker}: " if speaker else ""
            lines.append(f"- **{clock}** {who}{text}")
        path = self.data_dir / "transcripts" / f"{day}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
        return path

    # --- speakers ---------------------------------------------------------------

    def _rewrite_days(self, where: str, params: tuple) -> list[Path]:
        days = {
            datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")
            for (ms,) in self.db.execute(f"SELECT start_ms FROM utterances WHERE {where}", params)
        }
        return [self.write_transcript(day) for day in sorted(days)]

    def label_speakers(self, embedder: Embedder, load_audio: Callable[[Path], "np.ndarray"]) -> int:
        """Fingerprint new lines and group them into speakers. Returns lines labelled."""
        import numpy as np

        todo = self.db.execute(
            "SELECT u.id, u.segment, u.start_ms - s.start_ms, u.end_ms - u.start_ms "
            "FROM utterances u JOIN segments s ON s.path = u.segment "
            "WHERE u.embedding IS NULL AND u.end_ms - u.start_ms >= ? ORDER BY u.segment",
            (MIN_SPEAKER_MS,),
        ).fetchall()
        loaded: tuple[str, "np.ndarray"] | None = None
        for uid, segment, offset_ms, duration_ms in todo:
            if loaded is None or loaded[0] != segment:
                loaded = (segment, load_audio(self.data_dir / segment))
            first = offset_ms * SAMPLE_RATE // 1000
            clip = loaded[1][first : first + duration_ms * SAMPLE_RATE // 1000]
            if len(clip) < MIN_SPEAKER_MS * SAMPLE_RATE // 1000:
                continue  # the file is shorter than the transcript claims
            voice = np.asarray(embedder.embed(clip), dtype=np.float32)
            self.db.execute("UPDATE utterances SET embedding = ? WHERE id = ?", (voice.tobytes(), uid))
        self.db.commit()
        return self._assign_speakers()

    def _assign_speakers(self) -> int:
        import numpy as np

        (count,) = self.db.execute(
            "SELECT COUNT(*) FROM utterances WHERE embedding IS NOT NULL").fetchone()
        if count < MIN_FINGERPRINTS:
            return 0
        pending = self.db.execute(
            "SELECT id, embedding FROM utterances "
            "WHERE embedding IS NOT NULL AND speaker_id IS NULL ORDER BY start_ms, id"
        ).fetchall()
        if not pending:
            return 0

        def unit(v):
            norm = np.linalg.norm(v)
            return v / norm if norm else v

        # The average fingerprint is mostly the pendant's microphone and the
        # room, not anyone's voice. Subtracting it is what makes voices separable.
        total = np.zeros(0, dtype=np.float64)
        for (blob,) in self.db.execute("SELECT embedding FROM utterances WHERE embedding IS NOT NULL"):
            v = np.frombuffer(blob, dtype=np.float32)
            total = v.astype(np.float64) if not total.size else total + v
        mean = total / count

        speakers = {
            sid: [np.frombuffer(blob, dtype=np.float32).astype(np.float64), lines]
            for sid, blob, lines in self.db.execute("SELECT id, voice_sum, lines FROM speakers")
        }
        for uid, blob in pending:
            voice = np.frombuffer(blob, dtype=np.float32).astype(np.float64)
            centred = unit(voice - mean)
            best, best_score = None, MATCH_THRESHOLD
            for sid, (voice_sum, lines) in speakers.items():
                score = float(centred @ unit(voice_sum / lines - mean))
                if score >= best_score:
                    best, best_score = sid, score
            if best is None:
                cur = self.db.execute(
                    "INSERT INTO speakers (name, voice_sum, lines) VALUES ('', ?, 0)",
                    (np.zeros_like(voice, dtype=np.float32).tobytes(),))
                best = cur.lastrowid
                self.db.execute("UPDATE speakers SET name = ? WHERE id = ?", (f"Speaker {best}", best))
                speakers[best] = [np.zeros_like(voice), 0]
            speakers[best][0] = speakers[best][0] + voice
            speakers[best][1] += 1
            self.db.execute("UPDATE utterances SET speaker_id = ? WHERE id = ?", (best, uid))
        for sid, (voice_sum, lines) in speakers.items():
            self.db.execute("UPDATE speakers SET voice_sum = ?, lines = ? WHERE id = ?",
                            (voice_sum.astype(np.float32).tobytes(), lines, sid))
        self.db.commit()
        ids = [uid for uid, _ in pending]
        marks = ",".join("?" * len(ids))
        self._rewrite_days(f"id IN ({marks})", tuple(ids))
        return len(pending)

    def speakers(self) -> list[tuple[int, str, int]]:
        """(id, name, lines) for every speaker, most lines first."""
        return self.db.execute(
            "SELECT id, name, lines FROM speakers ORDER BY lines DESC, id").fetchall()

    def rename_speaker(self, speaker_id: int, name: str) -> int:
        """Name a speaker. Giving it another speaker's name merges the two.

        Returns the id that now holds those lines.
        """
        import numpy as np

        name = " ".join(name.split())
        if not name:
            raise ValueError("a speaker needs a name")
        row = self.db.execute(
            "SELECT voice_sum, lines FROM speakers WHERE id = ?", (speaker_id,)).fetchone()
        if row is None:
            raise ValueError(f"there is no speaker {speaker_id}")
        other = self.db.execute(
            "SELECT id, voice_sum, lines FROM speakers WHERE id != ? AND name = ? COLLATE NOCASE",
            (speaker_id, name)).fetchone()
        keep = speaker_id
        if other is None:
            self.db.execute("UPDATE speakers SET name = ? WHERE id = ?", (name, speaker_id))
        else:
            keep = other[0]
            merged = np.frombuffer(other[1], dtype=np.float32) + np.frombuffer(row[0], dtype=np.float32)
            self.db.execute("UPDATE speakers SET voice_sum = ?, lines = ? WHERE id = ?",
                            (merged.tobytes(), other[2] + row[1], keep))
            self.db.execute("UPDATE utterances SET speaker_id = ? WHERE speaker_id = ?", (keep, speaker_id))
            self.db.execute("DELETE FROM speakers WHERE id = ?", (speaker_id,))
        self.db.commit()
        self._rewrite_days("speaker_id = ?", (keep,))
        return keep

    def reset_speakers(self) -> int:
        """Forget all speakers and group every stored fingerprint again."""
        self.db.execute("UPDATE utterances SET speaker_id = NULL")
        self.db.execute("DELETE FROM speakers")
        self.db.commit()
        labelled = self._assign_speakers()
        self._rewrite_days("embedding IS NOT NULL", ())
        return labelled

    # --- conversations, summaries and reminders ------------------------------------

    def build_conversations(self, now_ms: int | None = None) -> int:
        """Group lines newer than the last conversation into conversations.

        A conversation ends at a silence of CONVERSATION_GAP_MS. The most recent
        one is left alone until that much time has passed, in case it continues.
        """
        now_ms = int(time.time() * 1000) if now_ms is None else now_ms
        (after,) = self.db.execute("SELECT COALESCE(MAX(end_ms), 0) FROM conversations").fetchone()
        rows = self.db.execute(
            "SELECT start_ms, end_ms FROM utterances WHERE start_ms > ? ORDER BY start_ms, id",
            (after,),
        ).fetchall()
        groups: list[list[int]] = []
        for start, end in rows:
            if groups and start - groups[-1][1] <= CONVERSATION_GAP_MS:
                groups[-1][1] = max(groups[-1][1], end)
            else:
                groups.append([start, end])
        if groups and now_ms - groups[-1][1] <= CONVERSATION_GAP_MS:
            groups.pop()  # may still be going on
        self.db.executemany(
            "INSERT INTO conversations (start_ms, end_ms, status) VALUES (?, ?, 'pending')", groups)
        self.db.commit()
        return len(groups)

    def conversation_text(self, start_ms: int, end_ms: int) -> tuple[str, int]:
        """The transcript handed to the summariser, and how many words were said."""
        rows = self.db.execute(
            "SELECT u.start_ms, u.text, s.name FROM utterances u "
            "LEFT JOIN speakers s ON s.id = u.speaker_id "
            "WHERE u.start_ms >= ? AND u.start_ms <= ? ORDER BY u.start_ms, u.id",
            (start_ms, end_ms),
        ).fetchall()
        transcript = "\n".join(
            f"[{datetime.fromtimestamp(ts / 1000).strftime('%H:%M')}] {name or 'Unknown'}: {text}"
            for ts, text, name in rows
        )
        return transcript, sum(len(text.split()) for _ts, text, _name in rows)

    def digest_pending(
        self,
        summarizer: Summarizer,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Title, summarise and extract reminders for new conversations.

        Returns how many were summarised. A DigestError from the engine stops the
        run and leaves the rest pending for next time.
        """
        self.build_conversations()
        pending = self.db.execute(
            "SELECT id, start_ms, end_ms FROM conversations WHERE status = 'pending' ORDER BY start_ms"
        ).fetchall()
        done = 0
        for n, (cid, start_ms, end_ms) in enumerate(pending, 1):
            text, words = self.conversation_text(start_ms, end_ms)
            if words < MIN_DIGEST_WORDS:
                self.db.execute("UPDATE conversations SET status = 'short' WHERE id = ?", (cid,))
            else:
                try:
                    result = summarizer.summarize(text)
                except DigestDeclined:
                    self.db.execute("UPDATE conversations SET status = 'skipped' WHERE id = ?", (cid,))
                else:
                    self.db.execute(
                        "UPDATE conversations SET status = 'done', title = ?, summary = ?, engine = ? "
                        "WHERE id = ?",
                        (result["title"], json.dumps(result["summary"]), summarizer.name, cid))
                    self.db.executemany(
                        "INSERT INTO reminders (conversation_id, text, created_ms) VALUES (?, ?, ?)",
                        [(cid, r, start_ms) for r in result["reminders"]])
                    done += 1
            self.db.commit()
            self._rewrite_days("start_ms >= ? AND start_ms <= ?", (start_ms, end_ms))
            if on_progress:
                on_progress(n, len(pending))
        return done

    def forget_digests(self) -> None:
        """Drop every conversation, summary and reminder so they can be rebuilt."""
        self.db.execute("DELETE FROM conversations")
        self.db.execute("DELETE FROM reminders")
        self.db.commit()
        self._rewrite_days("1 = 1", ())

    def conversations(self, lo_ms: int, hi_ms: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, start_ms, end_ms, title, summary FROM conversations "
            "WHERE status = 'done' AND start_ms >= ? AND start_ms < ? ORDER BY start_ms",
            (lo_ms, hi_ms),
        ).fetchall()
        out = []
        for cid, start_ms, end_ms, title, summary in rows:
            out.append({
                "id": cid, "start": start_ms, "end": end_ms, "title": title,
                "summary": json.loads(summary or "[]"),
                "reminders": [
                    {"id": rid, "text": text, "status": status}
                    for rid, text, status in self.db.execute(
                        "SELECT id, text, status FROM reminders WHERE conversation_id = ? ORDER BY id",
                        (cid,))
                ],
            })
        return out

    def reminders(self) -> list[dict]:
        """Reminders still worth showing: suggested and accepted, newest first."""
        rows = self.db.execute(
            "SELECT r.id, r.text, r.status, r.created_ms, c.title FROM reminders r "
            "JOIN conversations c ON c.id = r.conversation_id "
            "WHERE r.status IN ('suggested', 'accepted') ORDER BY r.created_ms DESC, r.id"
        ).fetchall()
        return [{"id": rid, "text": text, "status": status, "when": when, "from": title}
                for rid, text, status, when, title in rows]

    def set_reminder_status(self, reminder_id: int, status: str) -> None:
        if status not in REMINDER_STATUSES:
            raise ValueError(f"status must be one of {', '.join(REMINDER_STATUSES)}")
        cur = self.db.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
        if cur.rowcount == 0:
            raise ValueError(f"there is no reminder {reminder_id}")
        self.db.commit()
