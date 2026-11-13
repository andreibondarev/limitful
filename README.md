<p align="center"><img src="assets/banner.svg" width="560" alt="Limitful. Fine print: limits apply."></p>

# Limitful

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
uv run limitful scan      # find the pendant
uv run limitful pair      # first use only: pair this computer with it
uv run limitful status    # how much audio is stored on it
uv run limitful sync      # download everything into ~/Limitful
uv run limitful transcribe  # turn new audio into text, on this machine
```

Transcripts are written to `transcripts/<date>.md`, one timestamped line
per utterance. Transcription uses Whisper (`large-v3-turbo`) locally; the model
is about 1.6 GB and downloads on first use. No audio leaves your computer.

Everything is stored in `~/Limitful` (change it with `--data-dir` or the
`LIMITFUL_DATA` environment variable). Audio lands in
`audio/<date>/<time>.ogg` (Ogg Opus, plays in VLC, ffmpeg and most browsers).
The raw pages from the pendant are kept in `pendant.db`, so audio can be
re-exported later with `uv run limitful export`.

On macOS the first run asks for Bluetooth permission for your terminal app.

### Reading and listening

```sh
uv run limitful serve
```

Opens the Lifelog at http://localhost:4747. Each day is a list of
conversations with their time, title and length, under a strip showing when
speech happened. Open a conversation to read it under its section headings,
click any line to hear it (playback carries on through the conversation), or
copy it as Markdown. Search covers every day. The page only answers on
your own machine. Recordings are Ogg Opus, which Chrome and Firefox play;
older versions of Safari do not.

### The pendant, from the app

The Lifelog's Settings page has a Pendant section:

- **Check pendant** reads its battery level, how much audio is waiting and how
  much room is left.
- **Sync now** does what `watch` does, once: downloads new audio, frees it on
  the pendant, then transcribes and summarises it, with progress shown.
- **Light** sets the brightness of the pendant's light, from off to 100%. The
  pendant does not report its brightness, so the slider shows the last value
  set from here.

From the command line, `uv run limitful status` shows the same readings and
`--brightness 40` sets the light.

No command for pausing recording is known. Hold the pendant's button for two
seconds to switch it off.

### Speaker labels

Lines are grouped by voice into "Speaker 1", "Speaker 2" and so on, using a
small local model (TitaNet, about 40 MB, downloaded on first use). This runs
automatically after transcription. Click a name in the Lifelog to rename that
person everywhere; giving two speakers the same name merges them. "Only this
conversation" corrects who a speaker is in one conversation without touching
the rest. From the command line:

```sh
uv run limitful speakers                   # label new lines and list speakers
uv run limitful speakers --rename 2 Andrei
uv run limitful speakers --reset           # forget names and group again
```

Limits: labels start once about ten lines have been transcribed, lines shorter
than 1.5 s are not labelled, a line is given to one speaker even if two people
spoke in it, and similar voices can be confused. The matching was tuned on a
small test with synthetic voices in one room. A check on real recordings
suggests the fingerprints pick up the room as much as the voice, so treat
these labels as a rough guide.

### Summaries and reminders

```sh
uv run limitful digest --provider claude    # or: --provider ollama
```

`digest` groups each day's lines into conversations (a five-minute silence ends
one), then asks a language model for a title, a short summary and any
reminders. They appear above each conversation in the Lifelog and in the
Markdown transcripts. Reminders are suggestions: accept or dismiss them in the
Lifelog, where the Reminders button lists everything waiting.

Each reminder links back to the conversation it came from and, where it can be
identified, the line: the Reminders list quotes that line, and clicking the
link jumps to it and starts playing from there. The
model cites the line for reminders it writes. For reminders imported from
Limitless, which only record the conversation, the line is found by matching
the wording, so it is a best guess and some have none.

You choose what does the reading, and nothing is sent anywhere until you do.
The easiest way is the Lifelog's Settings page, which also has a "Summarise new
conversations now" button:

- **Claude** uses Anthropic's API (Claude Opus by default; `--llm-model`
  changes it). Better results, but conversation transcripts are sent to
  Anthropic and usage is billed to your Anthropic account. Paste an API key in
  Settings, or leave it empty to use `ANTHROPIC_API_KEY` or a sign-in from
  Anthropic's command-line tool (`ant auth login`). The key is checked with
  Anthropic before it is saved.
- **Ollama** uses a model running on your computer through
  [Ollama](https://ollama.com) (`llama3.1` by default). Private, weaker.

The choice and the key are saved in `~/.config/limitful/config.json`, readable
only by you and kept out of the data folder so it is not backed up with your
recordings. The `LIMITFUL_LLM` environment variable overrides the saved choice.
Once a choice is saved, `watch` summarises automatically.

Conversations of fewer than 25 words are left without a summary.
`digest --redo` rewrites your own summaries, discarding the state of their
reminders; imported conversations are left alone.

The Claude path has been run for real; the Ollama path is tested with a
stand-in server only.

### Importing your Limitless history

Request a data export from Limitless (with "Include audio files" ticked) before
the service ends, then:

```sh
uv run limitful import ~/Downloads/data-export_2026-11-13_19-19-43.zip
```

This brings in every conversation with its title, section headings and
transcript, the audio, and your reminders. Limitless's transcripts are kept as
they are; nothing is re-transcribed. Running it again on the same file adds
nothing.

You can also import from the Lifelog: open Settings and choose the zip.

Limitless numbers speakers separately in every conversation, so imported lines
show "Speaker 1", "Speaker 2". Click one to name that speaker in that
conversation.

Matching imported speakers across conversations by voice exists but is
experimental and off by default (`uv run limitful speakers --link-imported`,
undone with `--unlink-imported`). On real pendant recordings the voice
fingerprints were dominated by the room and background noise: 42% of pairs of
speakers known to be different people scored as the same person. Do not rely
on it.

Limits: playback of an imported line can start a second or two early or late.
Chats and account settings are not imported.

### Ask

The Lifelog's Ask page answers questions about what was said: "what did I agree
to with Joseph?", "what did they say a session costs?". Claude looks through
your transcripts with three tools (search lines, list conversations, read a
conversation), then answers. You see what it is looking up, and the answer
appears as it is written. Each fact carries a small link showing when it was
said; clicking it opens that line and plays it, so you can check the answer
against the recording. Follow-up questions keep the thread's context, and
threads are saved in your data folder: reopen or delete them under "Earlier
chats".

From the command line: `uv run limitful ask "what did I agree to this week?"`.

Ask needs Claude chosen in Settings. Your questions and the transcript lines
Claude reads are sent to Anthropic. Search is by literal words, not meaning,
so Claude tries several phrasings; it can still miss things said in unexpected
words.

### Running in the background

```sh
uv run limitful watch
```

`watch` checks for the pendant every two minutes. When it is in range it
downloads new audio, frees that audio on the pendant, and transcribes it. Leave
it running in a terminal. Use `--keep` to leave audio on the pendant and
`--no-transcribe` to download only.

### Freeing space on the pendant

By default `sync` is read-only: the pendant keeps its copy and will send the
same pages again next time (they are skipped locally).

```sh
uv run limitful sync --ack
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
- `digest.py`: titles, summaries and reminders from a language model.
- `ask.py`: question answering over the transcripts, with citations.
- `config.py`: saved settings, including the API key.
- `importer.py`: import of a Limitless data export.
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
3. An MCP server, so other assistants can query the transcripts; search by meaning.
4. Link imported speakers to named speakers; import chats.
5. MCP server, Obsidian sync, mobile app.

## Development

```sh
uv run pytest
```

## Credits

The pendant's Bluetooth protocol was reverse-engineered by the
[Omi](https://github.com/BasedHardware/omi) project (MIT licence). This is an
independent implementation of the same wire format.

The wordmark is set in [Outfit](https://github.com/Outfitio/Outfit-Fonts) (SIL Open Font
License), drawn as outlines; `assets/make_logo.py` rebuilds the logo files.

Not affiliated with or endorsed by Limitless or Meta.

## Licence

MIT
