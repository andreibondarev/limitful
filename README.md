# pendant-sync

An open-source desktop client for the Limitless Pendant. It pulls recordings off
the pendant over Bluetooth and saves them as audio files on your computer, with
no Limitless account or server involved.

Limitless ends its service on December 1, 2026. This project exists so the
hardware keeps working after that.

**Status: early, but working.** Pairing, status and read-only sync have been run
against a real pendant on macOS, and the downloaded audio plays. Freeing space
on the pendant (`--ack`) is tested against a simulated pendant only.

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Use

The pendant only advertises when no other device is connected to it, so turn
off Bluetooth on your phone (or quit the Limitless app) first.

The first time, run `pair` and put the pendant in pairing mode: while a light is
visible, press the button once, then press and hold until the light turns pink,
and release. Accept the connection request your computer shows. **Pairing mode
resets the pendant and clears the audio stored on it**, so let the Limitless app
sync first if you still use it.

```sh
uv run pendant-sync scan      # find the pendant
uv run pendant-sync pair      # first use only: pair this computer with it
uv run pendant-sync status    # how much audio is stored on it
uv run pendant-sync sync      # download everything into ./data
uv run pendant-sync transcribe  # turn new audio into text, on this machine
```

Transcripts are written to `data/transcripts/<date>.md`, one timestamped line
per utterance. Transcription uses Whisper (`large-v3-turbo`) locally; the model
is about 1.6 GB and downloads on first use. No audio leaves your computer.

Audio lands in `data/audio/<date>/<time>.ogg` (Ogg Opus, plays in VLC, ffmpeg
and most browsers). The raw pages from the pendant are kept in
`data/pendant.db`, so audio can be re-exported later with
`uv run pendant-sync export`.

On macOS the first run asks for Bluetooth permission for your terminal app.

### Freeing space on the pendant

By default `sync` is read-only: the pendant keeps its copy and will send the
same pages again next time (they are skipped locally).

```sh
uv run pendant-sync sync --ack
```

`--ack` tells the pendant to delete pages once they are safely on disk. Until
Limitless shuts down, anything you free this way will never reach the Limitless
app or cloud. Leave it off until you trust your local copy.

## How it works

- `protocol.py`: the wire format (protobuf-style messages over one BLE service).
- `client.py`: connect, set the clock, read storage status, download pages.
- `store.py`: SQLite store of raw pages, and export to audio files.
- `ogg.py`: a small Ogg Opus writer.
- `transcribe.py`: speech-to-text engines (local Whisper by default).

## Hardware notes

Observed on one pendant; treat as provisional.

- Firmware is built on Zephyr. Over USB it appears as "Pendant" by "ZEPHYR"
  (vendor 0x2fe3, product 0x0110) with a serial port.
- Bluetooth services: battery, the Limitless data service, and Zephyr's device
  management (SMP) service, which is normally used for firmware updates.
- Commands are refused with "Insufficient Encryption" until the host is paired.
  The pendant only accepts a new host in pairing mode.
- Audio is mono Opus in 20 ms frames. A flash page is about 4 KB and holds
  roughly 1.4 s; the pendant reports 95,232 pages, so about 38 hours.
- The pendant stops recording during silence, so audio arrives as short bursts.

## Roadmap

1. Verify `--ack` and long downloads on real hardware.
2. Speaker labels, and a hosted transcription option.
3. Daily lifelog view, search and chat over transcripts.
4. Import of a Limitless data export.
5. MCP server, Obsidian sync, mobile app.

## Development

```sh
uv run pytest
```

## Credits

The pendant's Bluetooth protocol was reverse-engineered by the
[Omi](https://github.com/BasedHardware/omi) project (MIT licence). This is an
independent implementation of the same wire format.

Not affiliated with or endorsed by Limitless or Meta.

## Licence

MIT
