"""Search by meaning: the index, the lookups built on it, and where they surface."""

import hashlib
import json
import threading
import urllib.request

import numpy as np
import pytest

from limitful import ask, search
from limitful.cli import main
from limitful.store import Store
from limitful.transcribe import Utterance
from limitful.web import Library, make_server

T0 = 1_794_000_000_000


class Topics:
    """Stands in for the model: text about the same subject gets the same direction."""

    name = "topics"
    SUBJECTS = [
        {"camera", "doorbell", "security", "porch"},
        {"sauna", "heat", "cabin", "sweat"},
        {"moldova", "country", "born", "originally"},
        {"ticket", "premium", "price", "cost"},
    ]

    def __init__(self):
        self.calls = 0

    def embed(self, texts, query=False):
        self.calls += len(texts)
        out = np.full((len(texts), len(self.SUBJECTS) + 1), 0.01, dtype=np.float32)
        for row, text in zip(out, texts):
            words = set(text.lower().replace(".", " ").replace("?", " ").split())
            for i, subject in enumerate(self.SUBJECTS):
                row[i] += len(words & subject)
            row[-1] += 0.2  # everything has a little in common
        return out / np.linalg.norm(out, axis=1, keepdims=True)


LINES = [  # (seconds after T0, text)
    (0, "We should get a doorbell for the porch."),
    (4, "Yeah."),
    (8, "Mom would feel safer."),
    (300, "The sauna was two thousand at the expo."),
    (304, "That much for a cabin that makes you sweat?"),
    (900, "I was born in Moldova."),
    (904, "Mhm."),
]


def add_lines(store, lines, segment="a.ogg"):
    store.db.executemany(
        "INSERT INTO utterances (segment, start_ms, end_ms, text) VALUES (?, ?, ?, ?)",
        [(segment, T0 + s * 1000, T0 + s * 1000 + 900, text) for s, text in lines])
    store.db.commit()


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path)
    add_lines(store, LINES)
    yield store
    store.close()


def ids(store, *texts):
    return [store.db.execute("SELECT id FROM utterances WHERE text = ?", (t,)).fetchone()[0] for t in texts]


def test_a_line_is_indexed_with_its_close_neighbours():
    rows = [(i, T0 + s * 1000, text) for i, (s, text) in enumerate(LINES)]
    texts = search.passages(rows)
    assert texts[1] == "We should get a doorbell for the porch. Yeah. Mom would feel safer."
    # Lines minutes away are another exchange and stay out of it.
    assert texts[2] == "We should get a doorbell for the porch. Yeah. Mom would feel safer."
    assert texts[3] == "The sauna was two thousand at the expo. That much for a cabin that makes you sweat?"
    assert texts[6] == "I was born in Moldova. Mhm."


def test_build_search_and_progress(store, tmp_path):
    index, model = search.Index(tmp_path), Topics()
    assert index.progress(store) == {"indexed": 0, "total": 7, "left": 7}
    assert index.search(model, "security camera") == [] and not index.exists()

    seen = []
    assert index.build(store, model, on_progress=lambda done, total: seen.append((done, total))) == 7
    assert seen[-1] == (7, 7) and index.progress(store)["left"] == 0

    # None of these words are in the lines; the subject is.
    best = index.search(model, "security camera for my parents", limit=3)
    assert {uid for uid, _s in best} == set(ids(store, *[t for _s, t in LINES[:3]]))
    assert best[0][1] > 0.9
    # "Yeah." and "Mhm." are found through the lines around them.
    assert ids(store, "Mhm.")[0] in [uid for uid, _s in index.search(model, "which country was I born in", limit=2)]

    # Limited to some lines (a date range), only those come back.
    sauna = set(ids(store, LINES[3][1], LINES[4][1]))
    assert {uid for uid, _s in index.search(model, "security camera", only=sauna)} == sauna
    assert index.search(model, "   ") == []


