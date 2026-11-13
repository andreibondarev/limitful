"""Minimal Ogg Opus writer (RFC 7845), so raw Opus packets become playable files."""

from __future__ import annotations

import struct
from typing import BinaryIO, Iterable

_PACKETS_PER_PAGE = 50  # ~1 s of 20 ms frames


def _build_crc_table() -> list[int]:
    table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
        table.append(r & 0xFFFFFFFF)
    return table


_CRC_TABLE = _build_crc_table()


def ogg_crc(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ _CRC_TABLE[(crc >> 24) ^ byte]
    return crc


def packet_samples(packet: bytes) -> int:
    """Duration of an Opus packet in 48 kHz samples, read from its TOC byte."""
    if not packet:
        return 0
    toc = packet[0]
    config = toc >> 3
    if config < 12:  # SILK: 10, 20, 40, 60 ms
        frame = (480, 960, 1920, 2880)[config & 3]
    elif config < 16:  # hybrid: 10, 20 ms
        frame = (480, 960)[config & 1]
    else:  # CELT: 2.5, 5, 10, 20 ms
        frame = (120, 240, 480, 960)[config & 3]
    code = toc & 3
    if code == 0:
        count = 1
    elif code in (1, 2):
        count = 2
    else:
        count = packet[1] & 0x3F if len(packet) > 1 else 0
    return frame * count


def _page(serial: int, seqno: int, granule: int, flags: int, packets: list[bytes]) -> bytes:
    lacing = bytearray()
    for packet in packets:
        full, rest = divmod(len(packet), 255)
        lacing += b"\xff" * full + bytes([rest])
    if len(lacing) > 255:
        raise ValueError("too many segments for one Ogg page")
    header = struct.pack(
        "<4sBBqIIIB", b"OggS", 0, flags, granule, serial, seqno, 0, len(lacing)
    ) + bytes(lacing)
    body = b"".join(packets)
    crc = ogg_crc(header + body)
    return header[:22] + struct.pack("<I", crc) + header[26:] + body


def write_ogg_opus(
    out: BinaryIO,
    packets: Iterable[bytes],
    *,
    input_sample_rate: int = 16000,
    channels: int = 1,
    serial: int = 0x50454E44,
) -> int:
    """Write packets as an Ogg Opus stream. Returns the duration in milliseconds."""
    head = struct.pack("<8sBBHIhB", b"OpusHead", 1, channels, 0, input_sample_rate, 0, 0)
    vendor = b"limitful"
    tags = b"OpusTags" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)
    out.write(_page(serial, 0, 0, 0x02, [head]))  # beginning of stream
    out.write(_page(serial, 1, 0, 0x00, [tags]))

    seqno = 2
    granule = 0
    batch: list[bytes] = []
    pending: bytes | None = None  # hold one page back so the last gets the end flag

    def flush(final: bool) -> None:
        nonlocal seqno, pending, batch
        if pending is not None:
            out.write(pending)
            pending = None
        if batch:
            page = _page(serial, seqno, granule, 0x04 if final else 0x00, batch)
            seqno += 1
            batch = []
            if final:
                out.write(page)
            else:
                pending = page

    for packet in packets:
        if not packet:
            continue
        batch.append(packet)
        granule += packet_samples(packet)
        if len(batch) >= _PACKETS_PER_PAGE:
            flush(final=False)

    if batch:
        flush(final=True)
    elif pending is not None:
        # Re-stamp the held-back page as the end of the stream.
        final_page = bytearray(pending)
        final_page[5] = 0x04
        final_page[22:26] = b"\x00\x00\x00\x00"
        final_page[22:26] = struct.pack("<I", ogg_crc(bytes(final_page)))
        out.write(bytes(final_page))
    return granule // 48
