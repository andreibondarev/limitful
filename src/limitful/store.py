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
CREATE TABLE IF NOT EXISTS imports (
    key TEXT PRIMARY KEY               -- one row per imported file, so imports can be re-run
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
CREATE TABLE IF NOT EXISTS sections (
    id              INTEGER PRIMARY KEY,
    conversation_id INTEGER NOT NULL,
    start_ms        INTEGER NOT NULL,   -- the first line under this heading
    level           INTEGER NOT NULL,   -- 2 for a section, 3 for a subsection
    title           TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS sections_conversation ON sections (conversation_id);
CREATE TABLE IF NOT EXISTS chats (
    id         INTEGER PRIMARY KEY,
    title      TEXT    NOT NULL,        -- the first question, shortened
    created_ms INTEGER NOT NULL,
    updated_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id         INTEGER PRIMARY KEY,
    chat_id    INTEGER NOT NULL,
    role       TEXT    NOT NULL,        -- user or assistant
    content    TEXT    NOT NULL,
    lines      TEXT,                    -- JSON: where each cited line is, for an answer
    created_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_messages_chat ON chat_messages (chat_id);
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
    ("utterances", "source", "TEXT"),          # imported conversation this line came from
    ("utterances", "source_speaker", "TEXT"),  # that import's own label for who spoke
    ("reminders", "utterance_id", "INTEGER"),  # the line a reminder came from, when known
]

_COMMON_WORDS = frozenset("""
a about after again all also an and any are as ask at be been before but buy by call can check
could did do does don for from get go going got had has have he her here him his how i if in
into is it its just know let like look make me more my need no not now of on one or our out
over said say see she should so some take tell than that the their them then there these they
thing things think this to too try up us very want was we well were what when where which
who why will with would yeah you your
""".split())


def _stems(text: str) -> set[str]:
    """Content words of a phrase, cut to a rough stem so "spraying" meets "spray"."""
    words = "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
    return {w[:5] for w in words if len(w) >= 3 and w not in _COMMON_WORDS}


def best_matching_line(phrase: str, lines: list[tuple[int, str]]) -> int | None:
    """The id of the line a reminder most plausibly came from, or None if unclear.

    Words that are rare in the conversation count for more. A match needs two
    shared content words, or one that appears in a single line only.
    """
    import math

    wanted = _stems(phrase)
    if not wanted or not lines:
        return None
    stems = [(line_id, _stems(text)) for line_id, text in lines]
    seen: dict[str, int] = {}
    for _id, found in stems:
        for stem in found:
            seen[stem] = seen.get(stem, 0) + 1
    best, best_score = None, 0.0
    for line_id, found in stems:
        shared = wanted & found
        if not shared:
            continue
        if len(shared) < 2 and not any(seen[stem] == 1 and len(stem) >= 5 for stem in shared):
            continue
        score = sum(math.log(1 + len(lines) / seen[stem]) for stem in shared)
        if score > best_score:
            best, best_score = line_id, score
    return best

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
        added = set()
        for table, column, kind in _MIGRATIONS:
            have = {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
                added.add((table, column))
        self.db.commit()
        if ("reminders", "utterance_id") in added:
            self.link_reminders_to_lines()  # reminders saved before lines were tracked

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
            "SELECT u.start_ms, u.text, COALESCE(s.name, 'Speaker ' || u.source_speaker) "
            "FROM utterances u LEFT JOIN speakers s ON s.id = u.speaker_id "
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

    def rewrite_all_transcripts(self) -> list[Path]:
        return self._rewrite_days("1 = 1", ())

    def label_speakers(self, embedder: Embedder, load_audio: Callable[[Path], "np.ndarray"]) -> int:
        """Fingerprint new lines and group them into speakers. Returns lines labelled."""
        import numpy as np

        todo = self.db.execute(
            "SELECT u.id, u.segment, u.start_ms - s.start_ms, u.end_ms - u.start_ms "
            "FROM utterances u JOIN segments s ON s.path = u.segment "
            "WHERE u.embedding IS NULL AND u.source IS NULL AND u.end_ms - u.start_ms >= ? "
            "ORDER BY u.segment",
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
            self.db.commit()  # keep write locks short: the Lifelog may be saving too
        return self._assign_speakers()

    def _voice_book(self):
        """(average fingerprint, {speaker id: [sum of fingerprints, count]}), or None.

        Speaker centroids are worked out from the lines assigned to each speaker,
        so merging or reassigning lines never leaves a stale centroid behind.
        """
        import numpy as np

        rows = self.db.execute(
            "SELECT speaker_id, embedding FROM utterances WHERE embedding IS NOT NULL").fetchall()
        if len(rows) < MIN_FINGERPRINTS:
            return None
        total = None
        sums: dict[int, list] = {}
        for speaker_id, blob in rows:
            voice = np.frombuffer(blob, dtype=np.float32).astype(np.float64)
            total = voice if total is None else total + voice
            if speaker_id is not None:
                entry = sums.setdefault(speaker_id, [np.zeros_like(voice), 0])
                entry[0] = entry[0] + voice
                entry[1] += 1
        # The average fingerprint is mostly the microphone and the room, not
        # anyone's voice. Subtracting it is what makes voices separable.
        return total / len(rows), sums

    @staticmethod
    def _match(voice, book, exclude=()) -> int | None:
        """The known speaker this fingerprint belongs to, if any is close enough."""
        import numpy as np

        mean, sums = book

        def unit(v):
            norm = np.linalg.norm(v)
            return v / norm if norm else v

        centred = unit(voice - mean)
        best, best_score = None, MATCH_THRESHOLD
        for speaker_id, (voice_sum, count) in sums.items():
            if speaker_id in exclude or not count:
                continue
            score = float(centred @ unit(voice_sum / count - mean))
            if score >= best_score:
                best, best_score = speaker_id, score
        return best

    def _new_speaker(self, name: str | None = None) -> int:
        cur = self.db.execute("INSERT INTO speakers (name, voice_sum, lines) VALUES ('', x'', 0)")
        speaker_id = cur.lastrowid
        self.db.execute("UPDATE speakers SET name = ? WHERE id = ?",
                        (name or f"Speaker {speaker_id}", speaker_id))
        return speaker_id

    def _assign_speakers(self) -> int:
        """Group fingerprinted lines recorded from the pendant into speakers."""
        import numpy as np

        book = self._voice_book()
        if book is None:
            return 0
        pending = self.db.execute(
            "SELECT id, embedding FROM utterances WHERE embedding IS NOT NULL "
            "AND speaker_id IS NULL AND source IS NULL ORDER BY start_ms, id"
        ).fetchall()
        for uid, blob in pending:
            voice = np.frombuffer(blob, dtype=np.float32).astype(np.float64)
            speaker_id = self._match(voice, book)
            if speaker_id is None:
                speaker_id = self._new_speaker()
            entry = book[1].setdefault(speaker_id, [np.zeros_like(voice), 0])
            entry[0] = entry[0] + voice
            entry[1] += 1
            self.db.execute("UPDATE utterances SET speaker_id = ? WHERE id = ?", (speaker_id, uid))
        self.db.commit()
        if pending:
            marks = ",".join("?" * len(pending))
            self._rewrite_days(f"id IN ({marks})", tuple(uid for uid, _ in pending))
        return len(pending)

    # Imported conversations already say which lines share a speaker, so a few
    # long lines per speaker are enough to recognise the voice.
    _PICKS_PER_SPEAKER = 5
    _PICK_MAX_MS = 15000

    def link_imported_speakers(
        self,
        embedder: Embedder,
        load_audio: Callable[[Path], "np.ndarray"],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[int, int]:
        """Link the per-conversation speakers of imported conversations to people.

        Returns (speakers linked, conversations where the closest voice was already
        taken by another speaker of the same conversation).
        """
        import numpy as np

        # Every imported speaker without a fingerprint yet, including ones the user
        # has already named: a named voice is what the others get matched against.
        groups = self.db.execute(
            "SELECT source, source_speaker FROM utterances "
            "WHERE source IS NOT NULL AND source_speaker != '' "
            "GROUP BY source, source_speaker HAVING SUM(embedding IS NOT NULL) = 0").fetchall()
        picks = []
        for source, label in groups:
            picks += self.db.execute(
                "SELECT u.id, u.segment, u.start_ms - s.start_ms, u.end_ms - u.start_ms "
                "FROM utterances u JOIN segments s ON s.path = u.segment "
                "WHERE u.source = ? AND u.source_speaker = ? AND u.end_ms - u.start_ms >= ? "
                "AND u.embedding IS NULL ORDER BY u.end_ms - u.start_ms DESC LIMIT ?",
                (source, label, MIN_SPEAKER_MS, self._PICKS_PER_SPEAKER)).fetchall()
        picks.sort(key=lambda row: row[1])  # one decode per audio file
        loaded: tuple[str, "np.ndarray"] | None = None
        for n, (uid, segment, offset_ms, duration_ms) in enumerate(picks, 1):
            if loaded is None or loaded[0] != segment:
                loaded = (segment, load_audio(self.data_dir / segment))
            first = max(0, offset_ms) * SAMPLE_RATE // 1000
            clip = loaded[1][first : first + min(duration_ms, self._PICK_MAX_MS) * SAMPLE_RATE // 1000]
            if len(clip) >= MIN_SPEAKER_MS * SAMPLE_RATE // 1000:
                voice = np.asarray(embedder.embed(clip), dtype=np.float32)
                self.db.execute("UPDATE utterances SET embedding = ? WHERE id = ?", (voice.tobytes(), uid))
                self.db.commit()  # keep write locks short: the Lifelog may be saving too
            if on_progress:
                on_progress(n, len(picks))
        return self._link_imported()

    def _link_imported(self) -> tuple[int, int]:
        import numpy as np

        book = self._voice_book()
        if book is None:
            return 0, 0
        taken: dict[str, set[int]] = {}
        for source, speaker_id in self.db.execute(
                "SELECT DISTINCT source, speaker_id FROM utterances "
                "WHERE source IS NOT NULL AND speaker_id IS NOT NULL"):
            taken.setdefault(source, set()).add(speaker_id)
        # Speakers who said the most first: their fingerprints are the most reliable.
        groups = self.db.execute(
            "SELECT source, source_speaker FROM utterances "
            "WHERE source IS NOT NULL AND source_speaker != '' AND speaker_id IS NULL "
            "GROUP BY source, source_speaker ORDER BY SUM(end_ms - start_ms) DESC").fetchall()
        linked = conflicts = 0
        for source, label in groups:
            voices = [np.frombuffer(blob, dtype=np.float32).astype(np.float64)
                      for (blob,) in self.db.execute(
                          "SELECT embedding FROM utterances WHERE source = ? AND source_speaker = ? "
                          "AND embedding IS NOT NULL", (source, label))]
            if not voices:
                continue  # no audio, or nothing long enough to judge
            voice = sum(voices) / len(voices)
            used = taken.setdefault(source, set())
            # Two speakers of one conversation are different people, whatever the voices say.
            speaker_id = self._match(voice, book, exclude=used)
            if used and self._match(voice, book) in used:
                conflicts += 1
            if speaker_id is None:
                speaker_id = self._new_speaker()
            entry = book[1].setdefault(speaker_id, [np.zeros_like(voice), 0])
            entry[0] = entry[0] + sum(voices)
            entry[1] += len(voices)
            used.add(speaker_id)
            self.db.execute(
                "UPDATE utterances SET speaker_id = ? WHERE source = ? AND source_speaker = ?",
                (speaker_id, source, label))
            linked += 1
        self.db.commit()
        if linked:
            self.rewrite_all_transcripts()
        return linked, conflicts

    def unlink_imported_speakers(self) -> int:
        """Undo automatic linking: imported speakers that were never given a real
        name go back to their per-conversation labels. Named ones are kept.

        Returns how many per-conversation speakers were unlinked.
        """
        auto = "SELECT id FROM speakers WHERE name = 'Speaker ' || id"
        (count,) = self.db.execute(
            "SELECT COUNT(*) FROM (SELECT 1 FROM utterances WHERE source IS NOT NULL "
            f"AND speaker_id IN ({auto}) GROUP BY source, source_speaker)").fetchone()
        self.db.execute(
            f"UPDATE utterances SET speaker_id = NULL WHERE source IS NOT NULL AND speaker_id IN ({auto})")
        self.db.execute(
            "DELETE FROM speakers WHERE id NOT IN "
            "(SELECT speaker_id FROM utterances WHERE speaker_id IS NOT NULL)")
        self.db.commit()
        if count:
            self.rewrite_all_transcripts()
        return count

    def speakers(self) -> list[tuple[int, str, int]]:
        """(id, name, lines) for every speaker, most lines first."""
        return self.db.execute(
            "SELECT s.id, s.name, COUNT(u.id) FROM speakers s "
            "LEFT JOIN utterances u ON u.speaker_id = s.id "
            "GROUP BY s.id ORDER BY COUNT(u.id) DESC, s.id").fetchall()

    @staticmethod
    def _clean_name(name: str) -> str:
        name = " ".join(name.split())
        if not name:
            raise ValueError("a speaker needs a name")
        return name

    def rename_speaker(self, speaker_id: int, name: str) -> int:
        """Name a speaker everywhere. Giving it another speaker's name merges the two.

        Returns the id that now holds those lines.
        """
        name = self._clean_name(name)
        if self.db.execute("SELECT 1 FROM speakers WHERE id = ?", (speaker_id,)).fetchone() is None:
            raise ValueError(f"there is no speaker {speaker_id}")
        other = self.db.execute(
            "SELECT id FROM speakers WHERE id != ? AND name = ? COLLATE NOCASE",
            (speaker_id, name)).fetchone()
        keep = speaker_id
        if other is None:
            self.db.execute("UPDATE speakers SET name = ? WHERE id = ?", (name, speaker_id))
        else:
            keep = other[0]
            self.db.execute("UPDATE utterances SET speaker_id = ? WHERE speaker_id = ?", (keep, speaker_id))
            self.db.execute("DELETE FROM speakers WHERE id = ?", (speaker_id,))
        self.db.commit()
        self._rewrite_days("speaker_id = ?", (keep,))
        return keep

    def assign_line_speaker(self, utterance_id: int, name: str) -> int:
        """Say who spoke a line, here only.

        For an imported line this covers every line of the same speaker in that
        conversation; for a line recorded from the pendant, just that line. The
        name is matched to an existing speaker or creates a new one.
        """
        name = self._clean_name(name)
        row = self.db.execute(
            "SELECT source, source_speaker FROM utterances WHERE id = ?", (utterance_id,)).fetchone()
        if row is None:
            raise ValueError(f"there is no line {utterance_id}")
        found = self.db.execute(
            "SELECT id FROM speakers WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        target = found[0] if found else self._new_speaker(name)
        if row[0] and row[1]:
            where, params = "source = ? AND source_speaker = ?", (row[0], row[1])
        else:
            where, params = "id = ?", (utterance_id,)
        self.db.execute(f"UPDATE utterances SET speaker_id = ? WHERE {where}", (target, *params))
        # Drop speakers this left with no lines.
        self.db.execute(
            "DELETE FROM speakers WHERE id != ? AND id NOT IN "
            "(SELECT speaker_id FROM utterances WHERE speaker_id IS NOT NULL)", (target,))
        self.db.commit()
        self._rewrite_days(where, params)
        return target

    def reset_speakers(self) -> int:
        """Forget all speakers and names, and group every stored fingerprint again."""
        self.db.execute("UPDATE utterances SET speaker_id = NULL")
        self.db.execute("DELETE FROM speakers")
        self.db.commit()
        labelled = self._assign_speakers()
        self.rewrite_all_transcripts()
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

    def conversation_text(self, start_ms: int, end_ms: int) -> tuple[str, int, list[int]]:
        """The transcript handed to the summariser, how many words were said, and
        the id of each numbered line."""
        rows = self.db.execute(
            "SELECT u.id, u.start_ms, u.text, s.name FROM utterances u "
            "LEFT JOIN speakers s ON s.id = u.speaker_id "
            "WHERE u.start_ms >= ? AND u.start_ms <= ? ORDER BY u.start_ms, u.id",
            (start_ms, end_ms),
        ).fetchall()
        transcript = "\n".join(
            f"{n}. [{datetime.fromtimestamp(ts / 1000).strftime('%H:%M')}] {name or 'Unknown'}: {text}"
            for n, (_id, ts, text, name) in enumerate(rows, 1)
        )
        return transcript, sum(len(row[2].split()) for row in rows), [row[0] for row in rows]

    def link_reminders_to_lines(self) -> int:
        """Find the line each unlinked reminder came from, by its wording."""
        linked = 0
        rows = self.db.execute(
            "SELECT r.id, r.text, c.start_ms, c.end_ms FROM reminders r "
            "JOIN conversations c ON c.id = r.conversation_id WHERE r.utterance_id IS NULL").fetchall()
        for reminder_id, text, start_ms, end_ms in rows:
            lines = self.db.execute(
                "SELECT id, text FROM utterances WHERE start_ms >= ? AND start_ms <= ? "
                "ORDER BY start_ms, id", (start_ms, end_ms)).fetchall()
            line_id = best_matching_line(text, lines)
            if line_id is not None:
                self.db.execute("UPDATE reminders SET utterance_id = ? WHERE id = ?", (line_id, reminder_id))
                linked += 1
        self.db.commit()
        return linked

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
            text, words, line_ids = self.conversation_text(start_ms, end_ms)
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
                    for reminder in result["reminders"]:
                        # The model cites a line number; fall back to matching the wording.
                        if isinstance(reminder, str):
                            reminder = {"text": reminder, "line": None}
                        cited = reminder.get("line")
                        line_id = line_ids[cited - 1] if cited and 1 <= cited <= len(line_ids) else None
                        self.db.execute(
                            "INSERT INTO reminders (conversation_id, text, created_ms, utterance_id) "
                            "VALUES (?, ?, ?, ?)", (cid, reminder["text"], start_ms, line_id))
                    self.link_reminders_to_lines()
                    done += 1
            self.db.commit()
            self._rewrite_days("start_ms >= ? AND start_ms <= ?", (start_ms, end_ms))
            if on_progress:
                on_progress(n, len(pending))
        return done

    def forget_digests(self) -> None:
        """Drop every conversation, summary and reminder so they can be rebuilt."""
        # Imported conversations carry their own titles; only ours are rebuilt.
        ours = "SELECT id FROM conversations WHERE engine IS NOT 'limitless'"
        self.db.execute(f"DELETE FROM reminders WHERE conversation_id IN ({ours})")
        self.db.execute(f"DELETE FROM sections WHERE conversation_id IN ({ours})")
        self.db.execute("DELETE FROM conversations WHERE engine IS NOT 'limitless'")
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
            (line_count,) = self.db.execute(
                "SELECT COUNT(*) FROM utterances WHERE start_ms >= ? AND start_ms <= ?",
                (start_ms, end_ms)).fetchone()
            out.append({
                "id": cid, "start": start_ms, "end": end_ms, "title": title,
                "summary": json.loads(summary or "[]"),
                "lines": line_count,
                "sections": [
                    {"start": at, "level": level, "title": heading}
                    for at, level, heading in self.db.execute(
                        "SELECT start_ms, level, title FROM sections WHERE conversation_id = ? "
                        "ORDER BY start_ms, id", (cid,))
                ],
                "reminders": [
                    {"id": rid, "text": text, "status": status, "line": line_id}
                    for rid, text, status, line_id in self.db.execute(
                        "SELECT id, text, status, utterance_id FROM reminders "
                        "WHERE conversation_id = ? ORDER BY id", (cid,))
                ],
            })
        return out

    def reminders(self) -> list[dict]:
        """Reminders still worth showing: suggested and accepted, newest first."""
        rows = self.db.execute(
            "SELECT r.id, r.text, r.status, r.created_ms, c.title, c.id, c.start_ms, "
            "u.id, u.text, u.start_ms FROM reminders r "
            "JOIN conversations c ON c.id = r.conversation_id "
            "LEFT JOIN utterances u ON u.id = r.utterance_id "
            "WHERE r.status IN ('suggested', 'accepted') ORDER BY c.start_ms DESC, r.id"
        ).fetchall()
        out = []
        for rid, text, status, when, title, cid, c_start, line_id, line_text, line_start in rows:
            anchor = line_start if line_id else c_start
            out.append({
                "id": rid, "text": text, "status": status, "when": when, "from": title,
                # Where to go: the day, the conversation, and the line when it is known.
                "day": datetime.fromtimestamp(anchor / 1000).strftime("%Y-%m-%d"),
                "conversation": cid,
                "start": c_start,
                "line": {"id": line_id, "text": line_text, "start": line_start} if line_id else None,
            })
        return out

    def set_reminder_status(self, reminder_id: int, status: str) -> None:
        if status not in REMINDER_STATUSES:
            raise ValueError(f"status must be one of {', '.join(REMINDER_STATUSES)}")
        cur = self.db.execute("UPDATE reminders SET status = ? WHERE id = ?", (status, reminder_id))
        if cur.rowcount == 0:
            raise ValueError(f"there is no reminder {reminder_id}")
        self.db.commit()

    # --- Ask threads ------------------------------------------------------------------

    def save_exchange(self, chat_id: int | None, question: str, answer: str, lines: dict) -> int:
        """Store a question and its answer, starting a new thread when chat_id is None."""
        now = int(time.time() * 1000)
        if chat_id is None or self.db.execute(
                "SELECT 1 FROM chats WHERE id = ?", (chat_id,)).fetchone() is None:
            title = " ".join(question.split())
            title = title if len(title) <= 80 else title[:79].rstrip() + "…"
            chat_id = self.db.execute(
                "INSERT INTO chats (title, created_ms, updated_ms) VALUES (?, ?, ?)",
                (title, now, now)).lastrowid
        self.db.executemany(
            "INSERT INTO chat_messages (chat_id, role, content, lines, created_ms) VALUES (?, ?, ?, ?, ?)",
            [(chat_id, "user", question, None, now), (chat_id, "assistant", answer, json.dumps(lines), now)])
        self.db.execute("UPDATE chats SET updated_ms = ? WHERE id = ?", (now, chat_id))
        self.db.commit()
        return chat_id

    def chats(self) -> list[dict]:
        """Saved threads, most recently used first."""
        return [{"id": cid, "title": title, "updated": updated, "questions": count}
                for cid, title, updated, count in self.db.execute(
                    "SELECT c.id, c.title, c.updated_ms, "
                    "(SELECT COUNT(*) FROM chat_messages m WHERE m.chat_id = c.id AND m.role = 'user') "
                    "FROM chats c ORDER BY c.updated_ms DESC, c.id DESC")]

    def chat_messages(self, chat_id: int) -> list[dict]:
        return [{"role": role, "content": content, "lines": json.loads(lines) if lines else {}}
                for role, content, lines in self.db.execute(
                    "SELECT role, content, lines FROM chat_messages WHERE chat_id = ? ORDER BY id",
                    (chat_id,))]

    def delete_chat(self, chat_id: int) -> None:
        self.db.execute("DELETE FROM chat_messages WHERE chat_id = ?", (chat_id,))
        self.db.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        self.db.commit()
