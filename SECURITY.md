# Security

Limitful holds recordings and transcripts of people's lives, so problems that
could expose them are taken seriously.

## Reporting a problem

Please report it privately through
[GitHub's security advisory form](https://github.com/andreibondarev/limitful/security/advisories/new),
not in a public issue. Say what you found and how to reproduce it. Do not
include real recordings or transcripts; `limitful demo` makes data that is safe
to share.

Only the latest version is supported.

## What counts

- Another website, or another computer on the network, reading or changing the
  Lifelog. It is meant to answer on `127.0.0.1` only, to requests with a local
  Host header.
- Data leaving the computer other than by the two choices listed under
  [What leaves your computer](README.md#what-leaves-your-computer).
- API keys readable by anyone but you. They are kept in
  `~/.config/limitful/config.json` with owner-only permissions.
- Anything in an imported export, or sent by a pendant, that makes Limitful
  write outside its data folder or run code.

Other programs running as you on the same computer can read the data folder
and reach the Lifelog. That is outside what Limitful defends against.
