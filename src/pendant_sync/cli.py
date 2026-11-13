"""Command-line interface: scan, pair, status, sync, export, transcribe, watch, serve."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

from . import __version__
from .client import Pendant, PendantError, pair, scan
from .store import Store
from .transcribe import DEFAULT_MODEL
from .watch import watch


def default_data_dir() -> Path:
    return Path(os.environ.get("PENDANT_SYNC_DATA") or Path.home() / "PendantSync")


async def _resolve(address: str | None, timeout: float):
    if address:
        return address
    pendants = await scan(timeout)
    if not pendants:
        raise PendantError(
            "no pendant found. It only advertises when it is not connected to "
            "another device, so turn off Bluetooth on your phone (or quit the "
            "Limitless app) and try again."
        )
    if len(pendants) > 1:
        print(f"{len(pendants)} pendants found; using the strongest signal.", file=sys.stderr)
    return pendants[0][0]


async def _cmd_scan(args) -> int:
    pendants = await scan(args.timeout)
    if not pendants:
        print("No pendant found.")
        return 1
    for device, rssi in pendants:
        print(f"{device.address}  {device.name or '(unnamed)'}  rssi {rssi} dBm")
    return 0


def _print_state(state) -> None:
    print(f"stored pages:  {state.page_count} ({state.oldest_flash_page}..{state.newest_flash_page})")
    print(f"free pages:    {state.free_capture_pages} of {state.total_capture_pages}")
    print(f"session:       {state.current_storage_session}")


async def _cmd_status(args) -> int:
    device = await _resolve(args.address, args.timeout)
    async with Pendant(device) as pendant:
        _print_state(await pendant.status())
    return 0


async def _cmd_pair(args) -> int:
    print("Put the pendant in pairing mode now: press and release the button, then")
    print("immediately press and hold until the purple light goes out. Blue means ready.")
    print("This is a factory reset: it erases any audio still stored on the pendant.")
    print(f"Accept the pairing request if your computer shows one. Waiting {args.timeout:.0f} s...")
    state = await pair(args.timeout)
    if state is None:
        print("Gave up: the pendant never accepted this computer.")
        return 1
    print("Paired. The pendant accepted this computer.")
    _print_state(state)
    return 0


def _print_segments(segments) -> None:
    total_s = sum(s.duration_ms for s in segments) / 1000
    print(f"Exported {len(segments)} audio file(s), {total_s / 60:.1f} min.")
    for seg in segments:
        print(f"  {seg.path}  ({seg.duration_ms / 1000:.0f} s)")


async def _cmd_sync(args) -> int:
    store = Store(args.data_dir)
    try:
        device = await _resolve(args.address, args.timeout)

        def progress(received: int, total: int) -> None:
            print(f"\r  {received}/{total} pages", end="", file=sys.stderr, flush=True)

        async with Pendant(device) as pendant:
            result = await pendant.sync(store, ack=args.ack, on_progress=progress)
        if result.pages_received:
            print(file=sys.stderr)

        if result.reason == "empty":
            print("Nothing stored on the pendant.")
        else:
            print(f"Received {result.pages_received} pages ({result.pages_new} new), "
                  f"finished: {result.reason}.")
            if result.acked_up_to is not None:
                print(f"Pendant freed pages up to {result.acked_up_to}.")
            elif not args.ack:
                print("Pendant storage untouched (run with --ack to free synced pages).")
        if not args.no_export:
            _print_segments(store.export_audio())
        return 0 if result.reason != "stalled" else 2
    finally:
        store.close()


async def _cmd_export(args) -> int:
    store = Store(args.data_dir)
    try:
        _print_segments(store.export_audio())
    finally:
        store.close()
    return 0


async def _cmd_transcribe(args) -> int:
    store = Store(args.data_dir)
    try:
        if args.redo:
            store.forget_transcriptions()
        pending = store.pending_transcription()
        if not pending:
            print("Nothing new to transcribe.")
            return 0
        from .transcribe import WhisperTranscriber

        print(f"Loading {args.model} (downloads on first use)...", file=sys.stderr)
        transcriber = WhisperTranscriber(args.model, args.language, args.device)

        def progress(done: int, total: int) -> None:
            print(f"\r  {done}/{total} files", end="", file=sys.stderr, flush=True)

        started = time.monotonic()
        added, files = store.transcribe_pending(transcriber, progress)
        print(file=sys.stderr)
        audio_s = sum(duration for _, _, duration in pending) / 1000
        took = time.monotonic() - started
        print(f"Transcribed {audio_s / 60:.1f} min of audio in {took:.0f} s: {added} line(s).")
        if not added:
            print("No speech was detected in the new audio.")
        for path in files:
            print(f"  {path}")
        return 0
    finally:
        store.close()


async def _cmd_watch(args) -> int:
    store = Store(args.data_dir)
    cached: list = []

    def get_transcriber():
        if not cached:
            from .transcribe import WhisperTranscriber

            print(f"Loading {args.model} (downloads on first use)...", flush=True)
            cached.append(WhisperTranscriber(args.model, args.language, args.device))
        return cached[0]

    print(f"Watching for the pendant every {args.interval:.0f} s. Data: {args.data_dir}")
    print("Synced audio is " + ("kept on" if args.keep else "freed from") + " the pendant. "
          "Press Ctrl-C to stop.")
    try:
        await watch(store, interval=args.interval, ack=not args.keep,
                    get_transcriber=None if args.no_transcribe else get_transcriber)
    finally:
        store.close()
    return 0


async def _cmd_serve(args) -> int:
    from .web import make_server

    try:
        server = make_server(args.data_dir, args.port)
    except OSError as err:
        raise PendantError(f"could not use port {args.port}: {err.strerror or err}") from None
    print(f"Lifelog is at http://localhost:{server.server_port}  (data: {args.data_dir})")
    print("Press Ctrl-C to stop.")
    try:
        await asyncio.to_thread(server.serve_forever)
    finally:
        server.shutdown()
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pendant-sync",
        description="Pull recordings off a Limitless Pendant over Bluetooth.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def device_args(p) -> None:
        p.add_argument("--address", help="pendant address from `scan` (default: auto-detect)")
        p.add_argument("--timeout", type=float, default=8.0, help="scan time in seconds")

    def data_args(p) -> None:
        p.add_argument("--data-dir", type=Path, default=default_data_dir(),
                       help="where recordings are stored (default: ~/PendantSync, "
                            "or $PENDANT_SYNC_DATA)")

    p = sub.add_parser("scan", help="list pendants advertising nearby")
    p.add_argument("--timeout", type=float, default=8.0)
    p.set_defaults(func=_cmd_scan)

    p = sub.add_parser("pair", help="pair this computer with the pendant (first use)")
    p.add_argument("--timeout", type=float, default=180.0, help="how long to wait, in seconds")
    p.set_defaults(func=_cmd_pair)

    p = sub.add_parser("status", help="show how much audio is stored on the pendant")
    device_args(p)
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("sync", help="download stored audio from the pendant")
    device_args(p)
    data_args(p)
    p.add_argument("--ack", action="store_true",
                   help="free synced pages on the pendant (deletes its copy)")
    p.add_argument("--no-export", action="store_true", help="skip writing audio files")
    p.set_defaults(func=_cmd_sync)

    p = sub.add_parser("export", help="write downloaded pages as Ogg Opus files")
    data_args(p)
    p.set_defaults(func=_cmd_export)

    p = sub.add_parser("transcribe", help="turn downloaded audio into text, locally")
    data_args(p)
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Whisper model (default: {DEFAULT_MODEL})")
    p.add_argument("--language", help="language code such as en (default: detect per file)")
    p.add_argument("--device", default="auto",
                   help="auto, cpu, cuda, or mps (experimental Apple GPU support)")
    p.add_argument("--redo", action="store_true",
                   help="transcribe everything again, replacing existing transcripts")
    p.set_defaults(func=_cmd_transcribe)

    p = sub.add_parser("watch", help="keep syncing and transcribing in the background")
    data_args(p)
    p.add_argument("--interval", type=float, default=120.0,
                   help="seconds between sync attempts (default: 120)")
    p.add_argument("--keep", action="store_true",
                   help="do not free synced audio on the pendant")
    p.add_argument("--no-transcribe", action="store_true", help="download audio only")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Whisper model (default: {DEFAULT_MODEL})")
    p.add_argument("--language", help="language code such as en (default: detect per file)")
    p.add_argument("--device", default="auto",
                   help="auto, cpu, cuda, or mps (experimental Apple GPU support)")
    p.set_defaults(func=_cmd_watch)

    p = sub.add_parser("serve", help="open the Lifelog: browse transcripts and play audio")
    data_args(p)
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 4747),
                   help="port to listen on (default: $PORT or 4747)")
    p.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    try:
        return asyncio.run(args.func(args))
    except PendantError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
