"""User settings, kept outside the data folder.

The data folder is something people back up and sync; an API key does not
belong in it. Settings live in ~/.config/limitful/config.json, readable only
by the user.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROVIDERS = ("claude", "ollama")


def config_path() -> Path:
    return Path(os.environ.get("LIMITFUL_CONFIG")
                or Path.home() / ".config" / "limitful" / "config.json")


def load() -> dict:
    try:
        data = json.loads(config_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(settings: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".tmp")
    # Create the file private from the start, so the key is never world-readable.
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(settings, out, indent=2)
    os.chmod(partial, 0o600)
    os.replace(partial, path)


_KEEP: Any = object()  # "leave this setting as it is"


def update(provider: Any = _KEEP, api_key: Any = _KEEP, led_brightness: Any = _KEEP) -> dict:
    """Change the given settings and return the result. `None` clears a setting."""
    settings = load()
    if provider is not _KEEP:
        if provider is not None and provider not in PROVIDERS:
            raise ValueError(f"provider must be one of {', '.join(PROVIDERS)}, or empty for none")
        settings["provider"] = provider
    if api_key is not _KEEP:
        key = (api_key or "").strip()
        if key:
            settings["anthropic_api_key"] = key
        else:
            settings.pop("anthropic_api_key", None)
    if led_brightness is not _KEEP:
        settings["led_brightness"] = led_brightness  # the pendant cannot be asked, so remember it
    save(settings)
    return settings


def provider() -> str | None:
    """What writes summaries: the environment wins over the saved setting."""
    chosen = os.environ.get("LIMITFUL_LLM") or load().get("provider")
    return chosen if chosen in PROVIDERS else None


def api_key() -> str | None:
    return load().get("anthropic_api_key") or None
