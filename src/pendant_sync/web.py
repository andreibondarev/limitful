"""Local web app: browse each day's transcript and play the audio behind any line.

Serves on 127.0.0.1 only. The data is private, so requests are also checked
for a local Host header, which stops other websites reaching it through DNS
tricks in the browser.
"""

from __future__ import annotations

import json
import re
import sqlite3
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


def _day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")


def _utterance(row) -> dict:
    uid, start_ms, end_ms, text, segment, segment_start = row
    return {
        "id": uid,
        "start": start_ms,
        "end": end_ms,
        "text": text,
        "audio": "/" + segment,
        "offset": max(0, start_ms - segment_start),
    }


_SELECT = (
    "SELECT u.id, u.start_ms, u.end_ms, u.text, u.segment, s.start_ms "
    "FROM utterances u JOIN segments s ON s.path = u.segment "
)


class Library:
    """Read-only queries over the data folder."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir).resolve()

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

    def audio_path(self, url_path: str) -> Path | None:
        """Resolve /audio/... to a file, refusing anything outside the audio folder."""
        root = self.data_dir / "audio"
        target = (self.data_dir / url_path.lstrip("/")).resolve()
        if root.resolve() not in target.parents or target.suffix != ".ogg" or not target.is_file():
            return None
        return target


def make_handler(library: Library):
    class Handler(BaseHTTPRequestHandler):
        server_version = "pendant-sync"

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
                    return self._send(HTTPStatus.OK, _INDEX.read_bytes(), "text/html; charset=utf-8")
                if path == "/api/days":
                    return self._json(library.days())
                if path.startswith("/api/day/"):
                    day = path.removeprefix("/api/day/")
                    if not _DAY.match(day):
                        return self._text(HTTPStatus.BAD_REQUEST, "Day must be YYYY-MM-DD.")
                    return self._json(library.day(day))
                if path == "/api/search":
                    query = parse_qs(url.query).get("q", [""])[0].strip()
                    return self._json(library.search(query) if query else [])
                if path.startswith("/audio/"):
                    return self._audio(library.audio_path(path))
            except (sqlite3.Error, ValueError) as err:
                return self._text(HTTPStatus.INTERNAL_SERVER_ERROR, f"Could not read the data: {err}")
            self._text(HTTPStatus.NOT_FOUND, "Not found.")

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


def make_server(data_dir: Path, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(Library(data_dir)))
