"""The lookups behind Ask AI, and the endpoint, without calling Claude."""

import json
from datetime import datetime

import pytest

from limitful import ask, config, digest
from limitful.store import Store

T0 = int(datetime(2026, 11, 8, 13, 0, 0).timestamp() * 1000)


@pytest.fixture
def lookup(tmp_path):
    store = Store(tmp_path)
    store.db.execute("INSERT INTO speakers (id, name, voice_sum, lines) VALUES (1, 'Joseph', x'', 0)")
    said = [
        (0, "We should confirm the hardware budget before Friday", 1, None, None),
        (5, "the budget is 100% fixed", None, "conv", "2"),
        (10, "what about lunch", None, None, None),
        (24 * 3600, "Joseph called about the hardware", None, None, None),
    ]
    for seconds, text, speaker, source, label in said:
        store.db.execute(
            "INSERT INTO utterances (segment, start_ms, end_ms, text, speaker_id, source, source_speaker) "
            "VALUES ('', ?, ?, ?, ?, ?, ?)",
            (T0 + seconds * 1000, T0 + seconds * 1000 + 900, text, speaker, source, label))
    store.db.execute("INSERT INTO conversations (id, start_ms, end_ms, status, title) "
                     "VALUES (7, ?, ?, 'done', 'Budget talk')", (T0, T0 + 11_000))
    store.db.execute("INSERT INTO sections (conversation_id, start_ms, level, title) VALUES (7, ?, 2, 'Money')", (T0,))
    store.db.commit()
    store.close()
    found = ask.Lookup(tmp_path)
    yield found
    found.close()


def test_search_ranks_lines_with_more_of_the_words_first(lookup):
    out = lookup.search("hardware budget").splitlines()
    assert out[0].startswith("3 lines contain at least one of: hardware, budget.")
    assert out[1] == '[L1] 2026-11-08 13:00 Joseph (conversation 7 "Budget talk"): We should confirm the hardware budget before Friday'
    assert out[2].startswith("[L4] 2026-11-09 13:00 Unknown (conversation untitled): Joseph called")  # newer of the rest
    assert out[3].startswith('[L2] 2026-11-08 13:00 Speaker 2 (conversation 7 "Budget talk")')


def test_search_dates_wildcards_and_misses(lookup):
    assert "[L4]" not in lookup.search("hardware", end_date="2026-11-08")
    assert "[L1]" not in lookup.search("hardware", start_date="2026-11-09")
    assert lookup.search("100%").count("[L") == 1  # "%" is a character, not a wildcard
    assert lookup.search("zebra") == "No line contains any of: zebra."
    assert lookup.search("  ") == "Give at least one word to search for."
    assert lookup.search("budget", start_date="yesterday").startswith("Dates must look like")


def test_listing_and_reading_conversations(lookup):
    assert lookup.conversations("2026-11-08", "2026-11-08").splitlines() == [
        "1 conversations:",
        "conversation 7 | 2026-11-08 13:00 to 13:00 | 3 lines | Budget talk | sections: Money"]
    assert lookup.conversations("2026-11-09") == "No titled conversations in that range."
    text = lookup.read(7).splitlines()
    assert text[0] == 'Conversation 7, "Budget talk", 2026-11-08 13:00, 3 lines.'
    assert text[1:] == ["[L1] 13:00 Joseph: We should confirm the hardware budget before Friday",
                        "[L2] 13:00 Speaker 2: the budget is 100% fixed", "[L3] 13:00 Unknown: what about lunch"]
    assert lookup.read(7, skip=2).splitlines()[0].endswith("Showing lines 3 to 3.")
    assert lookup.read(99) == "There is no conversation 99."
    assert lookup.coverage() == "The Lifelog holds 4 lines from 2026-11-08 to 2026-11-09."


