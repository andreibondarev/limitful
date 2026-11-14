"""The USB shell reader, against a stand-in serial port."""

import pytest

from limitful import usb

REPLIES = {
    "dev ver": "APP-VERSION: 1.1.20 b312ca1efaaa\r\n",
    "config get led_brightness": "led_brightness: 40\r\n",
    "battery info": "3941 mV  78 mA  31 C  52%  208 mAh\r\n",
}


class FakePort:
    """Echoes what is typed, answers known commands, and chatters log lines like the real one."""

    def __init__(self, replies=REPLIES):
        self.replies, self.typed, self.closed = replies, [], False
        self.waiting = b"\x1b[1;32muart:~$ \x1b[m[00:00:01.2] <inf> main: VER: 0.0.1 old\r\n"

    def write(self, data):
        command = data.decode().strip()
        self.typed.append(command)
        self.waiting += (f"{command}\r\n{self.replies.get(command, '')}\x1b[1;32muart:~$ \x1b[m"
                         "[09:16:49.2] <inf> storage: Session num:1605 started with err:0\r\n").encode()

    def read(self, _size):
        out, self.waiting = self.waiting, b""
        return out

    def close(self):
        self.closed = True


def test_reads_firmware_light_and_battery():
    port = FakePort()
    got = usb.read("/dev/fake", timeout=0.3, opener=lambda device: port)
    assert got == {"firmware": "1.1.20", "build": "b312ca1efaaa", "brightness": 40,
                   "millivolts": 3941, "milliamps": 78, "celsius": 31, "battery": 52, "mah": 208}
    assert port.typed == list(usb.READS) and port.closed  # typed nothing else


def test_only_read_only_commands_can_be_typed():
    port = FakePort()
    with pytest.raises(usb.UsbError, match="not a read-only command"):
        usb._ask(port, "flash erase", usb.READS["dev ver"], 0.1)
    assert port.typed == []
    assert not any(word in command for command in usb.READS
                   for word in ("set", "erase", "reset", "clear", "write", "push", "unpair", "wipe"))


def test_forget_types_one_line_and_waits_for_the_pendant_to_confirm(monkeypatch):
    port = FakePort({"ble unpair": "[10:33:54.8] <inf> bluetooth: Unpairing BLE\r\n"
                                   "[10:33:55.0] <inf> bluetooth: Unpaired BLE devices\r\n"})
    assert usb.forget("/dev/fake", timeout=0.3, opener=lambda device: port) is True
    assert port.typed == ["ble unpair"] and port.closed

    silent = FakePort({})
    with pytest.raises(usb.UsbError, match="did not confirm"):
        usb.forget("/dev/fake", timeout=0.2, opener=lambda device: silent)
    assert silent.typed == ["ble unpair"] and silent.closed

    monkeypatch.setattr(usb, "find_port", lambda: None)
    assert usb.forget() is False


def test_partial_and_missing_answers():
    part = usb.read("/dev/fake", timeout=0.2, opener=lambda d: FakePort({"dev ver": "APP-VERSION: 2.0.0\r\n"}))
    assert part == {"firmware": "2.0.0"}
    with pytest.raises(usb.UsbError, match="did not answer"):
        usb.read("/dev/fake", timeout=0.2, opener=lambda d: FakePort({}))


def test_not_plugged_in_or_cannot_open(monkeypatch):
    monkeypatch.setattr(usb, "find_port", lambda: None)
    assert usb.read() is None

    def refuse(device):
        raise OSError("Resource busy")
    with pytest.raises(usb.UsbError, match="could not open /dev/fake: Resource busy"):
        usb.read("/dev/fake", opener=refuse)
