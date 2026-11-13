"""Sync logic against a simulated pendant (no Bluetooth involved)."""

import asyncio

import pytest

from pendant_sync import client as client_mod
from pendant_sync.protocol import decode_varint, parse_ble_packet
from pendant_sync.store import Store

from wire import (ble_packets, device_status, flash_page, opus_frame,
                  pendant_message, storage_buffer)

T0 = 1_763_000_000_000


class FakePendant:
    """Stands in for BleakClient and answers commands like the device does."""

    instance = None

    def __init__(self, _device):
        FakePendant.instance = self
        self.commands: list[tuple[int, bytes]] = []
        self.notify = None
        self.connected = False

    # configured per test
    page_indices: list[int] = []
    reported_newest: int | None = None

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def start_notify(self, _uuid, callback):
        self.notify = callback

    async def write_gatt_char(self, _uuid, data, response=True):
        payload = parse_ble_packet(bytes(data)).payload
        field = decode_varint(payload, 0)[0] >> 3
        length, pos = decode_varint(payload, 1 if field < 16 else 2)
        self.commands.append((field, payload[pos : pos + length]))
        if field == 21:
            newest = self.reported_newest
            if newest is None:
                newest = max(self.page_indices, default=0)
            # An empty pendant reports oldest > newest.
            oldest = min(self.page_indices, default=1)
            self._send(ble_packets(1, device_status(oldest, newest))[0])
        elif field == 8 and payload[pos : pos + length] == b"\x08\x01\x10\x00":
            for n, index in enumerate(self.page_indices):
                frames = [opus_frame(index + i) for i in range(50)]
                msg = pendant_message(
                    storage_buffer(index, flash_page(T0 + n * 1000, frames)))
                for raw in ble_packets(100 + n, msg, fragments=3):
                    self._send(raw)

    def _send(self, raw: bytes):
        self.notify(None, bytearray(raw))

    def acks(self) -> list[int]:
        return [decode_varint(body, 1)[0] for field, body in self.commands if field == 7]


@pytest.fixture
def pendant(monkeypatch):
    monkeypatch.setattr(client_mod, "BleakClient", FakePendant)
    monkeypatch.setattr(client_mod, "_SETTLE_S", 0)
    monkeypatch.setattr(client_mod, "STALL_TIMEOUT_S", 0.2)
    monkeypatch.setattr(client_mod, "STATUS_TIMEOUT_S", 0.2)
    FakePendant.page_indices = []
    FakePendant.reported_newest = None
    return FakePendant


def run_sync(tmp_path, **kwargs):
    async def go():
        store = Store(tmp_path)
        try:
            async with client_mod.Pendant("fake") as p:
                result = await p.sync(store, **kwargs)
            return result, store.page_count()
        finally:
            store.close()

    return asyncio.run(go())


def test_sync_without_ack_leaves_pendant_untouched(pendant, tmp_path):
    pendant.page_indices = list(range(200, 260))
    result, stored = run_sync(tmp_path)
    fake = pendant.instance
    assert (result.reason, result.pages_received, result.pages_new) == ("caught_up", 60, 60)
    assert stored == 60
    assert result.acked_up_to is None and fake.acks() == []
    fields = [field for field, _ in fake.commands]
    assert fields == [6, 21, 8, 8]  # time, status, download mode, back to recording
    assert fake.commands[-1][1] == b"\x08\x00\x10\x00"
    assert not fake.connected


def test_sync_twice_stores_nothing_new(pendant, tmp_path):
    pendant.page_indices = list(range(10))
    run_sync(tmp_path)
    result, stored = run_sync(tmp_path)
    assert (result.pages_received, result.pages_new, stored) == (10, 0, 10)


def test_ack_follows_committed_pages(pendant, tmp_path):
    pendant.page_indices = list(range(200, 260))
    result, _ = run_sync(tmp_path, ack=True)
    assert pendant.instance.acks() == [224, 249, 259]
    assert result.acked_up_to == 259


def test_ack_never_passes_a_missing_page(pendant, tmp_path):
    pendant.page_indices = [0, 1, 2, 4, 5, 6]  # page 3 lost in transit
    result, stored = run_sync(tmp_path, ack=True)
    assert stored == 6
    assert pendant.instance.acks() == [2]
    assert result.acked_up_to == 2


def test_stall_is_reported_and_mode_is_restored(pendant, tmp_path):
    pendant.page_indices = [0, 1, 2]
    pendant.reported_newest = 50  # pendant promises more pages than it sends
    result, stored = run_sync(tmp_path)
    assert (result.reason, stored) == ("stalled", 3)
    assert pendant.instance.commands[-1] == (8, b"\x08\x00\x10\x00")


def test_empty_pendant(pendant, tmp_path):
    result, stored = run_sync(tmp_path)
    assert (result.reason, stored) == ("empty", 0)
    assert [f for f, _ in pendant.instance.commands] == [6, 21]


def test_status_timeout_raises(pendant, tmp_path, monkeypatch):
    monkeypatch.setattr(FakePendant, "_send", lambda self, raw: None)
    with pytest.raises(client_mod.PendantError):
        run_sync(tmp_path)