def test_citations_become_places_to_go(lookup):
    cited = lookup.cited("You agreed to confirm it [L1], and Joseph called later [L4][L999]. [L1]")
    assert set(cited) == {"1", "4"}  # unknown ids are dropped
    assert cited["1"] == {"day": "2026-11-08", "start": T0, "conversation": 7,
                          "text": "We should confirm the hardware budget before Friday"}
    assert cited["4"]["conversation"] is None and cited["4"]["day"] == "2026-11-09"


def test_asking_needs_a_question():
    with pytest.raises(digest.DigestError):
        ask.answer("unused", [{"role": "assistant", "content": "hello"}])


def test_ask_endpoint_streams_steps_then_the_answer(tmp_path, monkeypatch):
    import threading
    import urllib.error
    import urllib.request

    from limitful.web import make_server

    def fake_answer(data_dir, history, api_key=None, model=None, on_step=lambda s: None,
                    on_text=lambda t: None):
        on_text("Let me look.")
        on_text(None)
        on_step("Searching for “budget”")
        if history[-1]["content"] == "break":
            raise digest.DigestError("could not reach the Anthropic API")
        on_text("You asked: ")
        on_text("something")
        return {"answer": f"You asked: {history[-1]['content']} [L1]", "lines": {"1": {"day": "2026-11-08"}}}

    monkeypatch.setattr(ask, "answer", fake_answer)
    server = make_server(tmp_path, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/api/ask"

    def post(body, headers=None):
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers=headers or {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, [json.loads(line) for line in res.read().splitlines()]
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode()

    def get(path):
        with urllib.request.urlopen(url.replace("/api/ask", path)) as res:
            return json.loads(res.read())

    question = {"question": "what about the budget?"}
    status, body = post(question)
    assert status == 400 and "Choose Claude in Settings" in body  # nothing is sent until Claude is chosen

    config.update(provider="claude")
    assert post(question) == (200, [
        {"text": "Let me look."}, {"text": None},
        {"step": "Searching for “budget”"},
        {"text": "You asked: "}, {"text": "something"},
        {"answer": "You asked: what about the budget? [L1]", "lines": {"1": {"day": "2026-11-08"}}, "chat": 1}])

    # The thread is saved, and a follow-up is answered with it as context.
    assert [(c["id"], c["title"], c["questions"]) for c in get("/api/chats")] == [(1, "what about the budget?", 1)]
    seen = []
    monkeypatch.setattr(ask, "answer", lambda d, history, *a, **k: seen.append(history) or {"answer": "Friday", "lines": {}})
    assert post({"question": "and when?", "chat": 1})[1][-1]["chat"] == 1
    assert [m["content"] for m in seen[0]] == ["what about the budget?", "You asked: what about the budget? [L1]", "and when?"]
    thread = get("/api/chats/1")
    assert [(m["role"], m["content"]) for m in thread] == [
        ("user", "what about the budget?"), ("assistant", "You asked: what about the budget? [L1]"),
        ("user", "and when?"), ("assistant", "Friday")]
    assert thread[1]["lines"] == {"1": {"day": "2026-11-08"}}
    assert get("/api/chats")[0]["questions"] == 2

    # A question that fails is not saved.
    monkeypatch.setattr(ask, "answer", fake_answer)
    assert post({"question": "break"})[1][-1] == {"error": "could not reach the Anthropic API"}
    assert len(get("/api/chats")) == 1

    assert post({"question": "  "})[0] == 400
    assert post({"question": "x", "chat": "one"})[0] == 400
    assert post(question, {"Content-Type": "text/plain"})[0] == 415
    assert post(question, {"Content-Type": "application/json", "Host": "evil.example"})[0] == 403

    req = urllib.request.Request(url.replace("/api/ask", "/api/chats/1/delete"), data=b"{}",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        assert json.loads(res.read()) == {"deleted": 1}
    assert get("/api/chats") == [] and get("/api/chats/1") == []
    server.shutdown()
    server.server_close()
