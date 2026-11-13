"""Bluetooth client: find the pendant, read its status, download stored audio."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .protocol import (
    RX_CHAR_UUID,
    SERVICE_UUID,
    TX_CHAR_UUID,
    CommandEncoder,
    FlashPage,
    Reassembler,
    StorageState,
    parse_ble_packet,
    parse_device_status,
    parse_pendant_message,
)
from .store import Store

STATUS_TIMEOUT_S = 8
STALL_TIMEOUT_S = 30
CHECKPOINT_EVERY_PAGES = 25
PAIRING_TIMEOUT_S = 30
PAIRING_RETRY_S = 2
_SETTLE_S = 1.0  # the pendant needs a moment after connect and after subscribing


class PendantError(Exception):
    pass


@dataclass(frozen=True)
class SyncResult:
    reason: str  # "caught_up", "stalled" or "empty"
    pages_received: int
    pages_new: int
    acked_up_to: int | None


async def scan(timeout: float = 8.0) -> list[tuple[BLEDevice, int]]:
    """Return (device, rssi) for every pendant advertising nearby."""
    found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    pendants = []
    for device, adv in found.values():
        name = (adv.local_name or device.name or "").lower()
        uuids = [u.lower() for u in adv.service_uuids]
        if SERVICE_UUID in uuids or "limitless" in name or "pendant" in name:
            pendants.append((device, adv.rssi))
    return sorted(pendants, key=lambda item: -item[1])


class Pendant:
    """One connection to a pendant. Use as an async context manager."""

    def __init__(self, device: BLEDevice | str) -> None:
        self._client = BleakClient(device)
        self._encoder = CommandEncoder()
        self._reassembler = Reassembler()
        self._status_waiter: asyncio.Future[StorageState] | None = None
        self._pages: asyncio.Queue[FlashPage] | None = None

    async def __aenter__(self) -> "Pendant":
        await self._client.connect()
        try:
            await asyncio.sleep(_SETTLE_S)
            await self._client.start_notify(RX_CHAR_UUID, self._on_notify)
            await asyncio.sleep(_SETTLE_S)
            await self._first_write()
        except BaseException:
            await self._client.disconnect()
            raise
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.disconnect()

    async def _first_write(self) -> None:
        """Set the clock. This is the first encrypted write, so it triggers pairing.

        The pendant rejects writes until the link is encrypted. The operating
        system then starts pairing (macOS shows a dialog); retry while it does.
        """
        deadline = time.monotonic() + PAIRING_TIMEOUT_S
        while True:
            try:
                await self._write(self._encoder.set_time(int(time.time() * 1000)))
                return
            except BleakError as err:
                text = str(err).lower()
                if "encryption" not in text and "authentication" not in text:
                    raise
                if time.monotonic() >= deadline:
                    raise PendantError(
                        "the pendant refused the connection because this computer is "
                        "not paired with it. Put the pendant in pairing mode (while a "
                        "light is visible, press once, then press and hold until the "
                        "light turns pink, then release), accept the pairing request "
                        "on this computer, and run the command again."
                    ) from None
                await asyncio.sleep(PAIRING_RETRY_S)

    async def _write(self, packet: bytes) -> None:
        await self._client.write_gatt_char(TX_CHAR_UUID, packet, response=True)

    def _on_notify(self, _sender, raw: bytearray) -> None:
        data = bytes(raw)
        self._offer_status(data)
        packet = parse_ble_packet(data)
        if packet is None:
            return
        payload = self._reassembler.add(packet)
        if payload is None:
            return
        self._offer_status(payload)
        if self._pages is not None:
            for page in parse_pendant_message(payload):
                self._pages.put_nowait(page)

    def _offer_status(self, data: bytes) -> None:
        waiter = self._status_waiter
        if waiter is None or waiter.done():
            return
        state = parse_device_status(data)
        if state is not None:
            waiter.set_result(state)

    async def status(self) -> StorageState:
        self._status_waiter = asyncio.get_running_loop().create_future()
        try:
            await self._write(self._encoder.get_status())
            return await asyncio.wait_for(self._status_waiter, STATUS_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise PendantError("the pendant did not report its storage status") from None
        finally:
            self._status_waiter = None

    async def sync(
        self,
        store: Store,
        *,
        ack: bool = False,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> SyncResult:
        """Download stored flash pages into the store.

        With ack=False nothing is removed from the pendant. With ack=True the
        pendant is told to free pages, but only after they are committed to
        disk and only up to the last page with no gap before it.
        """
        state = await self.status()
        if state.page_count == 0:
            return SyncResult("empty", 0, 0, None)

        end_page = state.newest_flash_page
        total = state.page_count
        received = new = 0
        max_seen = -1
        contiguous_to: int | None = None  # highest index with no gap before it
        gap = False
        acked_to: int | None = None
        uncommitted = 0
        reason = "stalled"

        async def checkpoint() -> None:
            nonlocal acked_to, uncommitted
            store.commit()
            uncommitted = 0
            if ack and contiguous_to is not None and contiguous_to != acked_to:
                await self._write(self._encoder.acknowledge(contiguous_to))
                acked_to = contiguous_to

        self._reassembler.clear()
        self._pages = asyncio.Queue()
        await self._write(self._encoder.set_mode(download=True, realtime=False))
        try:
            while True:
                try:
                    page = await asyncio.wait_for(self._pages.get(), STALL_TIMEOUT_S)
                except asyncio.TimeoutError:
                    break
                if page.index is None:
                    continue
                received += 1
                if store.add_page(page):
                    new += 1
                uncommitted += 1
                if not gap:
                    if contiguous_to is None or page.index == contiguous_to + 1:
                        contiguous_to = page.index
                    elif page.index > contiguous_to + 1:
                        gap = True  # a page went missing: never ack past this point
                max_seen = max(max_seen, page.index)
                if on_progress:
                    on_progress(received, total)
                if uncommitted >= CHECKPOINT_EVERY_PAGES:
                    await checkpoint()
                if max_seen >= end_page:
                    reason = "caught_up"
                    break
        finally:
            self._pages = None
            try:
                await checkpoint()
            finally:
                # Always hand the pendant back to recording-to-flash.
                await self._write(self._encoder.set_mode(download=False, realtime=False))
        return SyncResult(reason, received, new, acked_to)
