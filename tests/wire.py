"""Test helpers that build pendant-side wire data (the direction the client only parses)."""

from __future__ import annotations

from pendant_sync.protocol import encode_varint


def ld(tag: int, body: bytes) -> bytes:
    """A length-delimited field with a single-byte tag."""
    return bytes([tag]) + encode_varint(len(body)) + body


def vi(tag: int, value: int) -> bytes:
    return bytes([tag]) + encode_varint(value)


def opus_frame(seed: int, size: int = 40, toc: int = 0xB8) -> bytes:
    return bytes([toc]) + bytes((seed + i) % 251 for i in range(size - 1))


def flash_page(timestamp_ms: int, frames: list[bytes]) -> bytes:
    audio = b"".join(ld(0x22, f) for f in frames)
    return vi(0x08, timestamp_ms) + ld(0x1A, vi(0x08, 0) + ld(0x12, audio))


def storage_buffer(index: int, page: bytes, session: int = 7, seq: int = 0) -> bytes:
    return vi(0x10, session) + vi(0x20, seq) + vi(0x28, index) + ld(0x32, page)


def pendant_message(*buffers: bytes) -> bytes:
    return b"".join(ld(0x12, b) for b in buffers)


def ble_packets(index: int, payload: bytes, fragments: int = 1) -> list[bytes]:
    size = -(-len(payload) // fragments)
    chunks = [payload[i : i + size] for i in range(0, len(payload), size)] or [b""]
    return [
        vi(0x08, index) + vi(0x10, seq) + vi(0x18, len(chunks)) + ld(0x22, chunk)
        for seq, chunk in enumerate(chunks)
    ]


def device_status(oldest: int, newest: int, session: int = 7,
                  free: int = 100_000, total: int = 200_000) -> bytes:
    storage = (vi(0x08, oldest) + vi(0x10, newest) + vi(0x18, session)
               + vi(0x20, free) + vi(0x28, total))
    return ld(0x22, ld(0x2A, ld(0x2A, storage)))
