# pendant-sync

An open-source desktop client for the Limitless Pendant. It pulls recordings off
the pendant over Bluetooth and saves them as audio files on your computer, with
no Limitless account or server involved.

Limitless ends its service on December 1, 2026. This project exists so the
hardware keeps working after that.

**Status: early.** The protocol code and sync logic are covered by tests against
a simulated pendant, but have not yet been run against a real device.

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Use

The pendant only advertises when no other device is connected to it, so turn
off Bluetooth on your phone (or quit the Limitless app) first.

```sh
uv run pendant-sync scan      # find the pendant
uv run pendant-sync status    # how much audio is stored on it
uv run pendant-sync sync      # download everything into ./data
```

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

## Roadmap

1. Verify against real hardware (this is next).
2. Transcription with speaker labels.
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
