"""Command-line interface: scan, status, sync, export."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from . import __version__
from .client import Pendant, PendantError, scan
from .store import Store


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


async def _cmd_status(args) -> int:
    device = await _resolve(args.address, args.timeout)
    async with Pendant(device) as pendant:
        state = await pendant.status()
    print(f"stored pages:  {state.page_count} ({state.oldest_flash_page}..{state.newest_flash_page})")
    print(f"free pages:    {state.free_capture_pages} of {state.total_capture_pages}")
    print(f"session:       {state.current_storage_session}")
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
        p.add_argument("--data-dir", type=Path, default=Path("data"),
                       help="where recordings are stored (default: ./data)")

    p = sub.add_parser("scan", help="list pendants advertising nearby")
    p.add_argument("--timeout", type=float, default=8.0)
    p.set_defaults(func=_cmd_scan)

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
