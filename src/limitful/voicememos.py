"""Bring in Voice Memos from the Mac's own Voice Memos library.

Apple offers no way to fetch Voice Memos from iCloud. What a Mac signed in to
the same Apple account has is a folder the Voice Memos app syncs them into:
one audio file per memo, and a small database with each memo's title and the
moment it began. This reads that folder; it never writes to it.

macOS guards the folder: whatever runs Limitful needs Full Disk Access.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .recordings import NotAudio, add_recording
from .store import Store

_FOLDERS = (
    "Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings",  # macOS 14 and later
    "Library/Application Support/com.apple.voicememos/Recordings",            # before that
)
_DATABASE = "CloudRecordings.db"
_AUDIO = (".m4a", ".qta", ".caf", ".wav", ".mp3")
_APPLE_EPOCH_S = 978_307_200  # Core Data counts seconds from 1 January 2001
_SETTLE_S = 30                # a file changed this recently may still be arriving


class NoAccess(Exception):
    """macOS refused to let this program read the Voice Memos folder."""


class NoLibrary(Exception):
    """There is no Voice Memos folder on this computer."""


@dataclass(frozen=True)
class Memo:
    file: Path
    key: str                 # what it is remembered by, so it is added once
    title: str | None
    start_ms: int | None     # None when the database could not say
    deleted: bool = False    # in Voice Memos' Recently Deleted


@dataclass(frozen=True)
class Synced:
    added: int = 0
    failed: int = 0


def supported() -> bool:
    return sys.platform == "darwin" or bool(os.environ.get("LIMITFUL_VOICE_MEMOS"))


def folder() -> Path:
    """Where Voice Memos keeps its recordings. LIMITFUL_VOICE_MEMOS names another folder."""
    chosen = os.environ.get("LIMITFUL_VOICE_MEMOS")
    if chosen:
        return Path(chosen)
    candidates = [Path.home() / each for each in _FOLDERS]
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            return candidate  # it is there, and guarded
    return candidates[0]


def _listing(where: Path) -> list[Path]:
    try:
        return sorted(where.iterdir())
    except PermissionError:
        raise NoAccess from None
    except (FileNotFoundError, NotADirectoryError):
        raise NoLibrary from None


def _from_database(where: Path) -> dict[str, tuple[str | None, int | None, str | None, bool]]:
    """File name -> (title, start in ms, unique id, deleted), from Voice Memos' own database.

    The database is undocumented and has changed between macOS releases, so only
    the columns that are there are read, and any trouble means "nothing known".
    """
    source = where / _DATABASE
    if not source.is_file():
        return {}
    with tempfile.TemporaryDirectory() as scratch:
        # A copy, with its write-ahead log: the app may be writing, and we must never lock it.
        for suffix in ("", "-wal", "-shm"):
            try:
                shutil.copyfile(f"{source}{suffix}", Path(scratch) / f"{_DATABASE}{suffix}")
            except OSError:
                if not suffix:
                    return {}
        try:
            db = sqlite3.connect(Path(scratch) / _DATABASE)
        except sqlite3.Error:
            return {}
        try:
            columns = {row[1] for row in db.execute("PRAGMA table_info(ZCLOUDRECORDING)")}
            if "ZPATH" not in columns:
                return {}

            def column(*names: str) -> str:
                return next((name for name in names if name in columns), "NULL")

            rows = db.execute(
                f"SELECT ZPATH, {column('ZENCRYPTEDTITLE', 'ZCUSTOMLABEL')}, {column('ZDATE')}, "
                f"{column('ZUNIQUEID')}, {column('ZEVICTIONDATE')} FROM ZCLOUDRECORDING").fetchall()
        except sqlite3.Error:
            return {}
        finally:
            db.close()
    known = {}
    for path, title, date, unique, evicted in rows:
        if not isinstance(path, str) or not path:
            continue
        start = round((date + _APPLE_EPOCH_S) * 1000) if isinstance(date, (int, float)) else None
        known[Path(path).name] = (
            title.strip() if isinstance(title, str) and title.strip() else None,
            start, unique if isinstance(unique, str) and unique else None, evicted is not None)
    return known


def look(where: Path | None = None) -> list[Memo]:
    """Every memo in the library, oldest first. Raises NoAccess or NoLibrary."""
    where = where or folder()
    files = [f for f in _listing(where) if f.suffix.lower() in _AUDIO and not f.name.startswith(".")]
    known = _from_database(where)
    memos = []
    for file in files:
        title, start, unique, deleted = known.get(file.name, (None, None, None, False))
        memos.append(Memo(file, f"voicememo:{unique or file.name}", title, start, deleted))
    return sorted(memos, key=lambda memo: (memo.start_ms is None, memo.start_ms or 0, memo.file.name))


def status(where: Path | None = None) -> dict:
    """What Settings shows: whether the library can be read, and how many memos are in it."""
    if not supported():
        return {"state": "unsupported", "memos": 0}
    try:
        memos = [memo for memo in look(where) if not memo.deleted]
    except NoAccess:
        return {"state": "denied", "memos": 0}
    except NoLibrary:
        return {"state": "missing", "memos": 0}
    return {"state": "ok", "memos": len(memos)}


def program() -> str:
    """The program macOS must be told to trust: the Python that runs Limitful."""
    return str(Path(sys.executable).resolve())


def sync(store: Store, since_ms: int = 0, where: Path | None = None, now_ms: int | None = None,
         on_progress=None) -> Synced:
    """Add every memo that began at or after `since_ms` and has not been added before.

    `on_progress(done, total)` is called before each memo and once at the end.
    """
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    waiting = []
    for memo in look(where):
        if memo.deleted:
            continue
        if store.db.execute("SELECT 1 FROM imports WHERE key = ?", (memo.key,)).fetchone():
            continue
        try:
            stat = memo.file.stat()
        except OSError:
            continue
        modified_ms = int(stat.st_mtime * 1000)
        if not stat.st_size or now_ms - modified_ms < _SETTLE_S * 1000:
            continue  # empty, or still being recorded or downloaded
        if (memo.start_ms if memo.start_ms is not None else modified_ms) < since_ms:
            continue
        waiting.append((memo, modified_ms))
    added = failed = 0
    for done, (memo, modified_ms) in enumerate(waiting):
        if on_progress:
            on_progress(done, len(waiting))
        try:
            result = add_recording(store, memo.file, memo.file.name, modified_ms, now_ms,
                                   start_ms=memo.start_ms, origin="voicememos", also_key=memo.key,
                                   title=memo.title)
        except NotAudio:
            failed += 1
            continue
        except PermissionError:
            raise NoAccess from None
        added += result.new
    if on_progress and waiting:
        on_progress(len(waiting), len(waiting))
    return Synced(added, failed)
