"""Serve the Lifelog for the promo video: made-up conversations and a pretend pendant.

Run by make_promo.mjs. Nothing here reaches a real pendant, a hosted model or
anyone's own data folder: Bluetooth, USB, the speech model, summaries and Ask
are all replaced with stand-ins, and the conversations are the ones
`limitful demo` writes.

    python pretend_server.py <empty data folder> <port>
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from limitful import ask, autostart, client, demo, digest, speech_model, transcribe, usb, watch
from limitful.store import Store
from limitful.web import make_server

DATA_DIR = Path(sys.argv[1]).resolve()
PORT = int(sys.argv[2])
if "Limitful" in DATA_DIR.parts and DATA_DIR.parent == Path.home():
    sys.exit("refusing to run on a real data folder")

state = {"paired": False, "model_ready": False, "download_began": None}
MODEL_BYTES = speech_model.KNOWN_BYTES["large-v3-turbo"]
DOWNLOAD_SECONDS = 3.2


# --- the pendant: unpaired at first, pairs after a few seconds, then answers ---------

async def read_state(timeout: float = 8.0) -> dict:
    await asyncio.sleep(1.2)
    if not state["paired"]:
        raise client.PendantError(client._NOT_PAIRED)
    return {"battery": 81, "pages": 0, "free_pages": 94820, "total_pages": 95232,
            "minutes_waiting": 0.0, "hours_free": 38.2}


async def pair(timeout: float = 180, log=print) -> dict:
    await asyncio.sleep(2.6)
    state["paired"] = True
    return {"battery": 81}


def read_usb() -> dict:
    return {"firmware": "1.1.20", "brightness": 80, "millivolts": 4012, "celsius": 29, "battery": 81}


# --- the first sync: a pretend model download, then the made-up conversations arrive ---

def make_transcriber(engine: str = "local", *args, **kwargs):
    state["download_began"] = time.time()
    time.sleep(DOWNLOAD_SECONDS)
    state["model_ready"] = True
    return object()


def downloaded_bytes(model: str | None = None) -> int:
    began = state["download_began"]
    return int(min(1.0, (time.time() - began) / DOWNLOAD_SECONDS) * MODEL_BYTES) if began else 0


def add_stand_in_audio() -> None:
    """Give one conversation a silent recording, so its lines can be 'played' on screen."""
    store = Store(DATA_DIR)
    try:
        cid, start, end = store.db.execute(
            "SELECT id, start_ms, end_ms FROM conversations WHERE title LIKE 'Supplier call%'").fetchone()
        (last,) = store.db.execute(
            "SELECT MAX(end_ms) FROM utterances WHERE start_ms BETWEEN ? AND ?", (start, end)).fetchone()
        began = start - 500
        seconds = (last - began) / 1000 + 1.0
        day = datetime.fromtimestamp(start / 1000)
        path = f"audio/{day:%Y-%m-%d}/{day:%H-%M-%S}_stand-in.ogg"
        (DATA_DIR / path).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
             "-t", f"{seconds:.2f}", "-c:a", "libopus", "-b:a", "16k", str(DATA_DIR / path)], check=True)
        store.db.execute(
            "INSERT INTO segments (path, start_ms, duration_ms, first_page, last_page, retimed) VALUES (?, ?, ?, 0, 0, 1)",
            (path, began, int(seconds * 1000)))
        store.db.execute("UPDATE utterances SET segment = ? WHERE start_ms BETWEEN ? AND ?", (path, start, end))
        # The demo folder comes with this question already asked; the video asks it live.
        store.db.execute("DELETE FROM chat_messages")
        store.db.execute("DELETE FROM chats")
        store.db.commit()
    finally:
        store.close()


async def run_cycle(store, ack, get_transcriber, get_embedder, summarizer, on_stage=lambda stage: None, **kwargs):
    on_stage("Downloading from the pendant")
    await asyncio.sleep(1.0)
    on_stage("Transcribing")
    await asyncio.to_thread(get_transcriber)
    made = await asyncio.to_thread(demo.build, DATA_DIR)
    await asyncio.to_thread(add_stand_in_audio)
    return watch.CycleResult(found=True, pages_new=412, audio_files=made["conversations"], lines=made["lines"])


# --- Ask: the demo's own answer, written out at reading speed, with nothing sent anywhere ---

def answer(data_dir, history, api_key=None, model=None, on_step=lambda step: None, on_text=lambda text: None) -> dict:
    lookup = ask.Lookup(data_dir)
    try:
        def find(words: str) -> int:
            return lookup.db.execute("SELECT id FROM utterances WHERE text LIKE ?", (f"%{words}%",)).fetchone()[0]

        text = demo.ANSWER.format(**{key: f"[L{find(words)}]" for key, words in demo.CITES.items()})
        on_step("Searching for “wheels”")
        time.sleep(0.7)
        on_step("Reading “Supplier call about the late wheel order”")
        time.sleep(0.7)
        for piece in re.findall(r"\S+\s*", text):
            on_text(piece)
            time.sleep(0.03)
        return {"answer": text, "lines": lookup.cited(text)}
    finally:
        lookup.close()


def no_login_item(*args, **kwargs):
    raise autostart.AutostartError("the pretend server never installs a login item")


# Start at login is shown as available and off; the real login items are neither read nor changed.
autostart.status = lambda *args, **kwargs: {"supported": True, "enabled": False, "running": False}
autostart.enable = autostart.disable = no_login_item
client.read_state, client.pair = read_state, pair
usb.read = read_usb
watch.run_cycle = run_cycle
transcribe.make_transcriber = make_transcriber
speech_model.ready = lambda model=None: state["model_ready"]
speech_model.downloaded_bytes = downloaded_bytes
digest.make_summarizer = lambda *args, **kwargs: None
demo.present = lambda data_dir: False  # the video says the conversations are made up on its own cards
ask.answer = answer

server = make_server(DATA_DIR, PORT)
print(f"pretend Lifelog on http://127.0.0.1:{PORT}", flush=True)
server.serve_forever()
