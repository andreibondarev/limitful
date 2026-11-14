"""Start Limitful when the user logs in, so the pendant syncs without a terminal open.

On macOS this is a LaunchAgent: a small file in ~/Library/LaunchAgents that tells
the system to run `limitful serve --sync-every 120` at login and to restart it
if it stops. Other systems are not supported yet.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "dev.limitful.app"
SYNC_EVERY_S = 120


class AutostartError(Exception):
    pass


def supported() -> bool:
    return sys.platform == "darwin"


def plist_path(label: str = LABEL, home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{label}.plist"


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=20)


def _target(label: str) -> str:
    return f"gui/{os.getuid()}/{label}"


def job(data_dir: Path, port: int, sync_every: float = SYNC_EVERY_S, label: str = LABEL) -> dict:
    """What the login item runs."""
    data_dir = Path(data_dir).resolve()
    out = {
        "Label": label,
        "ProgramArguments": [sys.executable, "-m", "limitful", "serve", "--data-dir", str(data_dir),
                             "--port", str(port), "--sync-every", str(int(sync_every))],
        "RunAtLoad": True,
        "KeepAlive": True,          # start it again if it stops
        "ProcessType": "Background",
        "StandardOutPath": str(data_dir / "limitful.log"),
        "StandardErrorPath": str(data_dir / "limitful.log"),
    }
    if os.environ.get("LIMITFUL_CONFIG"):
        out["EnvironmentVariables"] = {"LIMITFUL_CONFIG": os.environ["LIMITFUL_CONFIG"]}
    return out


def status(label: str = LABEL, home: Path | None = None, run=_launchctl) -> dict:
    if not supported():
        return {"supported": False, "enabled": False, "running": False}
    enabled = plist_path(label, home).is_file()
    return {"supported": True, "enabled": enabled,
            "running": enabled and run("print", _target(label)).returncode == 0}


def enable(data_dir: Path, port: int, start_now: bool = True, sync_every: float = SYNC_EVERY_S,
           label: str = LABEL, home: Path | None = None, run=_launchctl) -> dict:
    """Install the login item. With start_now it is also started straight away."""
    if not supported():
        raise AutostartError("starting at login is only supported on macOS so far")
    path = plist_path(label, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    if start_now:
        run("bootout", _target(label))  # an older copy, if one is loaded; fine if not
    with open(path, "wb") as out:
        plistlib.dump(job(data_dir, port, sync_every, label), out)
    if start_now:
        started = run("bootstrap", f"gui/{os.getuid()}", str(path))
        if started.returncode != 0:
            raise AutostartError(f"the login item was written to {path} but could not be started: "
                                 f"{(started.stderr or started.stdout).strip()}")
    return status(label, home, run)


def disable(label: str = LABEL, home: Path | None = None, run=_launchctl) -> dict:
    """Remove the login item, stopping it if it is running."""
    if supported():
        path = plist_path(label, home)
        path.unlink(missing_ok=True)   # first, in case stopping it stops us
        run("bootout", _target(label))
    return status(label, home, run)
