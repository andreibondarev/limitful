import os
import sqlite3
from datetime import datetime

import pytest

from limitful import voicememos
from limitful.recordings import added_recordings, remove_recording
from limitful.store import Store

from test_web import _spoken_file

NOW = int(datetime(2026, 11, 15, 12, 0, 0).timestamp() * 1000)
APPLE_EPOCH = 978_307_200


def apple(when: datetime) -> float:
    return when.timestamp() - APPLE_EPOCH


def library(tmp_path, memos, columns="ZPATH TEXT, ZENCRYPTEDTITLE TEXT, ZDATE REAL, ZUNIQUEID TEXT, ZEVICTIONDATE REAL"):
    """A folder laid out like the Voice Memos library: audio files and CloudRecordings.db."""
    folder = tmp_path / "Recordings"
    folder.mkdir()
    db = sqlite3.connect(folder / "CloudRecordings.db")
    db.execute(f"CREATE TABLE ZCLOUDRECORDING (Z_PK INTEGER PRIMARY KEY, {columns})")
    for n, (name, title, when, deleted) in enumerate(memos):
        _spoken_file(folder, name, seconds=2 + n)  # different lengths, so different files
        old = (NOW - 600_000) / 1000
        os.utime(folder / name, (old, old))
        if columns.startswith("ZPATH TEXT, ZENCRYPTEDTITLE"):
            db.execute("INSERT INTO ZCLOUDRECORDING (ZPATH, ZENCRYPTEDTITLE, ZDATE, ZUNIQUEID, ZEVICTIONDATE) "
                       "VALUES (?, ?, ?, ?, ?)",
                       (name, title, apple(when), f"ID-{n}", apple(when) if deleted else None))
    db.commit()
    db.close()
    return folder


MEMOS = [
    ("20261110 080000-AAAA0001.m4a", "Idea for the newsletter", datetime(2026, 11, 10, 8, 0, 0), False),
    ("20261114 093012-AAAA0002.m4a", "Dr. Ruiz, follow-up", datetime(2026, 11, 14, 9, 30, 12), False),
    ("20261114 100000-AAAA0003.m4a", "Deleted one", datetime(2026, 11, 14, 10, 0, 0), True),
]


def test_reads_titles_and_times_from_the_library(tmp_path):
    folder = library(tmp_path, MEMOS)
    memos = voicememos.look(folder)
    assert [(m.title, m.key, m.deleted) for m in memos] == [
        ("Idea for the newsletter", "voicememo:ID-0", False),
        ("Dr. Ruiz, follow-up", "voicememo:ID-1", False),
        ("Deleted one", "voicememo:ID-2", True)]
    assert memos[1].start_ms == int(datetime(2026, 11, 14, 9, 30, 12).timestamp() * 1000)
    assert voicememos.status(folder) == {"state": "ok", "memos": 2}
    # The library is only read: nothing was added to it.
    assert sorted(p.name for p in folder.iterdir()) == sorted([m[0] for m in MEMOS] + ["CloudRecordings.db"])


def test_sync_adds_each_memo_once_from_the_chosen_moment_on(tmp_path):
    folder = library(tmp_path, MEMOS)
    store = Store(tmp_path / "data")
    try:
        since = int(datetime(2026, 11, 12).timestamp() * 1000)
        assert voicememos.sync(store, since, folder, NOW) == voicememos.Synced(added=1)
        (only,) = added_recordings(store)
        assert (only["name"], only["source"]) == ("Dr. Ruiz, follow-up", "voicememos")
        assert only["start_ms"] == int(datetime(2026, 11, 14, 9, 30, 12).timestamp() * 1000)
        assert voicememos.sync(store, since, folder, NOW) == voicememos.Synced()

        # Asking for older ones too brings in the rest, but never one in Recently Deleted.
        assert voicememos.sync(store, 0, folder, NOW) == voicememos.Synced(added=1)
        assert [r["name"] for r in added_recordings(store)] == ["Dr. Ruiz, follow-up", "Idea for the newsletter"]

        # One removed here does not come back at the next sync.
        remove_recording(store, only["path"])
        assert voicememos.sync(store, 0, folder, NOW) == voicememos.Synced()
        assert [r["name"] for r in added_recordings(store)] == ["Idea for the newsletter"]
    finally:
        store.close()


def test_a_memo_still_arriving_waits_for_the_next_sync(tmp_path):
    folder = library(tmp_path, MEMOS[:1])
    fresh = (NOW - 5_000) / 1000
    os.utime(folder / MEMOS[0][0], (fresh, fresh))
    store = Store(tmp_path / "data")
    try:
        assert voicememos.sync(store, 0, folder, NOW).added == 0
        assert voicememos.sync(store, 0, folder, NOW + 60_000).added == 1
    finally:
        store.close()


def test_an_unfamiliar_database_falls_back_to_the_file_names(tmp_path):
    folder = library(tmp_path, MEMOS[:2], columns="ZSOMETHINGELSE TEXT")
    memos = voicememos.look(folder)
    assert [(m.title, m.start_ms, m.key) for m in memos] == [
        (None, None, f"voicememo:{MEMOS[0][0]}"), (None, None, f"voicememo:{MEMOS[1][0]}")]
    store = Store(tmp_path / "data")
    try:
        assert voicememos.sync(store, 0, folder, NOW).added == 2
        starts = sorted(r["start_ms"] for r in added_recordings(store))
        assert datetime.fromtimestamp(starts[1] / 1000) == datetime(2026, 11, 14, 9, 30, 12)  # from its name
    finally:
        store.close()


def test_says_when_the_library_is_missing_or_guarded(tmp_path, monkeypatch):
    assert voicememos.status(tmp_path / "nowhere") == {"state": "missing", "memos": 0}

    def refused(_where):
        raise voicememos.NoAccess

    monkeypatch.setattr(voicememos, "_listing", refused)
    assert voicememos.status(tmp_path) == {"state": "denied", "memos": 0}
    store = Store(tmp_path / "data")
    try:
        with pytest.raises(voicememos.NoAccess):
            voicememos.sync(store, 0, tmp_path, NOW)
    finally:
        store.close()
