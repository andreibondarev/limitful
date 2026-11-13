from datetime import datetime

from limitful.protocol import FlashPage
from limitful.store import Store
from limitful.transcribe import Utterance

from wire import flash_page, opus_frame


class FakeTranscriber:
    name = "fake"

    def __init__(self):
        self.calls = []

    def transcribe(self, audio_path):
        self.calls.append(audio_path.name)
        return [Utterance(0, 900, "first thing said"), Utterance(1200, 1900, "second thing")]


def _store_with_audio(tmp_path, t0):
    store = Store(tmp_path)
    frames = [opus_frame(i) for i in range(50)]  # 1 s per page
    pages = [(0, t0), (1, t0 + 1000), (2, t0 + 60_000), (3, t0 + 120_000)]
    for index, ts in pages:
        store.add_page(FlashPage(index=index, session=1, seq=0,
                                 data=flash_page(ts, frames if index != 3 else frames[:10])))
    store.commit()
    store.export_audio()
    return store


def test_transcripts_use_wall_clock_and_skip_tiny_files(tmp_path):
    t0 = int(datetime(2026, 11, 13, 9, 7, 0).timestamp() * 1000)
    store = _store_with_audio(tmp_path, t0)
    fake = FakeTranscriber()

    added, files = store.transcribe_pending(fake)
    assert len(fake.calls) == 2  # the 0.2 s file is too short to transcribe
    assert added == 4
    assert [f.name for f in files] == ["2026-11-13.md"]
    assert files[0].read_text() == (
        "# 2026-11-13\n\n"
        "- **09:07:00** first thing said\n"
        "- **09:07:01** second thing\n"
        "- **09:08:00** first thing said\n"
        "- **09:08:01** second thing\n"
    )
    rows = store.db.execute("SELECT start_ms, end_ms FROM utterances ORDER BY start_ms").fetchall()
    assert rows[0] == (t0, t0 + 900)

    # A second run has nothing to do and does not duplicate lines.
    assert store.transcribe_pending(fake) == (0, [])
    assert len(fake.calls) == 2
    store.close()
