"""Score a transcription service's speaker labels against Limitless's.

Imported conversations come with Limitless's own per-conversation speaker
numbers. Sending the same audio to another service and comparing who it says
spoke when gives a number to judge that service by before relying on it.

The score is the share of speaking time given to the right speaker, under the
best one-to-one pairing of the service's speakers with Limitless's. Always
guessing whoever talks most is the baseline: anything useful must beat it
clearly. Limitless's labels are themselves imperfect and its timestamps run
about a second late, so even a perfect service would score below 100%.
"""

from __future__ import annotations

import io
import itertools
import sqlite3
import wave
from collections import Counter
from pathlib import Path
from typing import Callable

SAMPLE_RATE = 16000
TYPICAL_LATE_S = 0.9  # how late Limitless's timestamps run (measured)


def best_pairing_score(truth: list, guess: list, weights: list[float]) -> float:
    """Share of the weight where the guess matches the truth, under the best
    one-to-one pairing of guessed speakers with true ones."""
    total = sum(weights)
    if not total:
        return 0.0
    table: Counter = Counter()
    for t, g, w in zip(truth, guess, weights):
        if g is not None:
            table[(t, g)] += w
    true_labels = sorted(set(truth), key=str)
    guessed = sorted({g for g in guess if g is not None}, key=str)
    if len(guessed) > 7:
        # Too many to try every pairing: pair greedily, largest overlap first.
        best, used_t, used_g = 0.0, set(), set()
        for (t, g), w in sorted(table.items(), key=lambda item: -item[1]):
            if t not in used_t and g not in used_g:
                best += w
                used_t.add(t)
                used_g.add(g)
        return best / total
    best = 0.0
    for chosen in itertools.permutations(guessed, min(len(guessed), len(true_labels))):
        for kept in itertools.combinations(true_labels, len(chosen)):
            best = max(best, sum(table[(t, g)] for t, g in zip(kept, chosen)))
    return best / total


def speakers_by_overlap(spans: list[tuple[float, float]], turns: list[tuple[float, float, object]]) -> list:
    """For each (start, end) span, the speaker of the turns that overlap it most."""
    out = []
    for start, end in spans:
        tally: Counter = Counter()
        for t_start, t_end, speaker in turns:
            overlap = min(end, t_end) - max(start, t_start)
            if overlap > 0 and speaker is not None:
                tally[speaker] += overlap
        out.append(tally.most_common(1)[0][0] if tally else None)
    return out


def majority_share(truth: list, weights: list[float]) -> float:
    by_label: Counter = Counter()
    for t, w in zip(truth, weights):
        by_label[t] += w
    return max(by_label.values()) / sum(weights) if weights else 0.0


def _wav(samples) -> bytes:
    """16 kHz mono samples (floats in -1..1) as a WAV file."""
    import numpy as np

    out = io.BytesIO()
    with wave.open(out, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


def score_service(data_dir: Path, service, load_audio: Callable, limit: int = 5) -> list[tuple]:
    """Send imported conversations to a service and score its speakers.

    Returns (title, lines, Limitless's speakers, the service's speakers, score,
    baseline) per conversation. Reads the database only.
    """
    import numpy as np

    data_dir = Path(data_dir)
    db = sqlite3.connect(f"file:{data_dir / 'pendant.db'}?mode=ro", uri=True)
    try:
        conversations = db.execute("""
            SELECT c.title, c.start_ms, c.end_ms FROM conversations c WHERE c.engine = 'limitless'
            AND (SELECT COUNT(*) FROM utterances u WHERE u.start_ms BETWEEN c.start_ms AND c.end_ms) BETWEEN 50 AND 220
            AND (SELECT COUNT(DISTINCT source_speaker) FROM utterances u
                 WHERE u.start_ms BETWEEN c.start_ms AND c.end_ms) BETWEEN 2 AND 4
            AND NOT EXISTS (SELECT 1 FROM utterances u
                            WHERE u.start_ms BETWEEN c.start_ms AND c.end_ms AND u.segment = '')
            AND c.end_ms - c.start_ms < 20 * 60000
            ORDER BY (c.id * 7919) % 1009 LIMIT ?""", (limit,)).fetchall()
        results = []
        for title, start, end in conversations:
            rows = db.execute("""
                SELECT u.segment, s.start_ms, COALESCE(u.orig_start_ms, u.start_ms), u.end_ms - u.start_ms,
                       u.source_speaker
                FROM utterances u JOIN segments s ON s.path = u.segment
                WHERE u.start_ms BETWEEN ? AND ? ORDER BY 3""", (start, end)).fetchall()
            pieces, spans, truth, at = [], [], [], 0.0
            for path, group in itertools.groupby(rows, key=lambda row: row[0]):
                group = list(group)
                audio = load_audio(data_dir / path)
                file_start = group[0][1]
                first = max(0.0, (min(g[2] for g in group) - file_start) / 1000 - TYPICAL_LATE_S - 1.0)
                last = min(len(audio) / SAMPLE_RATE,
                           (max(g[2] + g[3] for g in group) - file_start) / 1000 + 1.0)
                pieces.append(audio[int(first * SAMPLE_RATE): int(last * SAMPLE_RATE)])
                for _path, _fs, line_start, duration, label in group:
                    t0 = max(at, (line_start - file_start) / 1000 - TYPICAL_LATE_S - first + at)
                    spans.append((t0, t0 + max(0.3, duration / 1000)))
                    truth.append(label)
                at += last - first
            lines = service.transcribe_session(_wav(np.concatenate(pieces)), "audio/wav")
            guess = speakers_by_overlap(spans, [(line.start_s, line.end_s, line.speaker) for line in lines])
            weights = [b - a for a, b in spans]
            results.append((title, len(spans), len(set(truth)), len({g for g in guess if g is not None}),
                            best_pairing_score(truth, guess, weights), majority_share(truth, weights)))
        return results
    finally:
        db.close()
