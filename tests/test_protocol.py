from pendant_sync import protocol as p

from wire import (ble_packets, device_status, flash_page, opus_frame,
                  pendant_message, storage_buffer)


def test_varint_round_trip():
    for value in (0, 1, 127, 128, 300, 1_763_000_000_000, 2**63):
        encoded = p.encode_varint(value)
        assert p.decode_varint(encoded, 0) == (value, len(encoded))


def test_set_mode_bytes_match_reference_layout():
    packet = p.CommandEncoder().set_mode(download=True, realtime=False)
    # wrapper: 1=index 0, 2=seq 0, 3=frags 1, 4=payload
    # payload: msg 8 {1=1, 2=0} + request trailer msg 30 {1=request id 1, 2=0}
    assert packet.hex() == "0800100018" "01" "220d" "420408011000" "f20104" "08011000"


def test_encoder_counters_advance():
    enc = p.CommandEncoder()
    first = p.parse_ble_packet(enc.get_status())
    second = p.parse_ble_packet(enc.acknowledge(41))
    assert (first.index, second.index) == (0, 1)
    assert first.payload.hex() == "aa0100" "f20104" "08011000"  # msg 21 empty, request 1
    assert second.payload.hex() == "3a020829" "f20104" "08021000"  # msg 7 {1=41}, request 2


def test_set_time_carries_timestamp():
    ts = 1_763_000_000_123
    payload = p.parse_ble_packet(p.CommandEncoder().set_time(ts)).payload
    assert payload[0] == 0x32  # msg 6
    assert p.decode_varint(payload, 3) [0] == ts


def test_fragmented_payload_reassembles_into_pages():
    frames_a = [opus_frame(i) for i in range(5)]
    frames_b = [opus_frame(i, size=60, toc=0x78) for i in range(3)]
    payload = pendant_message(
        storage_buffer(100, flash_page(1_763_000_000_000, frames_a)),
        storage_buffer(101, flash_page(1_763_000_000_100, frames_b)),
    )
    reassembler = p.Reassembler()
    packets = ble_packets(9, payload, fragments=4)
    assert len(packets) == 4
    results = [reassembler.add(p.parse_ble_packet(raw)) for raw in reversed(packets)]
    assert results[:3] == [None, None, None]
    assert results[3] == payload

    pages = p.parse_pendant_message(results[3])
    assert [(pg.index, pg.session) for pg in pages] == [(100, 7), (101, 7)]
    assert pages[0].timestamp_ms == 1_763_000_000_000
    assert pages[0].opus_frames() == frames_a
    assert pages[1].opus_frames() == frames_b


def test_page_without_audio_is_kept_with_no_frames():
    page = p.parse_pendant_message(pendant_message(storage_buffer(5, b"\x08\x01\x10\x02")))[0]
    assert page.index == 5
    assert page.opus_frames() == []


def test_truncated_packet_is_rejected():
    raw = ble_packets(1, b"x" * 50)[0]
    assert p.parse_ble_packet(raw[:-10]) is None
    assert p.parse_ble_packet(b"") is None


def test_garbage_does_not_crash_parsers():
    for seed in range(200):
        blob = bytes((seed * 31 + i * 17) % 256 for i in range(seed + 1))
        p.parse_ble_packet(blob)
        p.parse_pendant_message(blob)
        p.extract_opus_frames(blob)
        p.parse_device_status(blob)


def test_device_status():
    state = p.parse_device_status(device_status(1000, 5000))
    assert state == p.StorageState(1000, 5000, 7, 100_000, 200_000)
    assert state.page_count == 4001
    # Also found when delivered inside a BLE wrapper.
    assert p.parse_device_status(ble_packets(3, device_status(1000, 5000))[0]) == state
    assert p.parse_device_status(b"\x00" * 30) is None
