# pendant-sync

An open-source desktop client for the Limitless Pendant. It pulls recordings off
the pendant over Bluetooth and saves them as audio files on your computer, with
no Limitless account or server involved.

Limitless ends its service on December 1, 2026. This project exists so the
hardware keeps working after that.

**Status: early, but working.** Pairing, status and read-only sync have been run
against a real pendant on macOS, and so has freeing space on the pendant
(`--ack`). Only tested on macOS so far.

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Use

The pendant only advertises when no other device is connected to it, so turn
off Bluetooth on your phone (or quit the Limitless app) first.

The first time, run `pair` and put the pendant in pairing mode: press and
release the button, then immediately press and hold until the purple light goes
out, and release. A blue light means it is ready to pair. Accept the connection request your computer shows. **Pairing mode
resets the pendant and clears the audio stored on it**, so let the Limitless app
sync first if you still use it.

```sh
uv run pendant-sync scan      # find the pendant
uv run pendant-sync pair      # first use only: pair this computer with it
uv run pendant-sync status    # how much audio is stored on it
uv run pendant-sync sync      # download everything into ~/PendantSync
uv run pendant-sync transcribe  # turn new audio into text, on this machine
```

Transcripts are written to `transcripts/<date>.md`, one timestamped line
per utterance. Transcription uses Whisper (`large-v3-turbo`) locally; the model
is about 1.6 GB and downloads on first use. No audio leaves your computer.

Everything is stored in `~/PendantSync` (change it with `--data-dir` or the
`PENDANT_SYNC_DATA` environment variable). Audio lands in
`audio/<date>/<time>.ogg` (Ogg Opus, plays in VLC, ffmpeg and most browsers).
The raw pages from the pendant are kept in `pendant.db`, so audio can be
re-exported later with `uv run pendant-sync export`.

On macOS the first run asks for Bluetooth permission for your terminal app.

### Reading and listening

```sh
uv run pendant-sync serve
```

Opens the Lifelog at http://localhost:4747: each day's transcript, with a strip
showing when speech happened. Click any line to hear it; playback carries on
through the conversation. Search covers every day. The page only answers on
your own machine. Recordings are Ogg Opus, which Chrome and Firefox play;
older versions of Safari do not.

### Speaker labels

Lines are grouped by voice into "Speaker 1", "Speaker 2" and so on, using a
small local model (TitaNet, about 40 MB, downloaded on first use). This runs
automatically after transcription. Click a name in the Lifelog to rename it;
giving two speakers the same name merges them. From the command line:

```sh
uv run pendant-sync speakers                   # label new lines and list speakers
uv run pendant-sync speakers --rename 2 Andrei
uv run pendant-sync speakers --reset           # forget names and group again
```

Limits: labels start once about ten lines have been transcribed, lines shorter
than 1.5 s are not labelled, a line is given to one speaker even if two people
spoke in it, and similar voices can be confused. The matching threshold was
tuned on a small test and will need adjusting on real conversations.

### Running in the background

```sh
uv run pendant-sync watch
```

`watch` checks for the pendant every two minutes. When it is in range it
downloads new audio, frees that audio on the pendant, and transcribes it. Leave
it running in a terminal. Use `--keep` to leave audio on the pendant and
`--no-transcribe` to download only.

### Freeing space on the pendant

By default `sync` is read-only: the pendant keeps its copy and will send the
same pages again next time (they are skipped locally).

```sh
uv run pendant-sync sync --ack
```

`--ack` tells the pendant to delete pages once they are safely on disk. After
that your computer holds the only copy, so back up the data folder.

## How it works

- `protocol.py`: the wire format (protobuf-style messages over one BLE service).
- `client.py`: connect, set the clock, read storage status, download pages.
- `store.py`: SQLite store of raw pages, and export to audio files.
- `ogg.py`: a small Ogg Opus writer.
- `transcribe.py`: speech-to-text engines (local Whisper by default).
- `speakers.py`: voice fingerprints for speaker labels.
- `watch.py`: the background loop.
- `web.py` and `web/index.html`: the Lifelog web app.

## Using the pendant without the Limitless app

Summarised from Limitless's help centre, which is due to go offline with the
service. The pendant has one button, on its side, and one light.

- **Power on or off:** hold the button for two seconds.
- **Mark a moment:** one quick press.
- **Factory reset and pairing mode:** press and release, then immediately press
  and hold. A purple light appears; keep holding until it goes out, then
  release. A blue light means it is ready to pair. This deletes any recordings
  not yet synced.
- **Solid red light (recovery mode):** hold the button for ten seconds or more
  until the light goes out.
- **Charging:** any standard USB-C charger, but not a Power Delivery (PD)
  charger. It keeps recording while it charges.

Light colours: blue is ready to pair, purple is a factory reset in progress,
solid red is recovery mode, blinking or breathing red is an error. White,
orange and green indicate recording and charging states.

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

1. Run `watch` as a login service.
2. Better speaker labels (splitting a line between two voices), and a hosted
   transcription option.
3. Summaries, reminders and chat over transcripts.
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
