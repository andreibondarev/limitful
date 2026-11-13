"""The background loop, against the simulated pendant."""

import asyncio

import pytest

from pendant_sync import client as client_mod
from pendant_sync import watch as watch_mod
from pendant_sync.store import Store
from pendant_sync.transcribe import Utterance

from test_client import FakePendant, pendant  # noqa: F401  (pytest fixture)


class FakeTranscriber:
    name = "fake"

    def transcribe(self, audio_path):
        return [Utterance(0, 500, "hello")]


@pytest.fixture
def in_range(monkeypatch):
    state = {"visible": True}

    async def fake_scan(timeout=5.0):
        return [("fake-device", -50)] if state["visible"] else []

    monkeypatch.setattr(client_mod, "scan", fake_scan)
    return state


def test_cycle_syncs_acks_exports_and_transcribes(pendant, in_range, tmp_path):
    pendant.page_indices = [0, 1, 2]
    store = Store(tmp_path)
    result = asyncio.run(watch_mod.run_cycle(
        store, ack=True, get_transcriber=FakeTranscriber))
    assert result == watch_mod.CycleResult(True, pages_new=3, audio_files=1, lines=1)
    assert pendant.instance.acks() == [2]
    assert (tmp_path / "transcripts").exists()
    store.close()


def test_cycle_without_pendant_does_nothing(pendant, in_range, tmp_path):
    in_range["visible"] = False
    store = Store(tmp_path)
    result = asyncio.run(watch_mod.run_cycle(store, ack=True, get_transcriber=None))
    assert result == watch_mod.CycleResult(found=False)
    assert pendant.instance is None or store.page_count() == 0
    store.close()


def test_watch_survives_failures_and_reports_once(pendant, in_range, tmp_path, monkeypatch):
    pendant.page_indices = [0, 1]
    store = Store(tmp_path)
    logs = []
    calls = {"n": 0}
    real_cycle = watch_mod.run_cycle

    async def flaky_cycle(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise client_mod.PendantError("link dropped")
        if calls["n"] == 5:
            in_range["visible"] = False
        return await real_cycle(*args, **kwargs)

    monkeypatch.setattr(watch_mod, "run_cycle", flaky_cycle)
    asyncio.run(watch_mod.watch(store, interval=0, ack=False, get_transcriber=None,
                                log=logs.append, cycles=6))
    assert logs == [
        "sync failed, will retry: link dropped",
        "synced 2 new page(s), 1 audio file(s), 0 transcript line(s)",
        "pendant not in range; waiting",  # said once, not every cycle
    ]
    store.close()
