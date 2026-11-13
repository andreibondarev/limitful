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

_INDEX = Path(__file__).parent / "web" / "index.html"
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
_SEARCH_LIMIT = 200
_MAX_UPLOAD = 50 * 1024**3
# Imported lines can sit a second or two after their audio; start playback early.
_IMPORT_LEAD_MS = 1500


def _day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def _utterance(row) -> dict:
    uid, start_ms, end_ms, text, segment, segment_start, speaker_id, speaker, label = row
    if speaker_id:
        who = {"id": speaker_id, "name": speaker, "line": uid}
    elif label:  # an imported line: the label only holds within its conversation
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
        "offset": max(0, start_ms - segment_start - (_IMPORT_LEAD_MS if label else 0)) if has_audio else 0,
    }


_SELECT = (
    "SELECT u.id, u.start_ms, u.end_ms, u.text, u.segment, s.start_ms, u.speaker_id, p.name, "
    "u.source_speaker FROM utterances u LEFT JOIN segments s ON s.path = u.segment "
    "LEFT JOIN speakers p ON p.id = u.speaker_id "
)


class Library:
    """Read-only queries over the data folder."""

    def __init__(self, data_dir: Path, link_speakers: bool = False) -> None:
        self.data_dir = Path(data_dir).resolve()
        self._link_speakers = link_speakers
        self._lock = threading.Lock()
        # What the server is busy with, shown in the Lifelog.
        self.job = {"running": False, "what": "", "done": 0, "total": 0, "error": None}

    def import_export(self, stream, length: int) -> dict:
        """Save an uploaded export zip, import it, then start linking speakers."""
        from .importer import import_limitless

        with self._lock:
            if self.job["running"]:
                raise RuntimeError("an import is already running")
            self.job.update(running=True, what="Importing the export", done=0, total=0, error=None)
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

    def _link_job(self) -> None:
        """Recognise the voices in imported conversations. Slow, so it runs in the background."""
        from .speakers import TitanetEmbedder, load_audio
        from .store import Store

        self.job.update(running=True, what="Recognising speakers", done=0, total=0, error=None)
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

    def _with_store(self, action):
        from .store import Store

        store = Store(self.data_dir)
        try:
            return action(store)
        finally:
            store.close()

    def rename_speaker(self, speaker_id: int, name: str) -> int:
        return self._with_store(lambda store: store.rename_speaker(speaker_id, name))

    def assign_line_speaker(self, utterance_id: int, name: str) -> int:
        return self._with_store(lambda store: store.assign_line_speaker(utterance_id, name))

    def conversations(self, day: str) -> list[dict]:
        start = datetime.strptime(day, "%Y-%m-%d")
        lo = int(start.timestamp() * 1000)
        hi = int((start + timedelta(days=1)).timestamp() * 1000)
        return self._with_store(lambda store: store.conversations(lo, hi))

    def reminders(self) -> list[dict]:
        return self._with_store(lambda store: store.reminders())

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
                    return self._json(library.reminders())
                if path == "/api/status":
                    return self._json(library.job)
                if path == "/api/search":
                    query = parse_qs(url.query).get("q", [""])[0].strip()
                    return self._json(library.search(query) if query else [])
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