def test_building_is_incremental_and_can_be_stopped(store, tmp_path, monkeypatch):
    monkeypatch.setattr(search, "_BATCH", 2)
    index, model = search.Index(tmp_path), Topics()
    stops = iter([False, False, True])
    assert index.build(store, model, should_stop=lambda: next(stops)) == 4  # two batches, then stopped
    assert index.progress(store) == {"indexed": 4, "total": 7, "left": 3}
    assert index.build(store, model) == 3 and model.calls == 7              # carried on; nothing redone
    assert index.build(store, model) == 0 and model.calls == 7

    add_lines(store, [(2000, "The premium ticket is nine hundred.")], "b.ogg")
    assert index.progress(store)["left"] == 1
    assert index.build(store, model) == 1 and model.calls == 8              # only the new line

    # A re-transcription replaces lines; the old ones leave the index.
    store.db.execute("DELETE FROM utterances WHERE text = 'Mhm.'")
    store.db.commit()
    assert index.build(store, model) == 0
    assert index.progress(store) == {"indexed": 7, "total": 7, "left": 0}
    assert len(index.search(model, "anything", limit=50)) == 7


def test_an_index_from_another_model_is_rebuilt(store, tmp_path, monkeypatch):
    index, model = search.Index(tmp_path), Topics()
    index.build(store, model)
    monkeypatch.setattr(search, "MODEL", "a-newer-model")
    assert index.progress(store)["left"] == 7
    assert index.build(store, model) == 7 and index.progress(store)["left"] == 0


def test_hits_from_the_same_moment_are_shown_once():
    start = {1: 0, 2: 4_000, 3: 300_000, 4: 302_000, 5: 900_000}
    hits = [(2, 0.9), (1, 0.89), (4, 0.8), (99, 0.79), (3, 0.7), (5, 0.6)]
    assert search.spread(hits, start, 10) == [(2, 0.9), (4, 0.8), (5, 0.6)]
    assert search.spread(hits, start, 2) == [(2, 0.9), (4, 0.8)]


def test_new_lines_join_an_index_that_exists_and_none_is_made_unasked(tmp_path, monkeypatch):
    model = Topics()
    monkeypatch.setattr(search, "make_embedder", lambda: model)

    class Heard:
        name = "fake"

        def transcribe(self, path):
            return [Utterance(0, 900, "The sauna cabin was hot.")]

    store = Store(tmp_path)
    try:
        store.db.execute("INSERT INTO segments (path, start_ms, duration_ms, first_page, last_page) VALUES ('audio/x.ogg', ?, 5000, 0, 0)", (T0,))
        store.transcribe_pending(Heard())
        assert not (tmp_path / "search.db").exists() and model.calls == 0  # not in use: nothing happens

        search.Index(tmp_path).build(store, model)
        store.db.execute("INSERT INTO segments (path, start_ms, duration_ms, first_page, last_page) VALUES ('audio/y.ogg', ?, 5000, 0, 0)", (T0 + 9000,))
        store.transcribe_pending(Heard())
        assert search.Index(tmp_path).progress(store) == {"indexed": 2, "total": 2, "left": 0}

        # A failure while indexing never loses the transcription it followed.
        monkeypatch.setattr(search, "make_embedder", lambda: 1 / 0)
        store.db.execute("INSERT INTO segments (path, start_ms, duration_ms, first_page, last_page) VALUES ('audio/z.ogg', ?, 5000, 0, 0)", (T0 + 19000,))
        assert store.transcribe_pending(Heard())[0] == 1
        assert search.Index(tmp_path).progress(store)["left"] == 1
    finally:
        store.close()


def test_the_model_download_is_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("LIMITFUL_CACHE", str(tmp_path / "cache"))
    good = b"model bytes"
    monkeypatch.setattr(search, "_FILES", {"m.onnx": ("onnx/m.onnx", hashlib.sha256(good).hexdigest())})
    asked = []

    def fetch(url, to):
        asked.append(url)
        open(to, "wb").write(b"tampered" if len(asked) == 1 else good)

    monkeypatch.setattr(search.urllib.request, "urlretrieve", fetch)
    with pytest.raises(RuntimeError, match="checksum"):
        search.ensure_model()
    assert list((tmp_path / "cache").iterdir()) == []            # nothing unchecked is left behind
    path = search.ensure_model()["m.onnx"]
    assert path.read_bytes() == good and asked[0].startswith(search._SOURCE)
    search.ensure_model()
    assert len(asked) == 2                                       # kept; not fetched again


