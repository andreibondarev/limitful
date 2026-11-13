"""Conversations, summaries and reminders, with stand-ins for the language model."""

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pendant_sync import digest
from pendant_sync.store import Store

T0 = int(datetime(2026, 11, 13, 9, 0, 0).timestamp() * 1000)
MIN = 60_000
LONG = ("we should finish the quarterly report by Thursday and keep it under ten pages "
        "with the detailed tables moved into an appendix for the client to read later")


class Canned:
    name = "canned"

    def __init__(self, fail_on=None):
        self.seen = []
        self.fail_on = fail_on

    def summarize(self, transcript):
        self.seen.append(transcript)
        if self.fail_on and self.fail_on in transcript:
            raise self.fail_on_error
        return {"title": f"Talk {len(self.seen)}", "summary": ["One.", "Two."],
                "reminders": ["Send the template"] if "report" in transcript else []}


def say(store, minute, text, speaker=None):
    start = T0 + minute * MIN
    store.db.execute(
        "INSERT INTO utterances (segment, start_ms, end_ms, text, speaker_id) VALUES ('x', ?, ?, ?, ?)",
        (start, start + 5000, text, speaker))
    store.db.commit()


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path)
    yield s
    s.close()


def test_conversations_split_at_long_silences_and_wait_for_the_last(store):
    say(store, 0, "a"); say(store, 2, "b"); say(store, 10, "c"); say(store, 30, "d")
    # Three minutes after the last line, it may still be going on.
    assert store.build_conversations(now_ms=T0 + 33 * MIN) == 2
    assert store.build_conversations(now_ms=T0 + 33 * MIN) == 0
    assert store.build_conversations(now_ms=T0 + 40 * MIN) == 1
    spans = store.db.execute("SELECT start_ms, end_ms FROM conversations ORDER BY start_ms").fetchall()
    assert [(a - T0) // MIN for a, _b in spans] == [0, 10, 30]
    assert spans[0][1] == T0 + 2 * MIN + 5000


def test_digest_writes_titles_summaries_and_reminders(store, tmp_path):
    store.db.execute("INSERT INTO speakers (id, name, voice_sum, lines) VALUES (1, 'Karen', x'00', 1)")
    say(store, 0, LONG, speaker=1)
    say(store, 1, "sounds good to me")
    say(store, 20, "okay")  # too little to summarise
    canned = Canned()
    assert store.digest_pending(canned) == 1
    assert canned.seen == [f"[09:00] Karen: {LONG}\n[09:01] Unknown: sounds good to me"]
    assert store.db.execute("SELECT status, title FROM conversations ORDER BY start_ms").fetchall() == [
        ("done", "Talk 1"), ("short", None)]

    (talk,) = store.conversations(T0, T0 + 24 * 60 * MIN)
    assert (talk["title"], talk["summary"]) == ("Talk 1", ["One.", "Two."])
    assert [(r["text"], r["status"]) for r in talk["reminders"]] == [("Send the template", "suggested")]

    text = (tmp_path / "transcripts" / "2026-11-13.md").read_text()
    assert "## 09:00 Talk 1\n\n> One.\n> Two.\n\n- **09:00:00** Karen: we should finish" in text
    assert "- **09:20:00** okay" in text
    assert store.digest_pending(canned) == 0 and len(canned.seen) == 1  # nothing left to do


def test_reminder_states(store):
    say(store, 0, LONG)
    store.digest_pending(Canned())
    (reminder,) = store.reminders()
    assert (reminder["status"], reminder["from"]) == ("suggested", "Talk 1")
    store.set_reminder_status(reminder["id"], "accepted")
    assert store.reminders()[0]["status"] == "accepted"
    store.set_reminder_status(reminder["id"], "done")
    assert store.reminders() == []  # finished ones drop off the list
    with pytest.raises(ValueError):
        store.set_reminder_status(reminder["id"], "maybe")
    with pytest.raises(ValueError):
        store.set_reminder_status(999, "done")


def test_engine_failure_keeps_finished_work_and_retries_the_rest(store):
    say(store, 0, LONG)
    say(store, 30, LONG + " second")
    flaky = Canned(fail_on="second")
    flaky.fail_on_error = digest.DigestError("offline")
    with pytest.raises(digest.DigestError):
        store.digest_pending(flaky)
    assert [s for (s,) in store.db.execute("SELECT status FROM conversations ORDER BY start_ms")] == [
        "done", "pending"]
    assert store.digest_pending(Canned()) == 1  # the second run only does what is left


def test_declined_conversation_is_not_retried(store):
    say(store, 0, LONG)
    refusing = Canned(fail_on="report")
    refusing.fail_on_error = digest.DigestDeclined("no")
    assert store.digest_pending(refusing) == 0
    assert store.db.execute("SELECT status FROM conversations").fetchone() == ("skipped",)
    assert store.digest_pending(Canned()) == 0


def test_redo_discards_and_rebuilds(store):
    say(store, 0, LONG)
    store.digest_pending(Canned())
    store.forget_digests()
    assert store.reminders() == [] and store.conversations(T0, T0 + MIN) == []
    assert store.digest_pending(Canned()) == 1


def test_clean_accepts_sloppy_replies_and_rejects_useless_ones():
    got = digest.clean({"title": "  Budget\n review ", "summary": "One point.",
                        "reminders": ["  Call  Joseph ", "", 7, "x"] + ["more"] * 20})
    assert got == {"title": "Budget review", "summary": ["One point."],
                   "reminders": ["Call Joseph", "x"] + ["more"] * 8}
    assert digest.clean({"title": "T"}) == {"title": "T", "summary": [], "reminders": []}
    for bad in ({"title": "   "}, {"summary": []}, ["title"], "title", {"title": 5}):
        with pytest.raises(digest.DigestError):
            digest.clean(bad)


@pytest.fixture
def ollama():
    """A stand-in Ollama server that records the request and replies as configured."""
    state = {"reply": {"message": {"content": json.dumps(
        {"title": "Local title", "summary": ["S"], "reminders": []})}}, "status": 200}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            state["path"] = self.path
            state["request"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps(state["reply"]).encode()
            self.send_response(state["status"])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["host"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()
    server.server_close()


def test_ollama_request_and_reply(ollama):
    engine = digest.OllamaSummarizer("tiny", ollama["host"])
    assert engine.summarize("[09:00] A: hello") == {"title": "Local title", "summary": ["S"], "reminders": []}
    request = ollama["request"]
    assert ollama["path"] == "/api/chat"
    assert (request["model"], request["stream"], request["format"]) == ("tiny", False, "json")
    assert request["messages"][0] == {"role": "system", "content": digest.SYSTEM}
    assert request["messages"][1] == {"role": "user", "content": "[09:00] A: hello"}


def test_ollama_failures_are_explained(ollama):
    engine = digest.OllamaSummarizer("tiny", ollama["host"])
    ollama["reply"] = {"message": {"content": "not json"}}
    with pytest.raises(digest.DigestError, match="not valid JSON"):
        engine.summarize("x")
    ollama["status"], ollama["reply"] = 404, {"error": "model not found"}
    with pytest.raises(digest.DigestError, match="ollama pull tiny"):
        engine.summarize("x")
    with pytest.raises(digest.DigestError, match="ollama serve"):
        digest.OllamaSummarizer("tiny", "http://127.0.0.1:9").summarize("x")


def test_unknown_provider():
    with pytest.raises(ValueError):
        digest.make_summarizer("gpt")
