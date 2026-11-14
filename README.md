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
is about 1.6 GB and downloads on first use. No audio leaves your computer,
unless you choose a hosted service (see Speaker labels).

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

- **Pause** stops the app keeping audio. The pendant itself cannot be told to
  stop recording (no such command is known, and its live-stream mode keeps
  writing to storage, which was measured). So a pause is kept by the app: the
  pendant goes on recording, and anything from the paused period is deleted
  when it syncs, without being stored or transcribed. A Paused marker shows on
  every page until you resume. To stop the pendant recording at all, hold its
  button for two seconds to switch it off.
- **Pairing** has two buttons. Pair this computer waits three minutes while
  you put the pendant in pairing mode. Unpair makes the pendant forget this
  computer so another can pair with it, keeping its recordings.

On the command line: `limitful pause`, `limitful resume`, `limitful pair` and
`limitful unpair`.

Unpair has only been tested against a simulated pendant.

### Speaker labels

Automatic speaker labels are **off by default**, because nothing tested so far
works on real pendant recordings.

What was measured, on ten imported conversations, as the share of speaking
time given to the same speaker Limitless gave it to (always guessing the main
speaker scores 63%):

| Method | Score |
|---|---|
| Separation model (pyannote segmentation with five different voice models), told the number of speakers | 62% |
| The same, deciding the number of speakers itself | 28% to 49% |
| Grouping transcript lines by voice fingerprint | 30% to 49% |
| Claude reading the words alone | 58% |

The same separation pipeline splits a clean two-speaker test recording
correctly, so the difficulty is the audio: one microphone, worn, with people
at different distances. Limitless's labels are also not a clean reference: in
43% of conversations, lines it gives to one speaker sound no more alike than
lines it gives to different speakers.

What does work:

- Imported conversations keep Limitless's per-conversation "Speaker 1",
  "Speaker 2". Click one to name that speaker in that conversation.
- Click a named speaker to rename that person everywhere; giving two speakers
  the same name merges them. "Only this conversation" changes one conversation.
- `uv run limitful speakers` lists speakers; `--rename 2 Andrei` names one.

Telling which speaker is you, by loudness, was also measured and does not
work. The idea: the pendant is worn, so its wearer should be the loudest voice
in every conversation. In the six imported conversations where one speaker is
named as the wearer, the wearer was the loudest speaker in three (chance
would be 2.6 of six), and never by more than half a decibel either way. Across
twenty other conversations the loudest speaker led the next by a median of
1.7 dB, and by under 1 dB in 30% of them. The pendant appears to even out
loudness, so nothing was built on it. Six conversations is a small sample, and
some of those names may have come from the unreliable voice linking.

#### Speaker labels from a hosted service (opt-in, untested)

A hosted transcription service can label speakers where local methods could
not. Limitful can use [Deepgram](https://deepgram.com) in place of local
Whisper for new recordings from the pendant:

- Choose it under Settings, Transcription, and paste a Deepgram API key, or
  run `uv run limitful transcribe --engine deepgram` once a key is saved.
- **The audio of every new recording is then sent to Deepgram and billed to
  your Deepgram account.** Nothing is sent until you choose this. The key is
  kept in `~/.config/limitful/config.json`, readable only by you, and is never
  shown again.
- A service's "Speaker 1" only means something within one request, and the
  pendant splits a conversation into many short recordings. So recordings are
  grouped into conversations (a five-minute silence ends one), joined, and sent
  as one piece. The newest conversation waits until it has been quiet for five
  minutes, so text appears a little later than with local transcription.
- Lines arrive as "Speaker 1", "Speaker 2" within each conversation. Click one
  to name that speaker in that conversation, exactly as with imported ones.
- Imported conversations are never sent; they keep Limitless's transcript.

**This has not been run against the real Deepgram service**: no key was
available when it was written. It is tested against a stand-in server that
follows Deepgram's published reference. Not confirmed from that reference, and
so the first things to check if it fails:

- that an Ogg Opus body is accepted with the content type `audio/ogg`;
- that each line in the reply carries its speaker (if not, the speaker heard
  on most of the line's words is used, which the reference does document);
- what refused keys and exhausted credit look like (assumed: HTTP 401 or 403,
  and 402);
- that `punctuate` and `smart_format` can be sent together;
- how good the labels are on pendant audio. Nobody has measured it.

To measure it, at your own cost:

```sh
uv run limitful score-speakers --limit 5
```

sends up to five imported conversations (two to four speakers, under twenty
minutes each) to Deepgram and prints, for each, the share of speaking time it
gave to the same speaker Limitless did, next to the score for always guessing
the main speaker. On the conversations used for the table above that baseline
was 63%; a service worth switching to should beat it clearly.

The experimental voice labelling is still there for anyone who wants to try
it: `limitful transcribe --speakers`, `limitful watch --speakers`, and
`limitful speakers --link-imported` for imported conversations.

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
2. Try hosted transcription against the real service and measure its speaker
   labels with `score-speakers`.
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
