import json
import threading
import urllib.error
import urllib.request
from datetime import datetime

import pytest

from pendant_sync.protocol import FlashPage
from pendant_sync.store import Store
from pendant_sync.transcribe import Utterance
from pendant_sync.web import make_server

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
    store.close()
    (tmp_path / "secret.txt").write_text("private")

    server = make_server(tmp_path, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def fetch(path, headers=None):
        req = urllib.request.Request(base + path, headers=headers or {})
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
