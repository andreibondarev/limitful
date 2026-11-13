import io
import shutil
import struct
import subprocess

import pytest

from pendant_sync.ogg import ogg_crc, packet_samples, write_ogg_opus
from pendant_sync.protocol import VALID_OPUS_TOC, FlashPage
from pendant_sync.store import Store

from wire import flash_page, opus_frame


def read_ogg_packets(data: bytes) -> list[bytes]:
    """Tiny Ogg demuxer; also verifies every page checksum."""
    packets, partial, pos = [], b"", 0
    while pos < len(data):
        assert data[pos : pos + 4] == b"OggS"
        nsegs = data[pos + 26]
        lacing = data[pos + 27 : pos + 27 + nsegs]
        body_start = pos + 27 + nsegs
        end = body_start + sum(lacing)
        page = bytearray(data[pos:end])
        (crc,) = struct.unpack_from("<I", page, 22)
        page[22:26] = b"\x00" * 4
        assert ogg_crc(bytes(page)) == crc
        offset = body_start
        for seg in lacing:
            partial += data[offset : offset + seg]
            offset += seg
            if seg < 255:
                packets.append(partial)
                partial = b""
        pos = end
    return packets


def test_packet_samples():
    assert packet_samples(bytes([0xB8, 0])) == 960  # CELT 20 ms
    assert packet_samples(bytes([0xB0, 0])) == 480  # CELT 10 ms
    assert packet_samples(bytes([0x78, 0])) == 960  # hybrid 20 ms
    assert packet_samples(bytes([0xB9, 0])) == 1920  # two frames
    assert packet_samples(bytes([0xBB, 3])) == 2880  # code 3, three frames


def test_ogg_round_trip_and_duration():
    frames = [opus_frame(i, size=30 + i % 7) for i in range(173)]
    buf = io.BytesIO()
    duration_ms = write_ogg_opus(buf, frames)
    assert duration_ms == 173 * 20
    packets = read_ogg_packets(buf.getvalue())
    assert packets[0].startswith(b"OpusHead")
    assert packets[1].startswith(b"OpusTags")
    assert packets[2:] == frames
    assert buf.getvalue()[-1:] != b""  # stream ends on a page flagged end-of-stream
    last = buf.getvalue().rfind(b"OggS")
    assert buf.getvalue()[last + 5] & 0x04


def test_ogg_exact_page_multiple_still_ends_stream():
    buf = io.BytesIO()
    write_ogg_opus(buf, [opus_frame(i) for i in range(100)])  # exactly two full pages
    data = buf.getvalue()
    assert read_ogg_packets(data)[2:] == [opus_frame(i) for i in range(100)]
    assert data[data.rfind(b"OggS") + 5] & 0x04


def _page(index, ts, frames, session=7, uptime=None):
    return FlashPage(index=index, session=session, seq=0,
                     data=flash_page(ts, frames, uptime_ms=uptime))


def test_store_dedupes_and_splits_segments_at_gaps(tmp_path):
    store = Store(tmp_path)
    t0 = 1_763_000_000_000
    frames = [opus_frame(i) for i in range(50)]  # 1 s per page
    assert store.add_page(_page(10, t0, frames))
    assert store.add_page(_page(11, t0 + 1000, frames, session=8))  # session change alone
    assert not store.add_page(_page(11, t0 + 1000, frames, session=8))  # re-sent page
    assert store.add_page(_page(12, t0 + 60_000, frames))  # a minute later
    assert store.add_page(_page(13, t0 + 61_000, []))  # diagnostic page, no audio
    store.commit()
    assert store.page_count() == 4

    segments = store.export_audio()
    assert [s.duration_ms for s in segments] == [2000, 1000]
    assert [s.start_ms for s in segments] == [t0, t0 + 60_000]
    assert all(s.path.exists() for s in segments)
    assert store.export_audio() == []  # nothing new to export
    store.close()


def test_reused_index_after_pendant_reset_is_not_treated_as_duplicate(tmp_path):
    store = Store(tmp_path)
    t0 = 1_763_000_000_000
    assert store.add_page(_page(0, t0, [opus_frame(i) for i in range(50)], session=1))
    # The pendant was reset: counters restart, but this is different audio.
    assert store.add_page(_page(0, t0 + 3_600_000, [opus_frame(i + 9) for i in range(50)], session=1))
    store.commit()
    assert [s.start_ms for s in store.export_audio()] == [t0, t0 + 3_600_000]
    store.close()


def test_pages_recorded_before_clock_was_set_get_a_real_time(tmp_path):
    store = Store(tmp_path)
    boot = 1_763_000_000_000
    frames = [opus_frame(i) for i in range(50)]
    # Clock not yet set: the timestamp is just time since boot.
    store.add_page(_page(0, 5_000, frames, uptime=5_000))
    store.add_page(_page(1, 6_000, frames, uptime=6_000))
    # Clock set from here on.
    store.add_page(_page(2, boot + 7_000, frames, uptime=7_000))
    store.commit()
    (segment,) = store.export_audio()
    assert (segment.start_ms, segment.duration_ms) == (boot + 5_000, 3000)
    store.close()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_real_opus_survives_page_round_trip(tmp_path):
    """Real Opus packets -> flash pages -> store -> Ogg file that ffmpeg decodes."""
    src = tmp_path / "src.ogg"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
         "-ar", "16000", "-ac", "1", "-c:a", "libopus", "-application", "lowdelay",
         "-frame_duration", "20", "-b:a", "24k", str(src)],
        check=True,
    )
    real = read_ogg_packets(src.read_bytes())[2:]
    assert len(real) >= 190
    if not all(f[0] in VALID_OPUS_TOC and 10 <= len(f) <= 200 for f in real):
        pytest.skip("this ffmpeg build produced packets outside the pendant's format")

    store = Store(tmp_path / "data")
    t0 = 1_763_000_000_000
    for n in range(0, len(real), 50):
        store.add_page(_page(n // 50, t0 + n * 20, real[n : n + 50]))
    store.commit()
    (segment,) = store.export_audio()
    store.close()

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-show_entries",
         "stream=codec_name,nb_read_frames", "-of", "csv=p=0", str(segment.path)],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert probe == f"opus,{len(real)}"
    decode = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(segment.path), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    assert decode.returncode == 0 and decode.stderr.strip() == ""
