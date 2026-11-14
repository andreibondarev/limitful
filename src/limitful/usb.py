"""Readings from the pendant's USB shell.

Plugged in, the pendant shows up as a serial port carrying its firmware log and
a developer shell. That shell can erase the device, so this module only ever
types the three read-only commands below. Nothing here changes the pendant.
"""

from __future__ import annotations

import re
import threading
import time

VENDOR_ID, PRODUCT_ID = 0x2FE3, 0x0110
BAUD = 115200

# The only lines this module will type, with what to look for in the reply.
READS = {
    "dev ver": re.compile(r"APP-VERSION:\s*(?P<firmware>\S+)(?:[ \t]+(?P<build>\S+))?"),
    "config get led_brightness": re.compile(r"led_brightness:\s*(?P<brightness>\d+)"),
    "battery info": re.compile(
        r"(?P<millivolts>-?\d+) mV\s+(?P<milliamps>-?\d+) mA\s+(?P<celsius>-?\d+) C\s+"
        r"(?P<battery>\d+)%\s+(?P<mah>\d+) mAh"),
}
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_lock = threading.Lock()


class UsbError(Exception):
    pass


def find_port() -> str | None:
    """The serial port of a plugged-in pendant, or None."""
    from serial.tools import list_ports

    for port in list_ports.comports():
        if port.vid == VENDOR_ID and port.pid == PRODUCT_ID:
            return port.device
    return None


def _open(device: str):
    import serial

    return serial.Serial(device, BAUD, timeout=0.1, write_timeout=1)


def _ask(link, command: str, wanted: re.Pattern, timeout: float) -> dict:
    if command not in READS:
        raise UsbError(f"refusing to type {command!r}: not a read-only command")
    link.write(command.encode() + b"\r")
    heard, deadline = "", time.monotonic() + timeout
    while time.monotonic() < deadline:
        heard += _ANSI.sub("", link.read(4096).decode("utf-8", "replace"))
        # The pendant echoes the command; the answer comes after the echo.
        found = wanted.search(heard.split(command, 1)[-1])
        if found:
            return found.groupdict()
    return {}


def read(device: str | None = None, timeout: float = 1.5, opener=_open) -> dict | None:
    """Firmware version, light brightness and battery detail, or None if not plugged in."""
    device = device or find_port()
    if device is None:
        return None
    if not _lock.acquire(timeout=5):
        raise UsbError("already reading the pendant over USB")
    try:
        try:
            link = opener(device)
        except OSError as err:
            raise UsbError(f"could not open {device}: {err}") from None
        try:
            # On connecting, the pendant replays its log. Let it finish before asking.
            quiet_since, deadline = time.monotonic(), time.monotonic() + 3
            while time.monotonic() < deadline and time.monotonic() - quiet_since < 0.3:
                if link.read(4096):
                    quiet_since = time.monotonic()
            got: dict = {}
            for command, wanted in READS.items():
                got.update(_ask(link, command, wanted, timeout))
        except OSError as err:
            raise UsbError(f"lost the pendant on {device}: {err}") from None
        finally:
            link.close()
    finally:
        _lock.release()
    if not got:
        raise UsbError("the pendant did not answer over USB")
    numbers = ("brightness", "millivolts", "milliamps", "celsius", "battery", "mah")
    return {key: int(value) if key in numbers else value for key, value in got.items() if value is not None}
