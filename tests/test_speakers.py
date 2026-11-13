"""Speaker grouping, with a stand-in for the voice model."""

from datetime import datetime

import numpy as np
import pytest

from pendant_sync.protocol import FlashPage
from pendant_sync.store import Store
from pendant_sync.transcribe import Utterance

from wire import flash_page, opus_frame

T0 = int(datetime(2026, 11, 13, 9, 0, 0).timestamp() * 1000)
WHO = [0, 1, 0, 2, 1, 0, 2, 1, 0, 1, 2, 0]  # who says each 2-second line
RATE = 16000


class Words:
    name = "fake"

    def __init__(self, count):
        self.count = count

    def transcribe(self, audio_path):
        said = [Utterance(i * 2000, i * 2000 + 1900, f"line {i}") for i in range(self.count)]
        return said + [Utterance(self.count * 2000, self.count * 2000 + 500, "mm")]


def fake_audio(path):
    """Samples whose value says who is speaking at that moment."""
    audio = np.zeros(40 * RATE, dtype=np.float32)
    for i, who in enumerate(WHO):
        audio[i * 2 * RATE : (i + 1) * 2 * RATE] = who
    return audio


class Voices:
    """Every voice shares a large common part (the microphone) plus its own."""

    def embed(self, clip):
        who = int(clip[0])
        rng = np.random.default_rng(len(clip) + who)
        voice = np.full(16, 5.0)
        voice[who] += 1.5
        return (voice + rng.normal(0, 0.05, 16)).astype(np.float32)


def make_store(tmp_path, lines=len(WHO)):
    store = Store(tmp_path)
    for index in range(30):
        store.add_page(FlashPage(index=index, session=1, seq=0,
                                 data=flash_page(T0 + index * 1000, [opus_frame(i) for i in range(50)])))
    store.commit()
    store.export_audio()
    store.transcribe_pending(Words(lines))
    return store


def groups(store):
    rows = store.db.execute("SELECT text, speaker_id FROM utterances ORDER BY start_ms").fetchall()
    return [speaker for _text, speaker in rows]


def test_lines_are_grouped_by_voice(tmp_path):
    store = make_store(tmp_path)
    assert store.label_speakers(Voices(), fake_audio) == 12
    got = groups(store)
    assert got[-1] is None  # the half-second "mm" is too short to judge
    first_seen = {}
    for who, speaker in zip(WHO, got):
        assert first_seen.setdefault(who, speaker) == speaker
    assert len(set(first_seen.values())) == 3
    assert [(name, lines) for _id, name, lines in store.speakers()] == [
        ("Speaker 1", 5), ("Speaker 2", 4), ("Speaker 3", 3)]
    text = (tmp_path / "transcripts" / "2026-11-13.md").read_text()
    assert "- **09:00:00** Speaker 1: line 0" in text
    assert "- **09:00:24** mm" in text
    assert store.label_speakers(Voices(), fake_audio) == 0  # nothing new
    store.close()


def test_too_few_lines_are_left_unlabelled(tmp_path):
    store = make_store(tmp_path, lines=9)
    assert store.label_speakers(Voices(), fake_audio) == 0
    assert set(groups(store)) == {None} and store.speakers() == []
    store.close()


def test_rename_and_merge(tmp_path):
    store = make_store(tmp_path)
    store.label_speakers(Voices(), fake_audio)
    assert store.rename_speaker(1, "  Andrei  ") == 1
    transcript = tmp_path / "transcripts" / "2026-11-13.md"
    assert "Andrei: line 0" in transcript.read_text()
    # Giving speaker 3 the same name (any capitalisation) merges it into speaker 1.
    assert store.rename_speaker(3, "andrei") == 1
    assert [(name, lines) for _id, name, lines in store.speakers()] == [("Andrei", 8), ("Speaker 2", 4)]
    assert "Speaker 3" not in transcript.read_text()
    with pytest.raises(ValueError):
        store.rename_speaker(1, "   ")
    with pytest.raises(ValueError):
        store.rename_speaker(99, "Nobody")
    store.close()


def test_reset_regroups_from_stored_fingerprints(tmp_path):
    store = make_store(tmp_path)
    store.label_speakers(Voices(), fake_audio)
    store.rename_speaker(1, "Andrei")
    assert store.reset_speakers() == 12
    assert sorted(lines for _id, _name, lines in store.speakers()) == [3, 4, 5]
    assert all(name.startswith("Speaker ") for _id, name, _lines in store.speakers())
    store.close()
