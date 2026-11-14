"""Local web app: browse each day's transcript and play the audio behind any line.

Serves on 127.0.0.1 only. The data is private, so requests are also checked
for a local Host header, which stops other websites reaching it through DNS
tricks in the browser.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import zipfile
from collections import Counter
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import asyncio

from . import ask as ask_mod
from . import client as client_mod
from . import config
from . import digest as digest_mod
from . import hosted as hosted_mod
from . import upkeep

_INDEX = Path(__file__).parent / "web" / "index.html"
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
_SEARCH_LIMIT = 200
_MEANING_LIMIT = 8  # moments offered as "close in meaning" under the exact matches
_MAX_UPLOAD = 50 * 1024**3
# Imported lines can sit a second or two after their audio; start playback early.
_IMPORT_LEAD_MS = 1500


def _day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def _utterance(row) -> dict:
    uid, start_ms, end_ms, text, segment, segment_start, speaker_id, speaker, label, retimed, imported = row
    if speaker_id:
        who = {"id": speaker_id, "name": speaker, "line": uid}
    elif label:  # a numbered speaker: the number only holds within its conversation
        who = {"id": None, "name": f"Speaker {label}", "line": uid}
    else:
        who = None
    has_audio = bool(segment) and segment_start is not None
    return {
        "speaker": who,
        "id": uid,
        "start": start_ms,
        "end": end_ms,
        "text": text,
        "audio": "/" + segment if has_audio else None,
        # Imported lines that have not been re-timed run late, so start those early.
        "offset": max(0, start_ms - segment_start - (_IMPORT_LEAD_MS if imported and retimed is None else 0))
        if has_audio else 0,
    }


_SELECT = (
    "SELECT u.id, u.start_ms, u.end_ms, u.text, u.segment, s.start_ms, u.speaker_id, p.name, "
    "u.source_speaker, u.orig_start_ms, u.source IS NOT NULL "
    "FROM utterances u LEFT JOIN segments s ON s.path = u.segment "
    "LEFT JOIN speakers p ON p.id = u.speaker_id "
)


class Library:
    """Read-only queries over the data folder."""

    def __init__(self, data_dir: Path, link_speakers: bool = False) -> None:
        self.data_dir = Path(data_dir).resolve()
        self._link_speakers = link_speakers
        self._lock = threading.Lock()
        # What the server is busy with, shown in the Lifelog.
        self.job = {"running": False, "what": "", "done": 0, "total": 0, "error": None, "note": None}
        # One Bluetooth conversation with the pendant at a time.
        self._radio = threading.Lock()
        self._pendant: dict = {"checked": None, "error": None}

    def import_export(self, stream, length: int) -> dict:
        """Save an uploaded export zip, import it, then start linking speakers."""
        from .importer import import_limitless

        with self._lock:
            if self.job["running"]:
                raise RuntimeError("an import is already running")
            self.job.update(running=True, what="Importing the export", done=0, total=0, error=None, note=None)
        upload = self.data_dir / "imports" / f"upload-{int(time.time())}.zip"
        try:
            upload.parent.mkdir(parents=True, exist_ok=True)
            with open(upload, "wb") as out:
                left = length
                while left > 0:
                    chunk = stream.read(min(left, 1 << 20))
                    if not chunk:
                        raise ValueError("the upload was cut short")
                    out.write(chunk)
                    left -= len(chunk)
            result = self._with_store(
                lambda store: import_limitless(store, upload, log=lambda message: None))
        except Exception:
            self.job.update(running=False, what="")
            raise
        finally:
            upload.unlink(missing_ok=True)
        if self._link_speakers and result.lines:
            threading.Thread(target=self._link_job, daemon=True).start()
        else:
            self.job.update(running=False, what="")
        return {
            "conversations": result.conversations, "lines": result.lines,
            "recordings": result.audio_files, "hours": round(result.audio_hours, 1),
            "reminders": result.reminders, "skipped": result.skipped_existing,
        }

    # --- the pendant -----------------------------------------------------------------

    def pendant(self) -> dict:
        """What was last learned about the pendant, without touching the radio."""
        return dict(self._pendant, brightness=config.load().get("led_brightness"),
                    paused_since=self._with_store(lambda store: store.paused_since()))

    def set_paused(self, paused: bool) -> dict:
        self._with_store(lambda store: store.pause() if paused else store.resume())
        return self.pendant()

    def unpair_pendant(self) -> dict:
        def unpair():
            try:
                asyncio.run(client_mod.unpair())
            except (client_mod.PendantError, client_mod.BleakError, asyncio.TimeoutError, OSError) as err:
                raise ValueError(f"Could not unpair: {err}") from None
            self._pendant = {"checked": None, "error": None}
            return self.pendant()

        return self._with_radio(unpair)

    def start_pairing(self) -> None:
        """Wait, in the background, for the pendant to be put in pairing mode."""
        with self._lock:
            if self.job["running"]:
                raise RuntimeError("something is already running; wait for it to finish")
            self.job.update(running=True, what="Waiting for the pendant in pairing mode",
                            done=0, total=0, error=None, note=None)
        threading.Thread(target=self._pair_job, daemon=True).start()

    def _pair_job(self) -> None:
        try:
            if not self._radio.acquire(timeout=20):
                raise RuntimeError("the pendant is busy")
            try:
                state = asyncio.run(client_mod.pair(timeout=180, log=lambda message: None))
            finally:
                self._radio.release()
            if state is None:
                raise RuntimeError("the pendant never accepted this computer. Check it showed "
                                   "a blue light, and that you accepted the connection request")
            self.job["note"] = "Paired. The pendant accepted this computer."
        except Exception as err:  # shown in the page
            self.job["error"] = f"Pairing stopped: {err}"
        finally:
            self.job.update(running=False, what="")

    def _with_radio(self, action):
        if not self._radio.acquire(blocking=False):
            raise RuntimeError("already talking to the pendant; try again in a moment")
        try:
            return action()
        finally:
            self._radio.release()

    def check_pendant(self) -> dict:
        def check():
            try:
                state = asyncio.run(client_mod.read_state())
            except (client_mod.PendantError, client_mod.BleakError, asyncio.TimeoutError, OSError) as err:
                self._pendant = {"checked": int(time.time() * 1000), "error": str(err) or type(err).__name__}
            else:
                self._pendant = dict(state, checked=int(time.time() * 1000), error=None)
            return self.pendant()

        return self._with_radio(check)

    def set_brightness(self, percent) -> dict:
        if not isinstance(percent, int) or isinstance(percent, bool) or not 0 <= percent <= 100:
            raise ValueError("brightness is a whole number from 0 to 100")

        def apply():
            try:
                asyncio.run(client_mod.set_brightness(percent))
            except (client_mod.PendantError, client_mod.BleakError, asyncio.TimeoutError, OSError) as err:
                raise ValueError(f"Could not reach the pendant: {err}") from None
            config.update(led_brightness=percent)
            return self.pendant()

        return self._with_radio(apply)

    def start_sync(self) -> None:
        """Pull new audio off the pendant, then transcribe and summarise it, in the background."""
        with self._lock:
            if self.job["running"]:
                raise RuntimeError("something is already running; wait for it to finish")
            self.job.update(running=True, what="Syncing the pendant", done=0, total=0, error=None, note=None)
        threading.Thread(target=self._sync_job, daemon=True).start()

    def _sync_job(self) -> None:
        from . import watch as watch_mod
        from .store import Store
        from .transcribe import make_transcriber

        try:
            if not self._radio.acquire(timeout=20):
                raise RuntimeError("the pendant is busy")
            try:
                provider = config.provider()
                summarizer = (digest_mod.make_summarizer(provider, None, config.api_key())
                              if provider else None)
                store = Store(self.data_dir)
                try:
                    result = asyncio.run(watch_mod.run_cycle(
                        store, ack=True,
                        get_transcriber=lambda: make_transcriber(config.transcriber()),
                        get_embedder=None, summarizer=summarizer,  # voice labels are opt-in: see README
                        on_stage=lambda stage: self.job.update(what=stage)))
                finally:
                    store.close()
            finally:
                self._radio.release()
            if not result.found:
                raise RuntimeError("the pendant is not in range, is switched off, "
                                   "or is connected to another device")
            if result.error:
                raise RuntimeError(result.error)
            self.job["note"] = (f"Synced {result.pages_new} new pages: {result.audio_files} recordings, "
                                f"{result.lines} lines of speech."
                                + (f" Deleted {result.pages_discarded} pages recorded while paused."
                                   if result.pages_discarded else ""))
        except Exception as err:  # shown in the page
            self.job["error"] = f"Sync stopped: {err}"
            self.job["note"] = None
        finally:
            self.job.update(running=False, what="")

    def settings(self) -> dict:
        """What the Settings page shows. The key itself never leaves the server."""
        key = config.api_key()
        return {
            "provider": config.load().get("provider") or None,
            "has_key": bool(key),
            "key_hint": f"ends in {key[-4:]}" if key and len(key) >= 12 else ("saved" if key else None),
            "claude_model": digest_mod.CLAUDE_MODEL,
            "ollama_model": digest_mod.OLLAMA_MODEL,
            "transcriber": config.load().get("transcriber") or "local",
            "has_deepgram_key": bool(config.deepgram_api_key()),
            "deepgram_key_hint": self._hint(config.deepgram_api_key()),
            "deepgram_model": hosted_mod.DEEPGRAM_MODEL,
        }

    @staticmethod
    def _hint(key: str | None) -> str | None:
        """Enough to recognise a saved key by, never the key itself."""
        if not key:
            return None
        return f"ends in {key[-4:]}" if len(key) >= 12 else "saved"

    def _save_transcription(self, body: dict) -> None:
        engine = body.get("transcriber", config.load().get("transcriber") or "local")
        key = body.get("deepgram_api_key")
        if key is not None and not isinstance(key, str):
            raise ValueError("the key must be text")
        if engine not in config.TRANSCRIBERS:
            raise ValueError("choose local transcription or Deepgram")
        candidate = key.strip() if key else (config.deepgram_api_key() if key is None else None)
        if engine == "deepgram":
            if not candidate:
                raise ValueError("Deepgram needs an API key. Nothing was saved.")
            # Check before saving, so a mistyped key is caught here and not at the next sync.
            try:
                hosted_mod.check_deepgram(candidate)
            except hosted_mod.HostedError as err:
                raise ValueError(f"{err}. Nothing was saved.") from None
        if key is None:
            config.update(transcriber=engine)
        else:
            config.update(transcriber=engine, deepgram_api_key=key)

    def save_settings(self, body: dict) -> dict:
        if "transcriber" in body or "deepgram_api_key" in body:
            self._save_transcription(body)
            if "provider" not in body and "api_key" not in body:
                return self.settings()
        provider = body.get("provider", config.load().get("provider"))
        if provider in ("", "none"):
            provider = None
        key = body.get("api_key")
        if key is not None and not isinstance(key, str):
            raise ValueError("the key must be text")
        if provider is not None and provider not in config.PROVIDERS:
            raise ValueError("choose Claude, Ollama or no summaries")
        if provider == "claude":
            # Check before saving, so a mistyped key is caught here and not hours later.
            candidate = key.strip() if key else (config.api_key() if key is None else None)
            try:
                digest_mod.check_claude(candidate or None)
            except digest_mod.DigestError as err:
                raise ValueError(f"{err}. Nothing was saved.") from None
        if key is None:
            config.update(provider=provider)
        else:
            config.update(provider=provider, api_key=key)
        return self.settings()

    def start_digest(self) -> None:
        """Summarise new conversations in the background."""
        provider = config.provider()
        if not provider:
            raise ValueError("choose what writes summaries first")
        with self._lock:
            if self.job["running"]:
                raise RuntimeError("something is already running; wait for it to finish")
            self.job.update(running=True, what="Summarising conversations", done=0, total=0, error=None, note=None)
        threading.Thread(target=self._digest_job, args=(provider,), daemon=True).start()

    def _digest_job(self, provider: str) -> None:
        from .store import Store

        try:
            summarizer = digest_mod.make_summarizer(provider, None, config.api_key())
            store = Store(self.data_dir)
            try:
                store.digest_pending(
                    summarizer, lambda done, total: self.job.update(done=done, total=total))
            finally:
                store.close()
        except Exception as err:  # shown in the page; whatever was summarised is kept
            self.job["error"] = f"Summaries stopped: {err}"
        finally:
            self.job.update(running=False, what="")

    def _link_job(self) -> None:
        """Recognise the voices in imported conversations. Slow, so it runs in the background."""
        from .speakers import TitanetEmbedder, load_audio
        from .store import Store

        self.job.update(running=True, what="Recognising speakers", done=0, total=0, error=None, note=None)
        try:
            store = Store(self.data_dir)
            try:
                store.link_imported_speakers(
                    TitanetEmbedder(), load_audio,
                    lambda done, total: self.job.update(done=done, total=total))
            finally:
                store.close()
        except Exception as err:  # report it in the page; the import itself is already saved
            self.job["error"] = f"Could not recognise speakers: {err}"
        finally:
            self.job.update(running=False, what="")

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(f"file:{self.data_dir / 'pendant.db'}?mode=ro", uri=True)

    def days(self) -> list[dict]:
        db = self._db()
        try:
            counts = Counter(_day_of(ms) for (ms,) in db.execute("SELECT start_ms FROM utterances"))
        except sqlite3.OperationalError:
            counts = Counter()  # no recordings yet
        finally:
            db.close()
        return [{"day": day, "lines": n} for day, n in sorted(counts.items())]

    def day(self, day: str) -> list[dict]:
        start = datetime.strptime(day, "%Y-%m-%d")
        lo = int(start.timestamp() * 1000)
        hi = int((start + timedelta(days=1)).timestamp() * 1000)
        db = self._db()
        try:
            rows = db.execute(
                _SELECT + "WHERE u.start_ms >= ? AND u.start_ms < ? ORDER BY u.start_ms, u.id",
                (lo, hi),
            ).fetchall()
        finally:
            db.close()
        return [_utterance(r) for r in rows]

    def search(self, query: str) -> list[dict]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        db = self._db()
        try:
            rows = db.execute(
                _SELECT + "WHERE u.text LIKE ? ESCAPE '\\' ORDER BY u.start_ms DESC LIMIT ?",
                (f"%{escaped}%", _SEARCH_LIMIT),
            ).fetchall()
        finally:
            db.close()
        return [dict(_utterance(r), day=_day_of(r[1])) for r in rows]

    def search_meaning(self, query: str) -> dict:
        """Lines close in meaning to `query`, best first, once the index has been built.

        Served apart from the exact-word search so those results never wait for,
        or change because of, this one; the page lists these underneath.
        """
        from . import search as search_mod

        index = search_mod.index_for(self.data_dir)
        if not index.exists():
            return {"ready": False, "lines": []}
        db = self._db()
        try:
            start_of = dict(db.execute("SELECT id, start_ms FROM utterances"))
            # No cut-off by score: measured on real transcripts, right answers (0.57 to
            # 0.79) and unrelated lines (median 0.68) score alike, so a floor would
            # hide as many good hits as bad. The page labels these as near, not exact.
            hits = search_mod.spread(index.search(search_mod.make_embedder(), query, limit=200),
                                     start_of, _MEANING_LIMIT, apart_ms=search_mod.NEIGHBOUR_GAP_MS)
            # A hit is a line that matched together with its neighbours, and on its own
            # it can be a bare "Yeah.", so each is shown as that moment: the same few lines.
            lines, seen = [], set()  # a line two moments share is listed with the closer one
            for moment, (uid, _score) in enumerate(hits):
                at = start_of[uid]
                reach = search_mod.NEIGHBOUR_GAP_MS
                before = db.execute(
                    _SELECT + "WHERE u.start_ms <= ? AND u.start_ms > ? AND u.id != ? "
                    "ORDER BY u.start_ms DESC, u.id DESC LIMIT ?", (at, at - reach, uid, search_mod.NEIGHBOURS)).fetchall()
                after = db.execute(
                    _SELECT + "WHERE u.start_ms >= ? AND u.start_ms < ? AND u.id != ? "
                    "ORDER BY u.start_ms, u.id LIMIT ?", (at, at + reach, uid, search_mod.NEIGHBOURS)).fetchall()
                here = db.execute(_SELECT + "WHERE u.id = ?", (uid,)).fetchall()
                for row in sorted([*before, *here, *after], key=lambda r: (r[1], r[0])):
                    if row[0] not in seen:
                        seen.add(row[0])
                        lines.append(dict(_utterance(row), day=_day_of(row[1]), moment=moment))
        finally:
            db.close()
        return {"ready": True, "lines": lines}

    def _with_store(self, action):
        from .store import Store

        store = Store(self.data_dir)
        try:
            return action(store)
        finally:
            store.close()

    def rename_speaker(self, speaker_id: int, name: str) -> int:
        return self._with_store(lambda store: store.rename_speaker(speaker_id, name))

    def chats(self) -> list[dict]:
        return self._with_store(lambda store: store.chats())

    def chat(self, chat_id: int) -> list[dict]:
        return self._with_store(lambda store: store.chat_messages(chat_id))

    def delete_chat(self, chat_id: int) -> None:
        self._with_store(lambda store: store.delete_chat(chat_id))

    def save_exchange(self, chat_id, question: str, answer: str, lines: dict) -> int:
        return self._with_store(lambda store: store.save_exchange(chat_id, question, answer, lines))

    def assign_line_speaker(self, utterance_id: int, name: str) -> int:
        return self._with_store(lambda store: store.assign_line_speaker(utterance_id, name))

    def conversations(self, day: str) -> list[dict]:
        start = datetime.strptime(day, "%Y-%m-%d")
        lo = int(start.timestamp() * 1000)
        hi = int((start + timedelta(days=1)).timestamp() * 1000)
        return self._with_store(lambda store: store.conversations(lo, hi))

    def reminders(self, include_done: bool = False) -> list[dict]:
        return self._with_store(lambda store: store.reminders(include_done))

    def set_reminder_status(self, reminder_id: int, status: str) -> None:
        self._with_store(lambda store: store.set_reminder_status(reminder_id, status))

    def audio_path(self, url_path: str) -> Path | None:
        """Resolve /audio/... to a file, refusing anything outside the audio folder."""
        root = self.data_dir / "audio"
        target = (self.data_dir / url_path.lstrip("/")).resolve()
        if root.resolve() not in target.parents or target.suffix != ".ogg" or not target.is_file():
            return None
        return target


def make_handler(library: Library):
    # Read once: a page newer than the running server would call addresses it lacks.
    index = _INDEX.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        server_version = "limitful"

        def log_message(self, format, *args) -> None:  # keep the terminal quiet
            pass

        def do_GET(self) -> None:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in _LOCAL_HOSTS:
                return self._text(HTTPStatus.FORBIDDEN, "This app only answers on localhost.")
            url = urlparse(self.path)
            path = unquote(url.path)
            try:
                if path == "/":
                    return self._send(HTTPStatus.OK, index, "text/html; charset=utf-8")
                if path == "/api/days":
                    return self._json(library.days())
                if path.startswith("/api/day/"):
                    day = path.removeprefix("/api/day/")
                    if not _DAY.match(day):
                        return self._text(HTTPStatus.BAD_REQUEST, "Day must be YYYY-MM-DD.")
                    return self._json(library.day(day))
                if path.startswith("/api/conversations/"):
                    day = path.removeprefix("/api/conversations/")
                    if not _DAY.match(day):
                        return self._text(HTTPStatus.BAD_REQUEST, "Day must be YYYY-MM-DD.")
                    return self._json(library.conversations(day))
                if path == "/api/reminders":
                    done = parse_qs(url.query).get("done", ["0"])[0] == "1"
                    return self._json(library.reminders(include_done=done))
                if path == "/api/status":
                    return self._json(library.job)
                if path == "/api/settings":
                    return self._json(library.settings())
                if path == "/api/pendant":
                    return self._json(library.pendant())
                if path == "/api/upkeep":
                    return self._json(upkeep.status(library))
                if path == "/api/chats":
                    return self._json(library.chats())
                found = re.match(r"^/api/chats/(\d+)$", path)
                if found:
                    return self._json(library.chat(int(found.group(1))))
                if path == "/api/search":
                    query = parse_qs(url.query).get("q", [""])[0].strip()
                    return self._json(library.search(query) if query else [])
                if path == "/api/search/meaning":
                    query = parse_qs(url.query).get("q", [""])[0].strip()
                    return self._json(library.search_meaning(query) if query else {"ready": True, "lines": []})
                if path.startswith("/audio/"):
                    return self._audio(library.audio_path(path))
            except (sqlite3.Error, ValueError) as err:
                return self._text(HTTPStatus.INTERNAL_SERVER_ERROR, f"Could not read the data: {err}")
            self._text(HTTPStatus.NOT_FOUND, "Not found.")

        def do_POST(self) -> None:
            """POST /api/speakers/<id> {"name": ...} or /api/reminders/<id> {"status": ...}."""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            if host not in _LOCAL_HOSTS:
                return self._text(HTTPStatus.FORBIDDEN, "This app only answers on localhost.")
            # JSON and zip content types cannot be sent by another website without
            # our permission, which this server never gives.
            kind = (self.headers.get("Content-Type") or "").split(";")[0].strip()
            if kind not in ("application/json", "application/zip"):
                return self._text(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Send JSON.")
            if (kind == "application/zip") != (urlparse(self.path).path == "/api/import"):
                return self._text(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Wrong content type for this address.")
            path = urlparse(self.path).path
            if path == "/api/import":
                return self._import()
            if path == "/api/ask":
                return self._ask()
            found = re.match(r"^/api/chats/(\d+)/delete$", path)
            if found:
                library.delete_chat(int(found.group(1)))
                return self._json({"deleted": int(found.group(1))})
            if path == "/api/pendant":
                try:
                    length = min(int(self.headers.get("Content-Length") or 0), 4096)
                    body = json.loads(self.rfile.read(length) or b"{}")
                    action = body.get("action") if isinstance(body, dict) else None
                    if action == "check":
                        return self._json(library.check_pendant())
                    if action == "brightness":
                        return self._json(library.set_brightness(body.get("value")))
                    if action == "sync":
                        library.start_sync()
                        return self._json({"started": True})
                    if action in ("pause", "resume"):
                        return self._json(library.set_paused(action == "pause"))
                    if action == "pair":
                        library.start_pairing()
                        return self._json({"started": True})
                    if action == "unpair":
                        return self._json(library.unpair_pendant())
                    raise ValueError("unknown action")
                except RuntimeError as err:
                    return self._text(HTTPStatus.CONFLICT, str(err))
                except ValueError as err:
                    return self._text(HTTPStatus.BAD_REQUEST, str(err))
            if path == "/api/upkeep":
                # Re-timing and index building: {"action": "retime" | "index" | "stop"}.
                try:
                    length = min(int(self.headers.get("Content-Length") or 0), 4096)
                    body = json.loads(self.rfile.read(length) or b"{}")
                    action = body.get("action") if isinstance(body, dict) else None
                    if action == "retime":
                        upkeep.start_retime(library)
                    elif action == "index":
                        upkeep.start_index(library)
                    elif action == "stop":
                        upkeep.stop(library)
                    else:
                        raise ValueError("unknown action")
                    return self._json({"ok": True})
                except RuntimeError as err:
                    return self._text(HTTPStatus.CONFLICT, str(err))
                except ValueError as err:
                    return self._text(HTTPStatus.BAD_REQUEST, str(err))
            if path in ("/api/settings", "/api/digest"):
                try:
                    length = min(int(self.headers.get("Content-Length") or 0), 8192)
                    body = json.loads(self.rfile.read(length) or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError("send a JSON object")
                    if path == "/api/settings":
                        return self._json(library.save_settings(body))
                    library.start_digest()
                    return self._json({"started": True})
                except RuntimeError as err:
                    return self._text(HTTPStatus.CONFLICT, str(err))
                except ValueError as err:
                    return self._text(HTTPStatus.BAD_REQUEST, str(err))
            match = (re.match(r"^/api/(speakers|reminders)/(\d+)$", path)
                     or re.match(r"^/api/(lines)/(\d+)/speaker$", path))
            if not match:
                return self._text(HTTPStatus.NOT_FOUND, "Not found.")
            kind, item = match.group(1), int(match.group(2))
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 4096)
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("send a JSON object")
                if kind in ("speakers", "lines"):
                    name = body.get("name", "")
                    if not isinstance(name, str):
                        raise ValueError("a speaker needs a name")
                    change = library.rename_speaker if kind == "speakers" else library.assign_line_speaker
                    return self._json({"id": change(item, name[:80])})
                status = body.get("status")
                if not isinstance(status, str):
                    raise ValueError("a reminder needs a status")
                library.set_reminder_status(item, status)
                return self._json({"id": item, "status": status})
            except ValueError as err:
                return self._text(HTTPStatus.BAD_REQUEST, str(err))
            except sqlite3.Error as err:
                return self._text(HTTPStatus.INTERNAL_SERVER_ERROR, f"Could not save: {err}")

        def _ask(self) -> None:
            """Answer a question, sending progress as it happens.

            The reply is one JSON object per line: {"step": ...} while Claude looks
            things up, {"text": ...} for each piece of the answer as it is written
            ({"text": null} means discard what came so far), then the whole
            {"answer": ..., "lines": ..., "chat": thread id}, or {"error": ...}.
            Send {"question": ..., "chat": thread id or null}.
            """
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 1 << 20)
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("send a JSON object")
                question = body.get("question")
                if not isinstance(question, str) or not question.strip():
                    raise ValueError("ask a question first")
                question = question.strip()[:4000]
                chat_id = body.get("chat")
                if chat_id is not None and (not isinstance(chat_id, int) or isinstance(chat_id, bool)):
                    raise ValueError("chat must be a thread id")
            except ValueError as err:
                return self._text(HTTPStatus.BAD_REQUEST, str(err))
            if config.provider() != "claude":
                return self._text(HTTPStatus.BAD_REQUEST,
                                  "Ask needs Claude. Choose Claude in Settings first; "
                                  "your questions and the transcripts it reads are sent to Anthropic.")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()  # no length: the reply ends when the connection closes

            def emit(item: dict) -> None:
                try:
                    self.wfile.write(json.dumps(item).encode() + b"\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the reader left; let the answer finish quietly

            try:
                # The thread so far comes from the database, not from the page.
                earlier = library.chat(chat_id) if chat_id is not None else []
                history = [{"role": m["role"], "content": m["content"]} for m in earlier][-40:]
                history.append({"role": "user", "content": question})
                result = ask_mod.answer(library.data_dir, history, config.api_key(),
                                        on_step=lambda step: emit({"step": step}),
                                        on_text=lambda text: emit({"text": text}))
                # Saved only once answered, so a failed question leaves no half-thread.
                result["chat"] = library.save_exchange(
                    chat_id, question, result["answer"], result["lines"])
                emit(result)
            except digest_mod.DigestError as err:
                emit({"error": str(err)})
            except Exception as err:  # never leave the page waiting on a broken stream
                emit({"error": f"Something went wrong: {err}"})

        def _import(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if not 0 < length <= _MAX_UPLOAD:
                return self._text(HTTPStatus.BAD_REQUEST, "Choose an export zip to import.")
            try:
                return self._json(library.import_export(self.rfile, length))
            except RuntimeError as err:
                return self._text(HTTPStatus.CONFLICT, str(err))
            except zipfile.BadZipFile:
                return self._text(HTTPStatus.BAD_REQUEST, "That file is not a zip archive.")
            except (ValueError, OSError, sqlite3.Error) as err:
                return self._text(HTTPStatus.BAD_REQUEST, f"Could not import: {err}")

        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser stopped listening, e.g. while seeking

        def _json(self, payload) -> None:
            self._send(HTTPStatus.OK, json.dumps(payload).encode(), "application/json")

        def _text(self, status: int, message: str) -> None:
            self._send(status, message.encode(), "text/plain; charset=utf-8")

        def _audio(self, file: Path | None) -> None:
            if file is None:
                return self._text(HTTPStatus.NOT_FOUND, "No such recording.")
            data = file.read_bytes()
            size = len(data)
            headers = {"Accept-Ranges": "bytes"}
            match = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
            if not match or not (match.group(1) or match.group(2)):
                return self._send(HTTPStatus.OK, data, "audio/ogg", headers)
            if match.group(1):
                start = int(match.group(1))
                end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
            else:  # "bytes=-N": the last N bytes
                start, end = max(0, size - int(match.group(2))), size - 1
            if start >= size or start > end:
                headers["Content-Range"] = f"bytes */{size}"
                return self._send(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, b"", "audio/ogg", headers)
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            self._send(HTTPStatus.PARTIAL_CONTENT, data[start : end + 1], "audio/ogg", headers)

    return Handler


def make_server(data_dir: Path, port: int, link_speakers: bool = False) -> ThreadingHTTPServer:
    from .store import Store

    # Opening the store creates the database if needed and applies any upgrades,
    # so the read-only queries below always see the current layout.
    Store(data_dir).close()
    library = Library(data_dir, link_speakers)
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(library))
