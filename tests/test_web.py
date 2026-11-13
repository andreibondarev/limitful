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
    assert talk["reminders"] == [{"id": 1, "text": "Call Joseph", "status": "suggested"}]
    assert json.loads(site("/api/conversations/2026-11-14")[2]) == []
    assert site("/api/conversations/soon")[0] == 400

    (reminder,) = json.loads(site("/api/reminders")[2])
    assert (reminder["text"], reminder["from"], reminder["status"]) == ("Call Joseph", "Shopping and a call", "suggested")
    status, _h, body = site("/api/reminders/1", JSON, b'{"status": "accepted"}')
    assert (status, json.loads(body)) == (200, {"id": 1, "status": "accepted"})
    assert json.loads(site("/api/reminders")[2])[0]["status"] == "accepted"
    assert site("/api/reminders/1", JSON, b'{"status": "dismissed"}')[0] == 200
    assert json.loads(site("/api/reminders")[2]) == []


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
