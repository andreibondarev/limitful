"""Importing a Limitless export, using a small hand-made zip."""

import json
import zipfile
from datetime import datetime, timezone

from limitful.importer import best_utc_offset, import_limitless, parse_lifelog
from limitful.store import Store

# 2026-11-08 18:55:58 UTC, which is 13:55:58 in a UTC-5 zone.
T0 = int(datetime(2026, 11, 8, 18, 55, 58, tzinfo=timezone.utc).timestamp() * 1000)

LIFELOG = f"""# UVB therapy introduction

## Benefits

> [1](#startMs={T0}&endMs={T0 + 10000}): It helps with bone density.

> [2](#startMs={T0 + 10000}&endMs={T0 + 10000}): Mhm.

## Setup

### App

> [1](#startMs={T0 + 60000}&endMs={T0 + 64000}): Does it take [a long] time?
> [2](#startMs={T0 + 500000}&endMs={T0 + 501000}):
"""


def make_zip(path, with_audio=True):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("lifelogs/2026/11/08/2026-11-08_13h55m58s_UVB-therapy-introduction.md", LIFELOG)
        z.writestr("lifelogs/2026/11/08/empty.md", "# Nothing said\n")
        if with_audio:
            # File names are local time (UTC-5); the folder date is not used.
            z.writestr("audio/pendant/2026/11/08/2026-11-08_13h55m50s_to_13h57m10s.ogg", b"OggS-one")
            z.writestr("audio/pendant/2026/11/09/2026-11-08_23h59m50s_to_00h00m20s.ogg", b"OggS-two")
            z.writestr("audio/pendant/../../evil.ogg", b"nope")
        z.writestr("reminders/abc.json", json.dumps({
            "title": "Ask about  the spraying", "status": "completed", "createdTimeMs": T0 + 90000,
            "source": {"startTimeMs": T0 + 5000}}))
        z.writestr("reminders/bad.json", "{not json")
        z.writestr("user/user.json", json.dumps({"utcOffsetMinutes": -480}))  # wrong on purpose
        z.writestr("chats/2026/11/08/c.json", "{}")
    return path


def quiet(_message):
    pass


def test_parse_lifelog():
    log = parse_lifelog("k", LIFELOG)
    assert (log.title, log.sections) == ("UVB therapy introduction", ["Benefits", "Setup"])
    assert [(s, e - st, t) for s, st, e, t in log.lines] == [
        ("1", 10000, "It helps with bone density."),
        ("2", 1, "Mhm."),  # a zero-length line still gets a duration
        ("1", 4000, "Does it take [a long] time?"),
    ]
    assert log.headings == [(T0, 2, "Benefits"), (T0 + 60000, 2, "Setup"), (T0 + 60000, 3, "App")]
    assert parse_lifelog("k", "# Only a title\n") is None


def test_time_zone_is_found_from_the_data_not_the_settings_file():
    audio = [(T0 - 8000 - 5 * 3600000, T0 + 72000 - 5 * 3600000)]  # named in UTC-5
    assert best_utc_offset(audio, [T0, T0 + 10000, T0 + 60000]) == -300
    assert best_utc_offset([], [T0]) == 0


def test_import(tmp_path):
    store = Store(tmp_path / "data")
    result = import_limitless(store, make_zip(tmp_path / "export.zip"), log=quiet)
    assert (result.conversations, result.lines, result.lines_with_audio) == (1, 3, 3)
    assert (result.audio_files, result.reminders, result.utc_offset_minutes) == (2, 1, -300)
    assert result.not_imported == ["1 file(s) in chats/", "1 file(s) in user/"]

    # Audio lands inside the data folder under names we chose, nowhere else.
    audio_dir = tmp_path / "data" / "audio"
    files = sorted(p.relative_to(audio_dir).as_posix() for p in audio_dir.rglob("*.ogg"))
    assert len(files) == 2 and all("/limitless_2026-11-08_" in f for f in files)
    assert not list(tmp_path.rglob("evil.ogg"))

    rows = store.db.execute(
        "SELECT u.text, u.source_speaker, u.start_ms - s.start_ms FROM utterances u "
        "JOIN segments s ON s.path = u.segment ORDER BY u.start_ms").fetchall()
    assert rows == [("It helps with bone density.", "1", 8000), ("Mhm.", "2", 18000),
                    ("Does it take [a long] time?", "1", 68000)]
    assert store.db.execute(
        "SELECT duration_ms FROM segments WHERE path LIKE '%23h59m50s%'").fetchone() == (30000,)

    (talk,) = store.conversations(T0 - 1, T0 + 1)
    assert (talk["title"], talk["summary"]) == ("UVB therapy introduction", ["Benefits", "Setup"])
    assert [(r["text"], r["status"]) for r in talk["reminders"]] == [("Ask about the spraying", "done")]
    assert talk["lines"] == 3
    assert talk["reminders"][0]["line"] is None  # nothing in this transcript mentions spraying
    assert talk["sections"] == [
        {"start": T0, "level": 2, "title": "Benefits"},
        {"start": T0 + 60000, "level": 2, "title": "Setup"},
        {"start": T0 + 60000, "level": 3, "title": "App"}]
    assert store.pending_transcription() == []  # imported audio is not sent to Whisper

    day = datetime.fromtimestamp(T0 / 1000).strftime("%Y-%m-%d")
    text = (tmp_path / "data" / "transcripts" / f"{day}.md").read_text()
    assert "UVB therapy introduction" in text and "Speaker 1: It helps with bone density." in text
    store.close()


def test_import_twice_adds_nothing(tmp_path):
    store = Store(tmp_path / "data")
    path = make_zip(tmp_path / "export.zip")
    import_limitless(store, path, log=quiet)
    again = import_limitless(store, path, log=quiet)
    assert (again.conversations, again.lines, again.audio_files, again.reminders) == (0, 0, 0, 0)
    assert again.skipped_existing == 1
    assert store.db.execute("SELECT COUNT(*) FROM utterances").fetchone() == (3,)
    assert store.db.execute("SELECT COUNT(*) FROM reminders").fetchone() == (1,)
    assert store.db.execute("SELECT COUNT(*) FROM sections").fetchone() == (3,)
    # An import made before headings were kept gets them on the next run.
    store.db.execute("DELETE FROM sections")
    import_limitless(store, path, log=quiet)
    assert store.db.execute("SELECT COUNT(*) FROM sections").fetchone() == (3,)
    store.close()


def test_import_without_audio_keeps_the_text(tmp_path):
    store = Store(tmp_path / "data")
    result = import_limitless(store, make_zip(tmp_path / "export.zip", with_audio=False), log=quiet)
    assert (result.lines, result.lines_with_audio, result.utc_offset_minutes) == (3, 0, None)
    assert store.db.execute("SELECT DISTINCT segment FROM utterances").fetchall() == [("",)]
    store.close()
