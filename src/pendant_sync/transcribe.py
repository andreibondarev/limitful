"""Speech-to-text for exported audio.

Engines implement `Transcriber`. The default runs Whisper locally through
faster-whisper, so audio never leaves the machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DEFAULT_MODEL = "large-v3-turbo"


@dataclass(frozen=True)
class Utterance:
    start_ms: int  # offset from the start of the audio file
    end_ms: int
    text: str


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio_path: Path) -> list[Utterance]: ...


class WhisperTranscriber:
    """Local Whisper via faster-whisper. The model downloads on first use."""

    def __init__(
        self, model: str = DEFAULT_MODEL, language: str | None = None, device: str = "auto"
    ) -> None:
        from faster_whisper import WhisperModel  # imported lazily: it is slow to load

        self.name = f"whisper:{model}"
        self._language = language
        self._model = WhisperModel(model, device=device, compute_type="auto")

    def transcribe(self, audio_path: Path) -> list[Utterance]:
        segments, _info = self._model.transcribe(
            str(audio_path),
            language=self._language,
            vad_filter=True,  # skip non-speech, where Whisper tends to invent text
            condition_on_previous_text=False,  # stops one bad guess repeating itself
        )
        utterances = []
        for seg in segments:
            text = seg.text.strip()
            if text:
                utterances.append(Utterance(int(seg.start * 1000), int(seg.end * 1000), text))
        return utterances
