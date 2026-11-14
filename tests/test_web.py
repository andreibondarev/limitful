import json
import threading
import urllib.error
import urllib.request
from datetime import datetime

import pytest

from limitful.protocol import FlashPage
from limitful.store import Store
from limitful.transcribe import Utterance
from limitful.web import make_server

from wire import flash_page, opus_frame

T0 = int(datetime(2026, 11, 13, 9, 7, 0).timestamp() * 1000)


class Words:
    name = "fake"

    def transcribe(self, audio_path):
        return [Utterance(0, 900, "buy 100% oat_milk"), Utterance(1200, 1900, "call Joseph")]


@pytest.fixture
def site(tmp_path):
    store = Store(tmp_path)
    frames = [opus_frame(i) for i in range(50)]
    for index, ts in [(0, T0), (1, T0 + 1000), (2, T0 + 3_600_000)]:
        store.add_page(FlashPage(index=index, session=1, seq=0, data=flash_page(ts, frames)))
    store.commit()
    store.export_audio()
    store.transcribe_pending(Words())
    store.db.execute("INSERT INTO speakers (id, name, voice_sum, lines) VALUES (1, 'Speaker 1', x'00000000', 2)")
    store.db.execute("INSERT INTO speakers (id, name, voice_sum, lines) VALUES (2, 'Joseph', x'00000000', 1)")
    store.db.execute("UPDATE utterances SET speaker_id = 1 WHERE text LIKE 'buy%'")
    store.db.execute("INSERT INTO conversations (id, start_ms, end_ms, status, title, summary) "
                     "VALUES (1, ?, ?, 'done', 'Shopping and a call', '[\"Oat milk is needed.\"]')",
                     (T0, T0 + 2000))
    store.db.execute("INSERT INTO reminders (id, conversation_id, text, created_ms) VALUES (1, 1, 'Call Joseph', ?)", (T0,))
    store.db.commit()
    assert store.link_reminders_to_lines() == 1  # "Call Joseph" is found in the transcript
    store.close()
    (tmp_path / "secret.txt").write_text("private")

    server = make_server(tmp_path, 0, link_speakers=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def fetch(path, headers=None, data=None):
        req = urllib.request.Request(base + path, headers=headers or {}, data=data)
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, dict(res.headers), res.read()
        except urllib.error.HTTPError as err:
            return err.code, dict(err.headers), err.read()

    yield fetch
    server.shutdown()
    server.server_close()


def test_page_and_days(site):
    status, headers, body = site("/")
    assert status == 200 and b"Lifelog" in body and "text/html" in headers["Content-Type"]
    assert json.loads(site("/api/days")[2]) == [{"day": "2026-11-13", "lines": 4}]


def test_day_lists_lines_with_audio_offsets(site):
    lines = json.loads(site("/api/day/2026-11-13")[2])
    assert [u["text"] for u in lines] == ["buy 100% oat_milk", "call Joseph"] * 2
    assert (lines[0]["start"], lines[1]["offset"]) == (T0, 1200)
    assert lines[2]["start"] == T0 + 3_600_000 and lines[2]["offset"] == 0
    assert lines[0]["audio"] != lines[2]["audio"]
    assert json.loads(site("/api/day/2026-11-14")[2]) == []
    assert site("/api/day/yesterday")[0] == 400


def test_search_is_literal_and_case_insensitive(site):
    hits = json.loads(site("/api/search?q=JOSEPH")[2])
    assert len(hits) == 2 and hits[0]["day"] == "2026-11-13"
    assert hits[0]["start"] > hits[1]["start"]  # newest first
    assert len(json.loads(site("/api/search?q=100%25")[2])) == 2
    assert json.loads(site("/api/search?q=oat%20milk")[2]) == []  # "_" is not a wildcard
    assert json.loads(site("/api/search?q=%25")[2]) != [] and json.loads(site("/api/search?q=")[2]) == []


def test_audio_supports_ranges(site):
    path = json.loads(site("/api/day/2026-11-13")[2])[0]["audio"]
    status, headers, body = site(path)
    assert status == 200 and body[:4] == b"OggS" and headers["Accept-Ranges"] == "bytes"
    status, headers, part = site(path, {"Range": "bytes=4-9"})
    assert status == 206 and part == body[4:10]
    assert headers["Content-Range"] == f"bytes 4-9/{len(body)}"
    assert site(path, {"Range": "bytes=-5"})[2] == body[-5:]
    assert site(path, {"Range": f"bytes={len(body)}-"})[0] == 416


def test_only_audio_files_are_served(site):
    assert site("/audio/../secret.txt")[0] == 404
    assert site("/audio/%2e%2e/secret.txt")[0] == 404
    assert site("/audio/../pendant.db")[0] == 404
    assert site("/secret.txt")[0] == 404


def test_other_hosts_are_refused(site):
    assert site("/api/days", {"Host": "evil.example"})[0] == 403
    assert site("/api/days", {"Host": "localhost:9"})[0] == 200


JSON = {"Content-Type": "application/json"}


def test_speakers_are_shown_and_can_be_renamed(site):
    lines = json.loads(site("/api/day/2026-11-13")[2])
    assert lines[0]["speaker"] == {"id": 1, "name": "Speaker 1", "line": lines[0]["id"]}
    assert lines[1]["speaker"] is None
    status, _h, body = site("/api/speakers/1", JSON, b'{"name": "Andrei"}')
    assert (status, json.loads(body)) == (200, {"id": 1})
    assert json.loads(site("/api/day/2026-11-13")[2])[0]["speaker"]["name"] == "Andrei"
    # Using a name that exists merges into that speaker.
    assert json.loads(site("/api/speakers/1", JSON, b'{"name": "joseph"}')[2]) == {"id": 2}
    first = json.loads(site("/api/day/2026-11-13")[2])[0]
    assert (first["speaker"]["id"], first["speaker"]["name"]) == (2, "Joseph")
    # Naming one line only: the other line is untouched, and a new person appears.
    second = json.loads(site("/api/day/2026-11-13")[2])[1]["id"]
    assert site(f"/api/lines/{second}/speaker", JSON, b'{"name": "Karen"}')[0] == 200
    after = json.loads(site("/api/day/2026-11-13")[2])
    assert after[1]["speaker"]["name"] == "Karen" and after[0]["speaker"]["name"] == "Joseph"
    assert site("/api/lines/999999/speaker", JSON, b'{"name": "X"}')[0] == 400


def test_rename_rejects_bad_requests(site):
    assert site("/api/speakers/1", JSON, b'{"name": "  "}')[0] == 400
    assert site("/api/speakers/1", JSON, b'{"name": 5}')[0] == 400
    assert site("/api/speakers/1", JSON, b'[1]')[0] == 400
    assert site("/api/speakers/99", JSON, b'{"name": "X"}')[0] == 400
    assert site("/api/speakers/1", {"Content-Type": "text/plain"}, b'{"name": "X"}')[0] == 415
    assert site("/api/speakers/1", dict(JSON, Host="evil.example"), b'{"name": "X"}')[0] == 403
    assert site("/api/other", JSON, b'{}')[0] == 404
    assert json.loads(site("/api/day/2026-11-13")[2])[0]["speaker"]["name"] == "Speaker 1"


def test_conversations_and_reminders(site):
    (talk,) = json.loads(site("/api/conversations/2026-11-13")[2])
    assert (talk["title"], talk["summary"], talk["start"]) == ("Shopping and a call", ["Oat milk is needed."], T0)
    line = json.loads(site("/api/day/2026-11-13")[2])[1]
    assert talk["reminders"] == [{"id": 1, "text": "Call Joseph", "status": "suggested", "line": line["id"]}]
    assert json.loads(site("/api/conversations/2026-11-14")[2]) == []
    assert site("/api/conversations/soon")[0] == 400

    (reminder,) = json.loads(site("/api/reminders")[2])
    assert (reminder["text"], reminder["from"], reminder["status"]) == ("Call Joseph", "Shopping and a call", "suggested")
    assert (reminder["day"], reminder["conversation"], reminder["start"]) == ("2026-11-13", 1, T0)
    assert reminder["line"] == {"id": line["id"], "text": "call Joseph", "start": line["start"]}
    status, _h, body = site("/api/reminders/1", JSON, b'{"status": "accepted"}')
    assert (status, json.loads(body)) == (200, {"id": 1, "status": "accepted"})
    assert json.loads(site("/api/reminders")[2])[0]["status"] == "accepted"
    # Finished reminders leave the working list but can still be listed, to tick back.
    assert site("/api/reminders/1", JSON, b'{"status": "done"}')[0] == 200
    assert json.loads(site("/api/reminders")[2]) == []
    assert [r["status"] for r in json.loads(site("/api/reminders?done=1")[2])] == ["done"]
    assert site("/api/reminders/1", JSON, b'{"status": "dismissed"}')[0] == 200
    assert json.loads(site("/api/reminders?done=1")[2]) == []


def test_reminder_updates_reject_bad_requests(site):
    assert site("/api/reminders/1", JSON, b'{"status": "later"}')[0] == 400
    assert site("/api/reminders/1", JSON, b'{}')[0] == 400
    assert site("/api/reminders/42", JSON, b'{"status": "done"}')[0] == 400
    assert site("/api/reminders/1", {"Content-Type": "text/plain"}, b'{"status": "done"}')[0] == 415
    assert json.loads(site("/api/reminders")[2])[0]["status"] == "suggested"


ZIP = {"Content-Type": "application/zip"}


def test_import_an_export_through_the_page(site, tmp_path):
    from test_importer import make_zip

    data = make_zip(tmp_path / "export.zip").read_bytes()
    status, _h, body = site("/api/import", ZIP, data)
    assert status == 200
    got = json.loads(body)
    assert (got["conversations"], got["lines"], got["recordings"], got["reminders"]) == (1, 3, 2, 1)
    assert {d["day"] for d in json.loads(site("/api/days")[2])} >= {"2026-11-08", "2026-11-13"}
    assert not list((tmp_path / "imports").glob("*.zip"))  # the upload is not kept
    assert json.loads(site("/api/status")[2])["running"] is False

    again = json.loads(site("/api/import", ZIP, data)[2])
    assert (again["conversations"], again["skipped"]) == (0, 1)


def test_import_rejects_bad_uploads(site):
    assert site("/api/import", ZIP, b"this is not a zip")[0] == 400
    assert site("/api/import", ZIP, b"")[0] == 400
    assert site("/api/import", JSON, b"{}")[0] == 415
    assert site("/api/import", {"Content-Type": "text/plain"}, b"x")[0] == 415
    assert site("/api/import", dict(ZIP, Host="evil.example"), b"x")[0] == 403
    assert site("/api/speakers/1", ZIP, b"x")[0] == 415
    assert json.loads(site("/api/status")[2])["running"] is False


def test_server_upgrades_an_old_database_and_serves_an_empty_folder(tmp_path):
    import sqlite3

    old = tmp_path / "old"
    old.mkdir()
    db = sqlite3.connect(old / "pendant.db")
    # The layout of the first release: no speaker, source or conversation columns.
    db.executescript("""
        CREATE TABLE segments (path TEXT PRIMARY KEY, start_ms INTEGER NOT NULL, duration_ms INTEGER NOT NULL,
                               first_page INTEGER NOT NULL, last_page INTEGER NOT NULL);
        CREATE TABLE utterances (id INTEGER PRIMARY KEY, segment TEXT NOT NULL, start_ms INTEGER NOT NULL,
                                 end_ms INTEGER NOT NULL, text TEXT NOT NULL);
    """)
    db.execute("INSERT INTO utterances (segment, start_ms, end_ms, text) VALUES ('', ?, ?, 'hello')", (T0, T0 + 900))
    db.commit()
    db.close()

    for folder, expected in ((old, ["hello"]), (tmp_path / "brand-new", [])):
        server = make_server(folder, 0, link_speakers=False)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(base + "/api/day/2026-11-13") as res:
            assert [u["text"] for u in json.loads(res.read())] == expected
        with urllib.request.urlopen(base + "/api/conversations/2026-11-13") as res:
            assert json.loads(res.read()) == []
        server.shutdown()
        server.server_close()


def test_settings_save_a_key_without_ever_returning_it(site, monkeypatch, tmp_path):
    import os
    import stat

    from limitful import config, digest

    checked = []
    monkeypatch.setattr(digest, "check_claude", lambda key=None, model=None: checked.append(key))
    assert json.loads(site("/api/settings")[2])["provider"] is None

    status, _h, body = site("/api/settings", JSON, b'{"provider": "claude", "api_key": " sk-ant-api03-SECRETSECRET1234 "}')
    assert status == 200 and b"SECRETSECRET" not in body
    got = json.loads(body)
    assert (got["provider"], got["has_key"], got["key_hint"]) == ("claude", True, "ends in 1234")
    assert checked == ["sk-ant-api03-SECRETSECRET1234"]
    assert b"SECRETSECRET" not in site("/api/settings")[2]
    assert config.api_key() == "sk-ant-api03-SECRETSECRET1234"
    assert stat.S_IMODE(os.stat(config.config_path()).st_mode) == 0o600
    assert not list(tmp_path.glob("**/pendant.db-key*")) and "SECRET" not in (tmp_path / "pendant.db").read_bytes().decode("latin1")

    # Changing the provider alone keeps the key; an empty key removes it.
    assert json.loads(site("/api/settings", JSON, b'{"provider": "ollama"}')[2])["has_key"] is True
    after = json.loads(site("/api/settings", JSON, b'{"provider": "", "api_key": ""}')[2])
    assert (after["provider"], after["has_key"]) == (None, False)


def test_settings_reject_a_key_anthropic_refuses(site, monkeypatch):
    from limitful import config, digest

    def refuse(key=None, model=None):
        raise digest.DigestError("Anthropic did not accept that key")

    monkeypatch.setattr(digest, "check_claude", refuse)
    status, _h, body = site("/api/settings", JSON, b'{"provider": "claude", "api_key": "sk-ant-wrong-000000"}')
    assert status == 400 and b"Nothing was saved" in body
    assert config.load() == {}
    assert site("/api/settings", JSON, b'{"provider": "gpt"}')[0] == 400
    assert site("/api/settings", {"Content-Type": "text/plain"}, b'{}')[0] == 415
    assert site("/api/settings", dict(JSON, Host="evil.example"), b'{}')[0] == 403


def test_summarise_from_the_page(site, monkeypatch):
    import time

    from limitful import config, digest

    assert site("/api/digest", JSON, b"{}")[0] == 400  # nothing chosen yet

    class Canned:
        name = "canned"

        def summarize(self, transcript):
            return {"title": "A new title", "summary": ["Point."], "reminders": []}

    monkeypatch.setattr(digest, "make_summarizer", lambda provider, model=None, api_key=None: Canned())
    monkeypatch.setattr("limitful.store.MIN_DIGEST_WORDS", 1)
    config.update(provider="ollama")
    assert site("/api/digest", JSON, b"{}")[0] == 200
    for _ in range(100):
        job = json.loads(site("/api/status")[2])
        if not job["running"]:
            break
        time.sleep(0.05)
    assert job["error"] is None
    titles = [t["title"] for t in json.loads(site("/api/conversations/2026-11-13")[2])]
    assert "A new title" in titles and "Shopping and a call" in titles


def test_pendant_status_and_light(site, monkeypatch):
    from limitful import client, config

    reads = {"n": 0}

    async def read_state(timeout=8.0):
        reads["n"] += 1
        if reads["n"] == 2:
            raise client.PendantError("the pendant is not in range")
        return {"battery": 80, "pages": 100, "free_pages": 9000, "total_pages": 9100,
                "minutes_waiting": 2.4, "hours_free": 3.6}

    sent = []

    async def set_brightness(percent, timeout=8.0):
        sent.append(percent)

    monkeypatch.setattr(client, "read_state", read_state)
    monkeypatch.setattr(client, "set_brightness", set_brightness)

    before = json.loads(site("/api/pendant")[2])
    assert (before["checked"], before["brightness"]) == (None, None)  # reading the page touches no radio
    assert reads["n"] == 0

    got = json.loads(site("/api/pendant", JSON, b'{"action": "check"}')[2])
    assert (got["battery"], got["minutes_waiting"], got["error"]) == (80, 2.4, None) and got["checked"]
    failed = json.loads(site("/api/pendant", JSON, b'{"action": "check"}')[2])
    assert failed["error"] == "the pendant is not in range" and "battery" not in failed

    after = json.loads(site("/api/pendant", JSON, b'{"action": "brightness", "value": 35}')[2])
    assert sent == [35] and after["brightness"] == 35 and config.load()["led_brightness"] == 35
    for bad in (b'{"action": "brightness", "value": 101}', b'{"action": "brightness", "value": "bright"}',
                b'{"action": "brightness"}', b'{"action": "explode"}', b'[]'):
        assert site("/api/pendant", JSON, bad)[0] == 400
    assert sent == [35]
    assert site("/api/pendant", {"Content-Type": "text/plain"}, b'{"action": "check"}')[0] == 415
    assert site("/api/pendant", dict(JSON, Host="evil.example"), b'{"action": "check"}')[0] == 403


def test_sync_from_the_page_reports_when_the_pendant_is_away(site, monkeypatch):
    import time

    from limitful import client

    async def nobody(timeout=5.0):
        return []

    monkeypatch.setattr(client, "scan", nobody)
    assert site("/api/pendant", JSON, b'{"action": "sync"}')[0] == 200
    for _ in range(100):
        job = json.loads(site("/api/status")[2])
        if not job["running"]:
            break
        time.sleep(0.05)
    assert job["error"].startswith("Sync stopped: the pendant is not in range")


def test_pause_pair_and_unpair_from_the_page(site, monkeypatch):
    import time

    from limitful import client

    before = json.loads(site("/api/pendant")[2])
    assert before["paused_since"] is None
    paused = json.loads(site("/api/pendant", JSON, b'{"action": "pause"}')[2])
    assert paused["paused_since"] and json.loads(site("/api/pendant")[2])["paused_since"] == paused["paused_since"]
    assert json.loads(site("/api/pendant", JSON, b'{"action": "pause"}')[2])["paused_since"] == paused["paused_since"]
    assert json.loads(site("/api/pendant", JSON, b'{"action": "resume"}')[2])["paused_since"] is None

    calls = []

    async def unpair(timeout=8.0):
        calls.append("unpair")

    async def pair(timeout=180.0, log=print):
        calls.append(("pair", timeout))
        return None if len(calls) == 2 else object()

    monkeypatch.setattr(client, "unpair", unpair)
    monkeypatch.setattr(client, "pair", pair)
    assert site("/api/pendant", JSON, b'{"action": "unpair"}')[0] == 200 and calls == ["unpair"]

    def finished():
        for _ in range(100):
            job = json.loads(site("/api/status")[2])
            if not job["running"]:
                return job
            time.sleep(0.05)

    assert site("/api/pendant", JSON, b'{"action": "pair"}')[0] == 200
    assert finished()["error"].startswith("Pairing stopped: the pendant never accepted")
    assert site("/api/pendant", JSON, b'{"action": "pair"}')[0] == 200
    job = finished()
    assert (job["error"], job["note"]) == (None, "Paired. The pendant accepted this computer.")

    async def gone(timeout=8.0):
        raise client.PendantError("the pendant is not in range")

    monkeypatch.setattr(client, "unpair", gone)
    status, _h, body = site("/api/pendant", JSON, b'{"action": "unpair"}')
    assert status == 400 and b"Could not unpair: the pendant is not in range" in body


def test_transcription_settings_keep_the_deepgram_key_private(site, monkeypatch):
    import os
    import stat

    from limitful import config, digest, hosted

    checked = []
    monkeypatch.setattr(hosted, "check_deepgram", lambda key, base_url=None: checked.append(key))
    monkeypatch.setattr(digest, "check_claude", lambda key=None, model=None: pytest.fail("summaries were not touched"))
    start = json.loads(site("/api/settings")[2])
    assert (start["transcriber"], start["has_deepgram_key"], start["deepgram_key_hint"]) == ("local", False, None)

    # Deepgram cannot be chosen without a key, and nothing is sent to check one that is missing.
    status, _h, body = site("/api/settings", JSON, b'{"transcriber": "deepgram"}')
    assert status == 400 and b"needs an API key" in body and checked == [] and config.load() == {}

    status, _h, body = site("/api/settings", JSON, b'{"transcriber": "deepgram", "deepgram_api_key": " dg-SECRETSECRET9876 "}')
    assert status == 200 and b"SECRETSECRET" not in body
    got = json.loads(body)
    assert (got["transcriber"], got["has_deepgram_key"], got["deepgram_key_hint"]) == ("deepgram", True, "ends in 9876")
    assert got["provider"] is None  # the summaries choice is untouched
    assert checked == ["dg-SECRETSECRET9876"] and config.transcriber() == "deepgram"
    assert b"SECRETSECRET" not in site("/api/settings")[2]
    assert stat.S_IMODE(os.stat(config.config_path()).st_mode) == 0o600

    # Going back to this computer keeps the key; removing the key is explicit.
    assert json.loads(site("/api/settings", JSON, b'{"transcriber": "local"}')[2])["has_deepgram_key"] is True
    after = json.loads(site("/api/settings", JSON, b'{"transcriber": "local", "deepgram_api_key": ""}')[2])
    assert (after["transcriber"], after["has_deepgram_key"]) == ("local", False)
    assert site("/api/settings", JSON, b'{"transcriber": "deepgram", "deepgram_api_key": ""}')[0] == 400
    assert site("/api/settings", JSON, b'{"transcriber": "elsewhere"}')[0] == 400
    assert site("/api/settings", JSON, b'{"deepgram_api_key": 7}')[0] == 400


def test_transcription_settings_reject_a_key_deepgram_refuses(site, monkeypatch):
    from limitful import config, hosted

    def refuse(key, base_url=None):
        raise hosted.HostedError("Deepgram did not accept that key")

    monkeypatch.setattr(hosted, "check_deepgram", refuse)
    status, _h, body = site("/api/settings", JSON, b'{"transcriber": "deepgram", "deepgram_api_key": "dg-wrong-0000000"}')
    assert status == 400 and b"Nothing was saved" in body and config.load() == {}


def test_hosted_lines_show_numbered_speakers_without_the_import_lead(site, tmp_path):
    store = Store(tmp_path)
    store.db.execute("UPDATE utterances SET speaker_id = NULL, speaker_group = 'deepgram:1', source_speaker = '2' "
                     "WHERE text LIKE 'call%'")
    store.db.commit()
    store.close()
    day = datetime.fromtimestamp(T0 / 1000).strftime("%Y-%m-%d")
    reply = json.loads(site(f"/api/day/{day}")[2])
    found = [line for line in json.dumps(reply).split('"text"') if "call Joseph" in line]
    assert found and '"Speaker 2"' in json.dumps(reply)
    # Its audio offset is its own start (1.2 s in), not moved earlier as for imported lines.
    assert '"offset": 1200' in json.dumps(reply)
