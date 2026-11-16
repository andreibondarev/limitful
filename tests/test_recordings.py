from datetime import datetime

import pytest

from limitful.hosted import SpokenLine
from limitful.recordings import NotAudio, add_recording, recorded_at
from limitful.store import Store

from test_web import _spoken_file

NOW = int(datetime(2026, 11, 15, 12, 0, 0).timestamp() * 1000)


def local(ms):
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def test_when_a_recording_was_made():
    # The time in the name, as Voice Memos and most recorders write it, in local time.
    start, how = recorded_at("20261114 093012-1A2B3C4D.m4a", "2020-01-01T00:00:00Z", None, 5000, NOW)
    assert (local(start), how) == ("2026-11-14 09:30:12", "name")
    assert recorded_at("Recording_2026-11-14_09-30-12.wav", None, None, 5000, NOW)[1] == "name"
    # Then the time written inside the file, which is UTC.
    start, how = recorded_at("New Recording 12.m4a", "2026-11-14T17:30:12.000000Z", None, 5000, NOW)
    assert how == "file" and start == int(datetime.fromisoformat("2026-11-14T17:30:12+00:00").timestamp() * 1000)
    # Then when the file was last changed, which is when recording stopped.
    assert recorded_at("memo.m4a", None, NOW - 60_000, 5000, NOW) == (NOW - 65_000, "modified")
    # A clock that was never set, a date in the future and a number that is not a date are not believed.
    assert recorded_at("memo.m4a", "1904-01-01T00:00:00Z", None, 5000, NOW) == (NOW - 5000, "now")
    assert recorded_at("20991114 093012.m4a", None, None, 5000, NOW) == (NOW - 5000, "now")
    assert recorded_at("20261345 996199.m4a", None, None, 5000, NOW) == (NOW - 5000, "now")


def test_a_recording_is_filed_once_and_transcribed(tmp_path):
    from test_web import Words

    source = _spoken_file(tmp_path, "New Recording 3.m4a")
    store = Store(tmp_path / "data")
    try:
        added = add_recording(store, source, source.name, modified_ms=NOW - 60_000, now_ms=NOW)
        assert added.new and added.dated_by in ("file", "modified")
        assert (store.data_dir / added.path).read_bytes()[:4] == b"OggS"
        assert 2800 <= added.duration_ms <= 3200
        assert not list((store.data_dir / "audio").glob(".adding-*"))
        assert add_recording(store, source, "renamed.m4a", now_ms=NOW).new is False
        assert [row[0] for row in store.pending_transcription()] == [added.path]

        lines, _files = store.transcribe_pending(Words())
        assert lines == 2 and store.pending_transcription() == []
        assert store.db.execute("SELECT MIN(start_ms) FROM utterances").fetchone()[0] == added.start_ms
    finally:
        store.close()


def test_a_file_that_is_not_audio_leaves_nothing_behind(tmp_path):
    bad = tmp_path / "memo.m4a"
    bad.write_bytes(b"not audio at all" * 50)
    store = Store(tmp_path / "data")
    try:
        with pytest.raises(NotAudio):
            add_recording(store, bad, bad.name)
        assert store.pending_transcription() == []
        assert not list((store.data_dir / "audio").rglob("*.ogg"))
    finally:
        store.close()


def test_a_hosted_service_is_sent_the_added_file_itself(tmp_path):
    source = _spoken_file(tmp_path, "20261114 093012.m4a")
    store = Store(tmp_path / "data")
    sent = []

    class Service:
        name = "deepgram:test"

        def transcribe_session(self, audio):
            sent.append(audio)
            return [SpokenLine(0.5, 1.5, "book the van", 0), SpokenLine(1.8, 2.6, "for Tuesday", 1)]

    try:
        added = add_recording(store, source, source.name, now_ms=NOW)
        lines, _files = store.transcribe_pending(Service())
        assert lines == 2 and store.pending_transcription() == []
        assert sent == [(store.data_dir / added.path).read_bytes()]
        rows = store.db.execute(
            "SELECT text, start_ms, source_speaker, segment FROM utterances ORDER BY start_ms").fetchall()
        assert rows == [("book the van", added.start_ms + 500, "1", added.path),
                        ("for Tuesday", added.start_ms + 1800, "2", added.path)]
    finally:
        store.close()


# --- removing, re-timing, and conversations for recordings older than the newest one ---

def _added_and_transcribed(tmp_path, name="20261114 093012.m4a"):
    from test_web import Words

    store = Store(tmp_path / "data")
    added = add_recording(store, _spoken_file(tmp_path, name), name, now_ms=NOW)
    store.transcribe_pending(Words())
    return store, added


def test_an_older_recording_still_becomes_a_conversation(tmp_path):
    store, added = _added_and_transcribed(tmp_path)
    try:
        # Something newer is already a conversation, as after any sync.
        store.db.execute("INSERT INTO conversations (start_ms, end_ms, status) VALUES (?, ?, 'done')",
                         (NOW - 3_600_000, NOW - 3_000_000))
        assert store.build_conversations(NOW) == 1
        row = store.db.execute("SELECT start_ms, end_ms, status FROM conversations ORDER BY start_ms").fetchone()
        assert row == (added.start_ms, added.start_ms + 1900, "pending")
        assert store.build_conversations(NOW) == 0  # and only once
    finally:
        store.close()


def test_move_a_recording_to_when_it_really_began(tmp_path):
    from limitful.recordings import added_recordings, move_recording

    store, added = _added_and_transcribed(tmp_path)
    try:
        store.build_conversations(NOW)
        store.db.execute("UPDATE conversations SET status = 'done', title = 'Shopping'")
        store.db.commit()
        target = int(datetime(2026, 11, 12, 18, 0, 5).timestamp() * 1000)
        moved = move_recording(store, added.path, target)
        assert moved.startswith("audio/2026-11-12/added_18-00-05_") and (store.data_dir / moved).is_file()
        assert not (store.data_dir / added.path).exists()
        assert store.db.execute("SELECT segment, start_ms FROM utterances ORDER BY start_ms").fetchall() == [
            (moved, target), (moved, target + 1200)]
        # The conversation made from it moves too and keeps its title.
        assert store.db.execute("SELECT start_ms, title, status FROM conversations").fetchall() == [
            (target, "Shopping", "done")]
        assert [r["path"] for r in added_recordings(store)] == [moved]
        assert store.pending_transcription() == []
        assert "buy 100% oat_milk" in (store.data_dir / "transcripts" / "2026-11-12.md").read_text()
        assert "oat_milk" not in (store.data_dir / "transcripts" / "2026-11-14.md").read_text()
        with pytest.raises(ValueError):
            move_recording(store, moved, NOW * 2)
        with pytest.raises(ValueError):
            move_recording(store, "audio/2026-11-12/not-added.ogg", target)
    finally:
        store.close()


def test_remove_a_recording(tmp_path):
    from limitful.recordings import added_recordings, remove_recording

    store, added = _added_and_transcribed(tmp_path)
    try:
        store.build_conversations(NOW)
        remove_recording(store, added.path)
        assert added_recordings(store) == []
        assert not (store.data_dir / added.path).exists()
        for table in ("utterances", "segments", "transcriptions", "conversations", "added"):
            assert store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        # A file that was removed can be added again.
        again = add_recording(store, tmp_path / "20261114 093012.m4a", "20261114 093012.m4a", now_ms=NOW)
        assert again.new is True
    finally:
        store.close()
