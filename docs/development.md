# Development

```sh
uv run pytest
```

The promo video is rebuilt as described in [assets/promo/README.md](../assets/promo/README.md).

## Where the code is

All under `src/limitful/`.

- `cli.py` and `__main__.py`: the commands, and the entry point the login item uses.
- `protocol.py`: the wire format (protobuf-style messages over one BLE service).
- `client.py`: connect, set the clock, read storage status, download pages.
- `usb.py`: readings over the pendant's USB shell, and the one `ble unpair` command.
- `store.py`: the SQLite store: raw pages, recordings, lines, conversations,
  speakers, reminders, day recaps, pauses and chats.
- `ogg.py`: a small Ogg Opus writer.
- `transcribe.py`: speech-to-text engines (local Whisper by default).
- `speech_model.py`: whether the Whisper model is downloaded yet, and how far along.
- `hosted.py`: hosted transcription with speaker labels (Deepgram).
- `scoring.py`: scoring a service's speaker labels against Limitless's.
- `speakers.py`: voice fingerprints for speaker labels.
- `digest.py`: titles, summaries and reminders from a language model.
- `ask.py`: question answering over the transcripts, with citations.
- `search.py`: search by meaning: the local model and its index.
- `upkeep.py`: long jobs the Lifelog can start and stop (re-timing, indexing).
- `config.py`: saved settings, including the API keys.
- `importer.py`: import of a Limitless data export.
- `demo.py`: the made-up data folder. `demo_filler.py` writes its long stretches, the talks and the visitors at the stand.
- `watch.py`: the background loop.
- `autostart.py`: the macOS login item.
- `web.py` and `web/index.html`: the Lifelog web app.
