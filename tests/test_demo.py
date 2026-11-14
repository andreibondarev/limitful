"""The made-up data folder holds together and shows up through the Lifelog."""

from datetime import date

import pytest

from limitful import demo
from limitful.store import Store
from limitful.web import Library


def test_demo_folder_is_complete_and_consistent(tmp_path):
    made = demo.build(tmp_path, today=date(2026, 3, 12))
    assert made == {"conversations": 8, "lines": 45, "days": 3, "reminders": 6}

    library = Library(tmp_path)
    assert [d["day"] for d in library.days()] == ["2026-03-10", "2026-03-11", "2026-03-12"]
    talks = library.conversations("2026-03-11")
    assert [t["title"] for t in talks][:2] == [
        "Morning plan: deliveries and the Saturday workshop", "Supplier call about the late wheel order"]
    assert [s["title"] for s in talks[0]["sections"]] == ["Deliveries", "Saturday workshop"]
    assert {line["speaker"]["name"] for line in library.day("2026-03-11")} >= {"Sam", "Priya", "Marco", "Dana"}

    # Every reminder points at a line inside its own conversation.
    reminders = library.reminders(include_done=True)
    assert sorted(r["status"] for r in reminders) == ["accepted", "accepted", "done", "suggested", "suggested", "suggested"]
    assert all(r["line"] and r["line"]["text"] for r in reminders)

    recap = library.recap("2026-03-11")["recap"]
    assert recap["headline"].startswith("Chasing the late wheel order") and recap["stale"] is False

    store = Store(tmp_path)
    (chat,) = store.chats()
    answer = store.chat_messages(chat["id"])[1]
    assert len(answer["lines"]) == 4 and all(f"[L{uid}]" in answer["content"] for uid in answer["lines"])
    assert "{" not in answer["content"]
    store.close()

    with pytest.raises(ValueError, match="already has conversations"):
        demo.build(tmp_path)
