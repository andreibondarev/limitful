# The promo video

`limitful-promo.mp4` is a 75-second silent walk through the app, with captions:
the setup guide, a day in the Lifelog, search, reminders, Settings and Ask.
`poster.jpg` is the still the main README links from.

`limitful-launch.mp4` is a half-minute cut for social media: a few big lines and
the app's best moments, with no setup guide, and music under it. Make it again with
`node assets/promo/make_promo.mjs --short`.

Everything in it is made up. The conversations are the ones `limitful demo`
writes, and `pretend_server.py` stands in for the pendant, the speech model
download and Ask, so making the video touches no real pendant, sends nothing to
a hosted model and never opens your own data folder. The line that "plays" at
the end has a silent recording behind it.

The launch cut opens on Limitless's own mark and a photo of the pendant, so it
is plain what the video is about. `limitless-mark.svg` and
`limitless-pendant.webp` are Limitless's, taken from limitless.ai, and are not
covered by this project's licence.

The music is the start of "One Cool Minute" by Loyalty Freak Music, which the
artist released into the public domain (CC0). `launch-music.ogg` is its first
45 seconds, from
[Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Loyalty_Freak_Music_-_02_-_One_Cool_Minute.ogg).

## Making it again

When the app's look changes, record it again:

```sh
node assets/promo/make_promo.mjs
```

It needs node 22 or newer, `uv`, `ffmpeg` and Google Chrome, takes about two
minutes, and overwrites the video and the poster. It starts the pretend server
on port 4811 and a headless Chrome, drives the page with real clicks and
typing, films it, and assembles the frames with ffmpeg.

Settings, from the environment: `PROMO_WORK` (folder for frames and the
scratch data; a temporary folder by default), `PROMO_PORT`,
`PROMO_CHROME_PORT`, `CHROME` (path to the browser), `PROMO_SPEED` (playback
speed against filming speed, 1.12 by default) and `PROMO_CRF` (ffmpeg quality,
25 by default; lower is better and bigger).

The scenes are the lines after `scene("…")` in `make_promo.mjs`: each is a
caption, some clicks and a pause. If a button is renamed in the app, the script
stops and names what it was waiting for.
