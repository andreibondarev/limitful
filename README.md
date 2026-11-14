<p align="center"><img src="assets/banner.svg" width="560" alt="Limitful. Fine print: limits apply."></p>

# Limitful

An open-source replacement for the Limitless app, for people who want to keep
using their Limitless Pendant. It pulls recordings off the pendant over
Bluetooth, transcribes them on your computer, and gives you a Lifelog to read,
search, listen to and ask questions of. No Limitless account or server is
involved.

Limitless ends its service on December 1, 2026 and deletes the data it holds.
This project exists so the hardware keeps working after that, and so the
history you export before then stays usable.

## What it does

- **Syncs the pendant** over Bluetooth, from the command line, in the
  background, or with a button in the app.
- **Transcribes on your machine** with Whisper. Audio stays on your computer
  unless you choose a hosted service.
- **Lifelog web app**: each day as a list of conversations, with playback from
  any line, a timeline of the day, and search across everything.
- **Summaries and reminders**: a title and summary for each conversation, and
  suggested reminders linked to the line they came from. Uses Claude or a local
  Ollama model, and is off until you choose one.
- **Ask**: questions about what was said, answered with links to the lines
  that support the answer.
- **Imports your Limitless export**: transcripts, audio and reminders.
- **Pendant controls**: battery and storage, light brightness, pause, pair and
  unpair.

**Status: early, but working.** The whole path, from pendant to transcript to
Lifelog, runs daily against one real pendant on macOS. It has not been tested
on Linux or Windows. What has not been verified is listed under
[Not yet verified](#not-yet-verified).

## Install

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/andreibondarev/limitful.git
cd limitful
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
speech happened; click the strip to jump to that moment. Open a conversation
to read it under its section headings, click any line to hear it (playback
carries on through the conversation, with a timeline to jump around in), or
copy it as Markdown. Search covers every day. The page only answers on
your own machine. Recordings are Ogg Opus, which Chrome and Firefox play;
older versions of Safari do not.

### Summaries and reminders

Recordings are grouped into conversations (five minutes of silence ends one).
A language model can then give each a title and a short summary, and suggest
reminders for things someone said they would do. This is off until you choose
what writes them, under Settings, Summaries:

- **Claude**: paste an Anthropic API key. The text of each conversation is
  sent to Anthropic; audio is not.
- **Ollama**: a model running on your own machine (`llama3.1` by default), so
  nothing leaves it.

New conversations are summarised after each sync. `uv run limitful digest`
does it by hand, and `--redo` writes them all again.

The Reminders page shows suggestions grouped by day, each with a link that
plays the moment it came up. Keep one and it moves to your to-do list; tick it
off when it is done.

### Ask

The Ask page answers questions such as "what did the dentist say about the
crown?" by searching and reading your transcripts. Answers cite the lines they
rest on, and each citation opens that line. Chats are saved. From the command
line: `uv run limitful ask "..."`.

Ask needs Claude, with the key saved in Settings. The lines it reads to answer
a question are sent to Anthropic.

### Bringing your Limitless history

Request a data export from Limitless before December 1, 2026, then import the
zip from Settings, Import, or with:

```sh
uv run limitful import data-export.zip
```

Transcripts, section headings, audio and reminders are imported, and
importing the same export twice adds nothing. Speakers keep Limitless's
"Speaker 1", "Speaker 2" within each conversation. Chats in the export are not
imported yet.

Lines in a Limitless transcript often sit a few seconds away from where they
are heard. `uv run limitful retime` listens to the imported audio with Whisper
and moves each line to where its words are; `--minutes 60` does it in
stages and `--undo` puts everything back. It takes roughly a fifth of the
audio's length on a laptop CPU.

### What leaves your computer

Nothing, by default. Syncing, transcription, search and playback are local.
Three things send data out, and each is off until you turn it on in Settings:

| If you choose | What is sent | To |
|---|---|---|
| Claude for summaries | The text of each conversation | Anthropic |
| Ask | The lines it looks up to answer | Anthropic |
| Deepgram for transcription | The audio of new recordings | Deepgram |

API keys are kept in `~/.config/limitful/config.json`, readable only by you,
outside the data folder, and are never sent back to the page.

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
- `store.py`: the SQLite store: raw pages, recordings, lines, conversations,
  reminders and chats.
- `ogg.py`: a small Ogg Opus writer.
- `transcribe.py`: speech-to-text engines (local Whisper by default).
- `hosted.py`: hosted transcription with speaker labels (Deepgram).
- `scoring.py`: scoring a service's speaker labels against Limitless's.
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

## Not yet verified

- **Linux and Windows.** Everything has been run on macOS only.
- **Deepgram.** Hosted transcription has not been run against the real
  service (see Speaker labels).
- **Ollama.** Summaries from a local model are written but have not been run
  against a real Ollama.
- **Unpair.** Tested against a simulated pendant only.
- **Other pendants.** All hardware observations come from one device.

## Roadmap

- Run `watch` and the app at login, so syncing needs no terminal.
- Import the chats in a Limitless export.
- Try Deepgram against the real service and measure its speaker labels.
- Let Ask search reminders.
- An MCP server, so other assistants can query the Lifelog.
- A real pause or power-off command, if the pendant has one. The USB serial
  port and the firmware update service are unexplored.
- Open firmware. Research only so far.

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
