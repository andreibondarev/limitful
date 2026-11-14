"""Upkeep jobs run from the Lifelog: re-timing imported lines and building the search index."""

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from limitful import search, transcribe, upkeep
from limitful.importer import import_limitless
from limitful.store import Store
from limitful.web import Library, make_server

from test_importer import make_zip, quiet
from test_search import Topics


def wait_until(check, what="the job"):
    deadline = time.monotonic() + 5
    while not check():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.01)


@pytest.fixture
def imported(tmp_path):
    """A data folder with two imported recordings that both have lines to re-time."""
    data = tmp_path / "data"
    store = Store(data)
    import_limitless(store, make_zip(tmp_path / "export.zip"), log=quiet)
    other, = [p for (p,) in store.db.execute("SELECT path FROM segments") if "23h59m50s" in p]
    store.db.execute("UPDATE utterances SET segment = ? WHERE text LIKE 'Does it take%'", (other,))
    store.db.commit()
    assert len(store.pending_retime()) == 2
    store.close()
    return data


class SlowWhisper:
    """Stands in for Whisper: hears nothing, and takes as long as the test lets it."""

    go = threading.Event()
    heard: list = []

    def __init__(self, *args, **kwargs):
        pass

    def words(self, path):
        SlowWhisper.heard.append(path.name)
        assert SlowWhisper.go.wait(5)
        return [(6.8, "it"), (7.1, "helps"), (7.4, "with"), (7.7, "bone"), (8.0, "density")]


@pytest.fixture
def whisper(monkeypatch):
    SlowWhisper.go = threading.Event()
    SlowWhisper.heard = []
    monkeypatch.setattr(transcribe, "WhisperTranscriber", SlowWhisper)
    return SlowWhisper


def test_status_counts_what_is_left(imported):
    library = Library(imported)
    assert upkeep.status(library) == {
        "retime": {"recordings": 2, "hours": 0.0},
        "index": {"indexed": 0, "total": 3, "left": 3}}
    assert not (imported / "search.db").exists()  # looking creates nothing


def test_retime_shows_progress_stops_between_recordings_and_resumes(imported, whisper):
    library = Library(imported)
    upkeep.start_retime(library)
    wait_until(lambda: len(whisper.heard) == 1, "the first recording")
    assert library.job["running"] and library.job["stoppable"] and library.job["total"] == 2
    assert library.job["done"] == 0

    # Nothing else may start while it runs, and it may not start twice.
    for start in (upkeep.start_retime, upkeep.start_index, Library.start_sync,
                  lambda lib: lib.import_export(None, 0)):
        with pytest.raises(RuntimeError):
            start(library)

    upkeep.stop(library)
    assert "stopping" in library.job["what"] and library.job["running"]  # the current one finishes
    whisper.go.set()
    wait_until(lambda: not library.job["running"])
    assert len(whisper.heard) == 1  # the second recording was never opened
    assert library.job["error"] is None and library.job["done"] == 1
    assert library.job["note"] == "Re-timed 1 line in 1 recording. 1 left; start again to continue."  # newest first
    assert upkeep.status(library)["retime"]["recordings"] == 1
    with pytest.raises(ValueError):
        upkeep.stop(library)  # nothing is running any more

    # Starting again picks up the recording that was left.
    upkeep.start_retime(library)
    wait_until(lambda: not library.job["running"])
    assert len(whisper.heard) == 2 and whisper.heard[0] != whisper.heard[1]
    assert library.job["note"] == "Re-timed 2 lines in 1 recording. All done."
    assert upkeep.status(library)["retime"]["recordings"] == 0

    upkeep.start_retime(library)
    wait_until(lambda: not library.job["running"])
    assert library.job["note"] == "Every imported recording is already re-timed."


def test_a_failure_is_reported_and_frees_the_job_slot(imported, monkeypatch):
    class Broken:
        def __init__(self, *args, **kwargs):
            raise OSError("no model")

    monkeypatch.setattr(transcribe, "WhisperTranscriber", Broken)
    library = Library(imported)
    upkeep.start_retime(library)
    wait_until(lambda: not library.job["running"])
    assert library.job["error"] == "Fixing the timing of imported lines stopped: no model"
    assert library.job["stoppable"] is False


def test_index_job_builds_and_can_be_stopped(imported, monkeypatch):
    gate, working = threading.Event(), threading.Event()

    class Slow(Topics):
        def embed(self, texts, query=False):
            working.set()
            assert gate.wait(5)
            return super().embed(texts, query)

    monkeypatch.setattr(search, "make_embedder", lambda: Slow())
    monkeypatch.setattr(search, "_BATCH", 1)
    library = Library(imported)
    upkeep.start_index(library)
    assert working.wait(5)
    upkeep.stop(library)
    gate.set()
    wait_until(lambda: not library.job["running"])
    # It stopped after the batch in hand; everything indexed so far was kept.
    first = upkeep.status(library)["index"]
    assert 1 <= first["indexed"] < 3 and library.job["note"].endswith("start again to continue.")

    upkeep.start_index(library)
    wait_until(lambda: not library.job["running"])
    assert upkeep.status(library)["index"] == {"indexed": 3, "total": 3, "left": 0}
    assert library.job["note"].startswith(f"Indexed {3 - first['indexed']} line")
    assert library.job["note"].endswith("for search by meaning. All done.")


def test_upkeep_over_http(imported, whisper):
    server = make_server(imported, 0, link_speakers=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def call(path, body=None):
        req = urllib.request.Request(
            base + path, data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"} if body is not None else {})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode()

    try:
        assert call("/api/upkeep")[1]["retime"] == {"recordings": 2, "hours": 0.0}
        assert call("/api/upkeep", {"action": "stop"})[0] == 400      # nothing to stop
        assert call("/api/upkeep", {"action": "explode"})[0] == 400
        assert call("/api/upkeep", {"action": "retime"}) == (200, {"ok": True})
        wait_until(lambda: len(whisper.heard) == 1)
        job = call("/api/status")[1]
        assert job["running"] and job["stoppable"]
        assert call("/api/upkeep", {"action": "index"})[0] == 409     # busy
        assert call("/api/upkeep", {"action": "stop"}) == (200, {"ok": True})
        whisper.go.set()
        wait_until(lambda: not call("/api/upkeep")[1]["retime"]["recordings"] == 2)
        assert call("/api/upkeep")[1]["retime"]["recordings"] == 1
    finally:
        whisper.go.set()
        server.shutdown()
        server.server_close()
