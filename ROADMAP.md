# Roadmap

What is planned for Limitful, and ideas that are not planned yet. The README
says what already works and what has not been verified.

## Planned

- Start at login on Linux and Windows (macOS is done).
- Let Ask search reminders.
- Let an assistant act through the MCP server (keep or dismiss a reminder, rename a
  conversation). Today it only reads.
- Open firmware. Research only so far.
- Import the chats in a Limitless export. They are already in the zip; only
  requesting the export has the December 1, 2026 deadline.

## Ideas

Not designed or scheduled. Each needs deciding what it should do first.

- **Analytics.** Insights drawn from conversations: where the time goes, who
  it is spent with, what keeps coming up, how that changes over weeks.
- **Pruning and cleaning.** Delete conversations that are meaningless
  recordings (stray noise, the television, a phrase repeated as a test), and
  edit audio to clean it up, for example cutting silence or a section that
  should not be kept.
- **Sharing.** Send a conversation's audio or transcript to someone else,
  whole or as a selected stretch. Copying one conversation as Markdown is the
  only part that exists.

## Dropped, with reasons

- **Automatic speaker labels, as a default.** Every local method tried, and
  Deepgram, scored at or below always guessing the main speaker. The numbers
  are in [docs/experiments.md](docs/experiments.md). The experimental commands remain.
- **Transcription on the Apple GPU by default.** Three to four times faster when
  it works, but half the test runs failed outright.
- **A true pause or power-off command.** The pendant's USB shell has no
  recording switch, and anything it can do only works while plugged in. The
  app-side pause stands in for it.
