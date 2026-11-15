"""A data folder of made-up conversations, for trying the Lifelog without a pendant.

Everything here is invented: the people, the companies, the conference and
what they say. Sam sells route-planning software and spends two days at a
trade show meeting people who might buy it. The lines have no audio behind
them, so they can be read, searched and asked about but not played.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .store import Store

ME = "Sam"

# (days before today, start time, title, summary points, [(heading or None, [(speaker, line), ...])])
TALKS = [
    (2, "08:20", "Setting up the booth and who to find", [
        "The goal for the summit is ten conversations worth a follow-up.",
        "Castellan Foods and Nordvik Cold Chain are the two companies to find in person.",
    ], [
        (None, [
            ("Nadia", "Screen's up and the demo is running. What are we actually trying to leave with?"),
            (ME, "Ten conversations worth a follow-up. A badge scan doesn't count unless they run a fleet."),
            ("Nadia", "Anyone in particular?"),
            (ME, "Castellan Foods and Nordvik Cold Chain. Both have people speaking tomorrow, so I'll catch them after their sessions."),
        ]),
    ]),
    (2, "14:15", "Booth chat with a bike courier startup", [
        "Grace runs Pedalpost: forty riders across two cities, planned in a spreadsheet.",
        "Sam will send her the starter-plan pricing, which charges per route.",
    ], [
        (None, [
            ("Grace", "We're forty riders across two cities. Everything I've looked at is priced for companies ten times our size."),
            (ME, "How are you planning the routes today?"),
            ("Grace", "A spreadsheet and a group chat. It falls over every time it rains."),
            (ME, "We have a starter plan that charges per route instead of per seat. I'll send you the pricing tonight so you can run the numbers."),
        ]),
    ]),
    (2, "17:40", "End of day one: what worked at the booth", [
        "Fourteen badges scanned, five of them worth a follow-up.",
        "The cold-chain demo replaces the parcel one tomorrow, with the fuel saving on the first screen.",
    ], [
        (None, [
            ("Nadia", "Fourteen scans today. I'd call five of them real."),
            (ME, "That's about what I counted. The parcel demo isn't landing, though. Everyone who stopped ships food."),
            ("Nadia", "I can swap it for the cold-chain dataset tonight. It takes twenty minutes."),
            (ME, "Do that. And put the fuel saving on the first screen, it's the number they all ask about."),
        ]),
    ]),
    (1, "08:30", "Breakfast: the plan for day two", [
        "Sam meets Elena Ruiz of Castellan Foods after her nine o'clock panel, and looks for Tobias of Nordvik at eleven.",
        "Hiro from Tracewell asked for lunch about connecting their trackers.",
        "Anyone with under thirty vans sees the starter plan first.",
    ], [
        ("Who to find", [
            (ME, "Elena Ruiz from Castellan Foods is on the nine o'clock panel. I've got coffee with her straight after."),
            ("Nadia", "And Nordvik?"),
            (ME, "Tobias is in the cold-chain session at eleven. I'll wait for him in the hallway."),
            ("Nadia", "Hiro from Tracewell asked for lunch. He wants to talk about plugging their trackers into our planner."),
            (ME, "Good, book it for one. That's a partnership rather than a sale, but it could bring us more leads than the booth does."),
        ]),
        ("The demo", [
            ("Nadia", "The cold-chain dataset is loaded, and the fuel saving is on the first screen like you asked."),
            (ME, "Perfect. If anyone with under thirty vans stops by, show them the starter plan first."),
            ("Nadia", "Will do. I'll message you if somebody wants pricing."),
        ]),
    ]),
    (1, "10:05", "Coffee with Elena Ruiz of Castellan Foods", [
        "Castellan runs 140 vans from three depots, and its fuel bill is up 18% on last year.",
        "Elena wants a six-week pilot at one depot, and her IT team needs a security questionnaire.",
        "Sam will send the pilot proposal and the questionnaire by Friday; her board meets on the 19th.",
    ], [
        (None, [
            (ME, "Elena, thanks for making time. On the panel you said fuel is the number that keeps you up at night."),
            ("Elena", "It is. We run a hundred and forty vans out of three depots, and fuel is up eighteen percent on last year."),
            (ME, "How are the routes planned now?"),
            ("Elena", "Each depot manager does it by hand the night before. They're good, but nobody can plan again when a van breaks down."),
            (ME, "That's exactly where we help. What would you need to see before trying it?"),
            ("Elena", "A pilot at one depot, six weeks, with real numbers at the end. And our IT team won't look at anything without a security questionnaire."),
            (ME, "I'll send you a pilot proposal for the northern depot and the completed security questionnaire by Friday."),
            ("Elena", "Friday works. The board meets on the nineteenth, and I'd like to bring them a decision."),
        ]),
    ]),
    (1, "11:40", "In the hallway with Tobias from Nordvik Cold Chain", [
        "Nordvik's planner cannot mix chilled and frozen drops on one van, so two vans cover the same streets.",
        "Their current contract runs until March, and procurement will want three quotes.",
        "Nadia will show Tobias temperature zones with Nordvik's own data next Wednesday.",
    ], [
        (None, [
            (ME, "Tobias, good session. You said your planner can't mix chilled and frozen on one van."),
            ("Tobias", "It can't, so we send two vans down the same street. It's absurd."),
            (ME, "We handle that with temperature zones. Are you tied in with your current supplier?"),
            ("Tobias", "Until March. I'd need a reason to switch before then, and procurement will want three quotes."),
            (ME, "Then let's give you the reason. I'll introduce you to Nadia, our engineer, and she can show it with your own drop data."),
            ("Tobias", "Next Wednesday suits me. Send an invite and I'll bring our transport manager."),
        ]),
    ]),
    (1, "13:00", "Lunch with Hiro Tanaka: connecting Tracewell's trackers", [
        "Tracewell has trackers in about 9,000 vehicles and no route planning of its own.",
        "Hiro suggests sending customers each other's way, starting with a joint webinar in the new year.",
        "Sam will send the API documentation this week and draft a referral agreement.",
    ], [
        ("What Tracewell wants", [
            ("Hiro", "We have trackers in about nine thousand vehicles, and customers keep asking us for route planning. We don't want to build it."),
            (ME, "And we keep being asked for live vehicle positions. So each of us has the half the other is missing."),
            ("Hiro", "Exactly. If your planner can read our positions, I can put you in front of our customers."),
        ]),
        ("Next steps", [
            (ME, "I'll send you our API documentation this week so your team can judge how much work it is."),
            ("Hiro", "Good. I'd start with a joint webinar in the new year and see who turns up."),
            (ME, "Agreed. I'll draft a simple referral agreement, nothing exclusive, and we can argue about the percentages later."),
        ]),
    ]),
    (1, "15:30", "Booth demo for Golden Crust Bakeries", [
        "Golden Crust runs 22 vans that must finish their deliveries by half past six in the morning.",
        "With that cutoff set, the demo still saved about forty minutes a morning.",
        "A pricing call for the starter plan is set for Tuesday at ten.",
    ], [
        (None, [
            ("Amara", "We're twenty-two vans, and every café wants its bread before half past six. Can it plan around that?"),
            (ME, "Yes, delivery windows are the first thing you set. Nadia, can you put in a six-thirty cutoff?"),
            ("Nadia", "There. It moved four stops to a different van and still saves about forty minutes a morning."),
            ("Amara", "That's the part I needed to see. What does it cost for a fleet our size?"),
            (ME, "Under twenty-five vehicles is the starter plan. Let's do a call on Tuesday at ten and I'll walk you through the pricing."),
            ("Amara", "Tuesday at ten is fine. Send it to my work address, it's on the badge."),
        ]),
    ]),
    (1, "19:10", "Dinner: ranking the leads", [
        "Castellan Foods comes first: the pilot proposal goes out before anything else.",
        "Nordvik is a March decision, and Golden Crust is small but could sign this month.",
        "Sam writes all the follow-ups before the flight home.",
    ], [
        (None, [
            ("Nadia", "So who's first? We scanned thirty-one badges and I can't chase them all."),
            (ME, "Castellan. A hundred and forty vans and a board date. The pilot proposal goes out before anything else."),
            ("Nadia", "Nordvik felt keen, but March is a long way off."),
            (ME, "Keep them warm with the demo on Wednesday. Golden Crust is small, but she could sign this month."),
            ("Nadia", "And Tracewell?"),
            (ME, "That's the long game. I'll write all the follow-ups tomorrow morning, before the flight."),
        ]),
    ]),
    (0, "08:35", "Follow-ups before the flight", [
        "Elena replied overnight: she wants the pilot proposal to cover the eastern depot as well.",
        "Nadia finishes the security questionnaire by eleven, and Sam sends both from the gate.",
    ], [
        (None, [
            ("Nadia", "Elena emailed overnight. She wants the pilot proposal to cover the eastern depot as well as the northern one."),
            (ME, "Two depots is a better test anyway. Can you finish the security questionnaire this morning?"),
            ("Nadia", "It's half done. You'll have it by eleven."),
            (ME, "Then I'll send both from the gate. After that it's the API documentation for Hiro and the invite for Tobias."),
        ]),
    ]),
]

# The conversation the promo video opens, searches for and asks about.
FEATURED = "Coffee with Elena Ruiz of Castellan Foods"

# (title of the conversation, words the line contains, reminder text, status)
REMINDERS = [
    ("Booth chat", "send you the pricing tonight", "Send Grace the starter-plan pricing", "accepted"),
    ("Setting up the booth", "catch them after their sessions", "Find Castellan Foods and Nordvik after their sessions", "done"),
    ("Coffee with Elena", "by Friday", "Send Elena the pilot proposal and the security questionnaire by Friday", "suggested"),
    ("In the hallway", "introduce you to Nadia", "Invite Tobias and Nadia to a demo next Wednesday", "suggested"),
    ("Lunch with Hiro", "API documentation this week", "Send Hiro the API documentation", "suggested"),
    ("Booth demo", "Tuesday at ten and", "Set up Tuesday's ten o'clock pricing call with Amara", "accepted"),
]

RECAP = (
    "Day two of the Freight Futures Summit: a pilot in sight at Castellan Foods, and three more leads",
    [
        "Elena Ruiz wants a six-week pilot at one of Castellan's three depots; the proposal and the security questionnaire are due Friday, ahead of her board on the 19th.",
        "Nordvik Cold Chain is tied in until March; Tobias gets a temperature-zone demo from Nadia next Wednesday.",
        "Tracewell wants its trackers connected to the planner and to refer customers both ways, starting with a joint webinar.",
        "Golden Crust Bakeries, with 22 vans, has a pricing call on Tuesday at ten.",
    ],
)

QUESTION = "What does Elena need before a pilot, and when does she decide?"
ANSWER = (
    "Elena asked for two things before Castellan Foods tries it {needs}:\n\n"
    "- **a six-week pilot at one depot**, with real numbers at the end\n"
    "- a completed **security questionnaire** for her IT team\n\n"
    "You said you would send both by **Friday** {friday}. She wants to bring a decision to her board, "
    "which meets on the **19th** {board}.\n\n"
    "Since then she has asked for the proposal to cover the eastern depot too {extra}."
)
CITES = {"needs": "with real numbers at the end", "friday": "by Friday",
         "board": "board meets on the nineteenth", "extra": "eastern depot as well"}


def build(data_dir: Path, today: date | None = None) -> dict:
    """Fill an empty data folder with the made-up conversations. Returns what was written."""
    today = today or date.today()
    store = Store(data_dir)
    try:
        if store.db.execute("SELECT 1 FROM utterances LIMIT 1").fetchone():
            raise ValueError(f"{data_dir} already has conversations in it; choose an empty folder")
        db = store.db
        speakers: dict[str, int] = {}
        line_ids: dict[str, int] = {}      # line text -> id, for reminders and citations
        talk_ids: dict[str, tuple[int, int]] = {}
        for days_ago, clock, title, summary, sections in TALKS:
            hour, minute = map(int, clock.split(":"))
            at = datetime.combine(today - timedelta(days=days_ago), time(hour, minute))
            start_ms = cursor = int(at.timestamp() * 1000)
            headings = []
            for heading, lines in sections:
                if heading:
                    headings.append((cursor, heading))
                for who, text in lines:
                    if who not in speakers:
                        speakers[who] = db.execute(
                            "INSERT INTO speakers (name, voice_sum, lines) VALUES (?, ?, 0)", (who, b"")).lastrowid
                    length = 1200 + 330 * len(text.split())   # about three words a second
                    line_ids[text] = db.execute(
                        "INSERT INTO utterances (segment, start_ms, end_ms, text, speaker_id, source) "
                        "VALUES ('', ?, ?, ?, ?, 'demo')",
                        (cursor, cursor + length, text, speakers[who])).lastrowid
                    db.execute("UPDATE speakers SET lines = lines + 1 WHERE id = ?", (speakers[who],))
                    cursor += length + 900
                cursor += 45_000  # a pause between subjects
            cid = db.execute(
                "INSERT INTO conversations (start_ms, end_ms, status, title, summary, engine, source) "
                "VALUES (?, ?, 'done', ?, ?, 'demo', 'demo')", (start_ms, cursor, title, json.dumps(summary))).lastrowid
            talk_ids[title] = (cid, start_ms)
            db.executemany(
                "INSERT INTO sections (conversation_id, start_ms, level, title) VALUES (?, ?, 2, ?)",
                [(cid, when, heading) for when, heading in headings])

        def find(words: str) -> int:
            return next(uid for text, uid in line_ids.items() if words in text)

        for talk, words, text, status in REMINDERS:
            cid, start_ms = next(v for title, v in talk_ids.items() if title.startswith(talk))
            db.execute(
                "INSERT INTO reminders (conversation_id, text, status, created_ms, utterance_id) VALUES (?, ?, ?, ?, ?)",
                (cid, text, status, start_ms, find(words)))

        yesterday = (today - timedelta(days=1)).isoformat()
        db.execute(
            "INSERT INTO day_recaps (day, headline, points, engine, signature, made_ms) VALUES (?, ?, ?, 'demo', ?, ?)",
            (yesterday, RECAP[0], json.dumps(RECAP[1]), store.day_material(yesterday)[1],
             int(datetime.now().timestamp() * 1000)))
        db.commit()

        from .ask import Lookup

        answer = ANSWER.format(**{key: f"[L{find(words)}]" for key, words in CITES.items()})
        lookup = Lookup(data_dir)
        try:
            store.save_exchange(None, QUESTION, answer, lookup.cited(answer))
        finally:
            lookup.close()
        return {"conversations": len(TALKS), "lines": len(line_ids), "days": 3, "reminders": len(REMINDERS)}
    finally:
        store.close()


def present(data_dir: Path) -> bool:
    """True if the folder holds the made-up conversations."""
    store = Store(data_dir)
    try:
        return store.db.execute("SELECT 1 FROM conversations WHERE engine = 'demo' LIMIT 1").fetchone() is not None
    finally:
        store.close()


def remove(data_dir: Path) -> int:
    """Take the made-up conversations out again, leaving anything real. Returns how many went."""
    store = Store(data_dir)
    try:
        db = store.db
        ours = "SELECT id FROM conversations WHERE engine = 'demo'"
        (count,) = db.execute(f"SELECT COUNT(*) FROM ({ours})").fetchone()
        db.execute(f"DELETE FROM reminders WHERE conversation_id IN ({ours})")
        db.execute(f"DELETE FROM sections WHERE conversation_id IN ({ours})")
        db.execute("DELETE FROM conversations WHERE engine = 'demo'")
        db.execute("DELETE FROM utterances WHERE source = 'demo'")
        db.execute("DELETE FROM day_recaps WHERE engine = 'demo'")
        db.execute("DELETE FROM speakers WHERE voice_sum = ? AND id NOT IN "
                   "(SELECT speaker_id FROM utterances WHERE speaker_id IS NOT NULL)", (b"",))
        chats = [cid for (cid,) in db.execute(
            "SELECT chat_id FROM chat_messages WHERE role = 'user' AND content = ?", (QUESTION,))]
        for cid in chats:
            db.execute("DELETE FROM chat_messages WHERE chat_id = ?", (cid,))
            db.execute("DELETE FROM chats WHERE id = ?", (cid,))
        db.commit()
        return count
    finally:
        store.close()