def test_ask_gets_the_tool_only_once_an_index_exists(store, tmp_path):
    lookup = ask.Lookup(tmp_path)
    try:
        assert not lookup.has_meaning()
        assert "search_meaning" not in ask.system_prompt(False) and "{meaning}" not in ask.system_prompt(False)
        search.index_for(tmp_path).build(store, Topics())
        assert lookup.has_meaning() and "search_meaning finds lines" in ask.system_prompt(True)

        found = lookup.meaning("security camera for my parents", embedder=Topics())
        first = found.splitlines()[1]
        assert first.startswith("[L") and ("doorbell" in first or "Yeah." in first or "Mom" in first)
        # The three doorbell lines are one moment, so they take one place, not three.
        assert sum(t in found for t in ("doorbell", "Yeah.", "Mom would")) == 1
        assert "not indexed yet" not in found

        day = "2026-11-06"
        assert lookup.meaning("sauna", "2031-01-01", "", embedder=Topics()) == "Nothing is indexed in those dates."
        assert lookup.meaning("sauna", "2026-99-01", embedder=Topics()) == "Dates must look like 2026-11-08."
        assert lookup.meaning(" ", day) == "Say what to look for."

        add_lines(store, [(5000, "A new line.")], "c.ogg")
        assert "(1 lines are not indexed yet" in lookup.meaning("sauna", embedder=Topics())
    finally:
        lookup.close()


def test_search_box_offers_lines_close_in_meaning(store, tmp_path, monkeypatch):
    model = Topics()
    monkeypatch.setattr(search, "make_embedder", lambda: model)
    library = Library(tmp_path)
    assert library.search_meaning("security camera") == {"ready": False, "lines": []}

    search.index_for(tmp_path).build(store, model)
    server = make_server(tmp_path, 0, link_speakers=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        def get(path):
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}{path}") as res:
                return json.loads(res.read())

        found = get("/api/search/meaning?q=security%20camera")
        # Closest moment first, each shown whole: the doorbell talk, then the other two.
        assert found["ready"] and found["lines"][0]["day"]
        assert [u["text"] for u in found["lines"] if u["moment"] == 0] == [t for _s, t in LINES[:3]]
        assert sorted(u["text"] for u in found["lines"]) == sorted(t for _s, t in LINES)
        assert [u["moment"] for u in found["lines"]] == [0, 0, 0, 1, 1, 2, 2]
        assert get("/api/search/meaning?q=") == {"ready": True, "lines": []}
        # Exact-word search is untouched by any of this.
        assert [u["text"] for u in get("/api/search?q=doorbell")] == [LINES[0][1]]
    finally:
        server.shutdown()
        server.server_close()


def test_index_command(store, tmp_path, monkeypatch, capsys):
    model = Topics()
    monkeypatch.setattr(search, "make_embedder", lambda: model)
    assert main(["index", "--data-dir", str(tmp_path), "--find", "sauna"]) != 0   # no index yet
    assert main(["index", "--data-dir", str(tmp_path)]) == 0
    assert "Indexed 7 line(s)" in capsys.readouterr().out
    assert main(["index", "--data-dir", str(tmp_path)]) == 0
    assert "already indexed" in capsys.readouterr().out
    assert main(["index", "--data-dir", str(tmp_path), "--find", "how hot is the sauna cabin"]) == 0
    assert "sauna" in capsys.readouterr().out.splitlines()[0]
    assert main(["index", "--data-dir", str(tmp_path), "--remove"]) == 0
    assert not (tmp_path / "search.db").exists()
