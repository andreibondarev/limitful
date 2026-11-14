"""Whether the local speech model is on this computer yet, and how its download is going.

The model is about 1.6 GB and is fetched the first time something is
transcribed. Without progress that looks like a hang, so the Lifelog asks here.
"""

from __future__ import annotations

from pathlib import Path

from .transcribe import DEFAULT_MODEL

# Sizes of the models people are likely to use, for a progress bar. Unknown ones show bytes only.
KNOWN_BYTES = {"large-v3-turbo": 1_621_665_983}


def _cache_dir(model: str) -> Path | None:
    try:
        from faster_whisper import utils
        from huggingface_hub import constants
    except ImportError:
        return None
    repo = utils._MODELS.get(model, model if "/" in model else None)
    if repo is None:
        return None
    return Path(constants.HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))


def ready(model: str = DEFAULT_MODEL) -> bool:
    """True if the model can be loaded without downloading anything."""
    try:
        from faster_whisper import utils

        utils.download_model(model, local_files_only=True)
        return True
    except Exception:  # not cached, or the cache is unreadable: either way, a download is ahead
        return False


def downloaded_bytes(model: str = DEFAULT_MODEL) -> int:
    """How much of the model has arrived so far, counting files still in flight."""
    folder = _cache_dir(model)
    if folder is None or not (folder / "blobs").is_dir():
        return 0
    total = 0
    for item in (folder / "blobs").iterdir():
        try:
            total += item.stat().st_size
        except OSError:
            pass  # renamed as it completed
    return total
