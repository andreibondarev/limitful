"""A data folder of made-up conversations, for trying the Lifelog without a pendant.

Everything here is invented: the people, the bike shop and what they say. The
lines have no audio behind them, so they can be read, searched and asked about
but not played.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .store import Store

ME = "Sam"

# (days before today, start time, title, summary points, [(heading or None, [(speaker, line), ...])])
TALKS = [
    (2, "09:10", "Quote for the school bike fleet", [
        "The school wants twelve bikes serviced before term starts on the 2nd.",
        "Sam will quote per bike, with new tyres priced as an extra.",
    ], [
        (None, [
            ("Priya", "The school rang again about their fleet. Twelve bikes, and they want them back before term starts on the second."),
            (ME, "Twelve is fine if they drop them off this week. I'll quote per bike so they can leave out the ones that are past saving."),
            ("Priya", "Half of them need tyres. Do we fold that into the price?"),
            (ME, "No, keep tyres as an extra line. I'll send the quote to the bursar by Friday."),
        ]),
    ]),
    (2, "16:30", "Choosing a new card reader", [
        "The current card reader drops its connection most afternoons.",
        "They will try the reader that works offline for a month before deciding.",
    ], [
        (None, [
            ("Priya", "The card reader dropped out three times this afternoon. Somebody walked out without paying because it took so long."),
            (ME, "That's the third week running. What was the one that keeps taking payments when the wifi goes?"),
            ("Priya", "It stores them and sends them later. Costs a bit more each month."),
            (ME, "Let's take the month's trial and see whether it actually behaves before we commit."),
        ]),
    ]),
    (1, "08:40", "Morning plan: deliveries and the Saturday workshop", [
        "The wheel order is a week late, which holds up three customer repairs.",
        "Saturday's puncture workshop has nine people signed up; the limit stays at ten.",
        "Priya opens on Saturday so Sam can set up the workshop.",
    ], [
        ("Deliveries", [
            (ME, "Morning. Did the wheels turn up yesterday after I left?"),
            ("Priya", "No, nothing. That's a week late now, and three repairs are waiting on them."),
            (ME, "I'll call Marco at ten and find out where they are. If it's another week we should tell those three customers today."),
            ("Priya", "The Hendersons' one is the urgent one. They leave on Friday."),
        ]),
        ("Saturday workshop", [
            (ME, "How many have we got for the puncture workshop on Saturday?"),
            ("Priya", "Nine signed up. Someone asked if they could bring a friend."),
            (ME, "Ten is the limit, we only have ten stands. So one friend, and then it's full."),
            ("Priya", "I can open up on Saturday if you want to set the stands out first."),
            (ME, "Yes please. I'll bring the spare tubes from the lock-up on Friday night."),
        ]),
    ]),
    (1, "10:05", "Supplier call about the late wheel order", [
        "The wheels were held at the port and are now due on Thursday.",
        "Marco will send a tracking number today and take 10% off the invoice.",
        "Sam will lend the Hendersons a wheel so they can leave on Friday.",
    ], [
        (None, [
            (ME, "Marco, it's Sam from the shop. I'm chasing the wheel order, it was due last Tuesday."),
            ("Marco", "I know, I'm sorry. The container sat at the port for five days. They cleared it yesterday."),
            (ME, "So when do I actually have them in my hands?"),
            ("Marco", "Thursday. I'll send you the tracking number this afternoon so you can see it moving."),
            (ME, "I've got a customer leaving on Friday who needs one of those wheels. Thursday is cutting it close."),
            ("Marco", "Understood. Take ten percent off the invoice for the trouble, I'll put it in writing."),
            (ME, "Thank you. If it slips past Thursday I'll lend them a wheel off the hire bike."),
        ]),
    ]),
    (1, "12:35", "Lunch: planning the Lisbon trip", [
        "Flights are cheapest leaving on the 14th and coming back on the 21st.",
        "Dana will book the flights tonight; Sam will find someone to cover the shop that week.",
        "They want two days of riding along the coast, so the bikes get hired there.",
    ], [
        ("Dates and flights", [
            ("Dana", "I looked at flights. Leaving on the fourteenth and back on the twenty-first is about half the price of the week after."),
            (ME, "The fourteenth works if I can get cover for the shop. Priya can't do the whole week on her own."),
            ("Dana", "Ask your cousin? He did it in the spring."),
            (ME, "I'll ask him tonight. You book the flights and I'll sort the cover."),
        ]),
        ("What to do there", [
            ("Dana", "I'd like two days riding the coast road, the rest just wandering about."),
            (ME, "Then we hire bikes there. I'm not boxing ours up for two days of riding."),
            ("Dana", "Fine by me. There's a place by the river that rents proper road bikes."),
        ]),
    ]),
    (1, "15:10", "Fitting a customer for a touring bike", [
        "The customer is planning a three-week tour and carries about 20 kg.",
        "A steel frame one size up with a longer stem suits them best.",
        "They will come back on Tuesday to test ride it loaded.",
    ], [
        (None, [
            ("Customer", "I'm doing three weeks through France in the summer, camping, so I'm carrying everything."),
            (ME, "How much weight, roughly, once the tent and the cooking kit are on?"),
            ("Customer", "About twenty kilos. I had back pain on my last bike after a long day."),
            (ME, "Then I'd put you on the steel frame, one size up, with a longer stem so you're not hunched over."),
            ("Customer", "Can I try it with bags on before I decide?"),
            (ME, "Of course. Come back Tuesday and I'll have it loaded up with panniers for you to ride round the block."),
        ]),
    ]),
    (1, "18:50", "Dinner: the weekend and the school fundraiser", [
        "The school fundraiser is on Sunday afternoon and needs a raffle prize.",
        "Sam will donate a bike service voucher.",
        "Saturday evening is kept free for Dana's parents.",
    ], [
        (None, [
            ("Dana", "The school asked if the shop would give something for the raffle on Sunday."),
            (ME, "I can do a voucher for a full service. That's easier than finding a prize."),
            ("Dana", "Perfect. And my parents are coming on Saturday evening, so don't plan anything after the workshop."),
            (ME, "Workshop finishes at one. I'm all yours after that."),
        ]),
    ]),
    (0, "08:35", "Tracking number and today's repairs", [
        "The tracking number arrived overnight; the wheels are out for delivery tomorrow.",
        "The Hendersons have been told their bike will be ready on Thursday evening.",
    ], [
        (None, [
            ("Priya", "Marco's tracking number came through last night. It says out for delivery tomorrow."),
            (ME, "Good. Ring the Hendersons and tell them Thursday evening, and that I've a spare wheel if it slips."),
            ("Priya", "Already did. They were relieved."),
            (ME, "Then today is the two brake jobs and the fleet quote. I still owe the bursar that."),
        ]),
    ]),
]

# (title of the conversation, words the line contains, reminder text, status)
REMINDERS = [
    ("Quote for the school bike fleet", "send the quote", "Send the fleet quote to the bursar by Friday", "accepted"),
    ("Morning plan", "call Marco at ten", "Call Marco at ten about the wheel order", "done"),
    ("Morning plan", "spare tubes", "Bring the spare tubes from the lock-up on Friday night", "suggested"),
    ("Lunch", "ask him tonight", "Ask your cousin to cover the shop from the 14th to the 21st", "suggested"),
    ("Fitting a customer", "Come back Tuesday", "Load the steel tourer with panniers for Tuesday's test ride", "suggested"),
    ("Dinner", "voucher for a full service", "Make a service voucher for Sunday's school raffle", "accepted"),
]

RECAP = (
    "Chasing the late wheel order, a touring bike fitting, and settling dates for Lisbon",
    [
        "The wheels were stuck at the port and are now due Thursday; Marco is sending tracking and taking 10% off the invoice.",
        "Lisbon is the 14th to the 21st: Dana books flights tonight, and Sam needs cover for the shop that week.",
        "A customer planning a three-week tour suits the steel frame one size up, and returns Tuesday to ride it loaded.",
        "Saturday's puncture workshop is nearly full at nine of ten, and the shop is giving a service voucher to Sunday's raffle.",
    ],
)

QUESTION = "When are the wheels arriving, and what did Marco offer?"
ANSWER = (
    "The wheels are due on **Thursday**. Marco said the container sat at the port for five days and "
    "was cleared the day before the call {port}, and gave Thursday as the delivery day {thursday}.\n\n"
    "He offered two things:\n\n"
    "- a tracking number, sent that afternoon {thursday}\n"
    "- **10% off the invoice**, which he said he would put in writing {discount}\n\n"
    "The tracking number did arrive overnight and shows the wheels out for delivery {tracking}."
)
CITES = {"port": "sat at the port", "thursday": "send you the tracking number",
         "discount": "ten percent off", "tracking": "tracking number came through"}


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
