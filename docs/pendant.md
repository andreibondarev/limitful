# The pendant

## Buttons and lights

Summarised from Limitless's help centre, which is due to go offline with the
service. The pendant has one button, on its side, and one light.

- **Power on or off:** hold the button for two seconds.
- **Mark a moment:** one quick press.
- **Factory reset and pairing mode:** press and release, then immediately press
  and hold. A purple light appears; keep holding until it goes out, then
  release. A blue light means it is ready to pair. This deletes any recordings
  not yet synced.
- **Solid red light (recovery mode):** hold the button for ten seconds or more
  until the light goes out.
- **Charging:** any standard USB-C charger, but not a Power Delivery (PD)
  charger. It keeps recording while it charges.

Light colours: blue is ready to pair, purple is a factory reset in progress,
solid red is recovery mode, blinking or breathing red is an error. White,
orange and green indicate recording and charging states.

## Moving a pendant to another computer without erasing it

Pairing mode is a factory reset, but it is only needed because the pendant
refuses new computers while it remembers an old one. With a USB cable it can
be told to forget, and then it pairs like new and keeps its audio. This was
done on a real pendant (firmware 1.1.20), and the 1,400 pages stored on it
survived:

1. Plug the pendant in with its USB cable. In the setup guide choose
   **Keep its recordings** at the pairing step, or open Settings, Pendant,
   Pairing and click **Pair without erasing**. Click **Forget the old
   computer**: Limitful types `ble unpair` into the pendant's USB shell and
   waits for it to confirm. The pendant forgets every computer and phone.
2. On a computer that was paired with it before, remove Pendant under
   Bluetooth in System Settings, then turn Bluetooth off and on. Without this
   the computer keeps trying its old key and cannot connect at all. A computer
   that has never seen the pendant should not need this step; that case was
   not tried.
3. Click **Pair** and accept the connection request. No button press on the
   pendant is needed.

The steps were done by hand on the real pendant. The buttons that now do them
have only been run against a simulated one.

## Hardware notes

Observed on one pendant; treat as provisional.

- Firmware is built on Zephyr. Over USB it appears as "Pendant" by "ZEPHYR"
  (vendor 0x2fe3, product 0x0110) with a serial port.
- Bluetooth services: battery, the Limitless data service, and Zephyr's device
  management (SMP) service, which is normally used for firmware updates.
- Commands are refused with "Insufficient Encryption" until the computer is
  paired. The pendant only accepts a new computer once it has forgotten the old one: by
  pairing mode (a factory reset) or by `ble unpair` over USB.
- Audio is mono Opus in 20 ms frames. A flash page is about 4 KB and holds
  roughly 1.45 s; the pendant reports 95,232 pages, so about 38 hours.
- The pendant stops recording during silence, so audio arrives as short bursts.

The USB serial port (115200 baud) carries the firmware's log and a Zephyr
shell prompt (`uart:~$`). Listening to it, without typing anything, showed:

- The chip is a Nordic nRF53, running nRF Connect SDK with the MCUboot
  bootloader. Firmware version 1.1.20, about 512 KB, with a primary and a
  secondary image slot, which is how MCUboot installs updates.
- Start-up initialises, in order: usb, led, watchdog, button, poll, storage,
  pendant_settings, device_state, battery, imu, crypto, wifi, comm, bluetooth.
  So there is a motion sensor, and at least a Wi-Fi module in the firmware.
- Storage reports four flash chip positions, two of them working. The other
  two fail at start-up; whether they are fitted on this model is not known.
- A crypto module holds a device key, a storage key and a server public key.
  After a factory reset the last two are missing.
- The firmware logs its own state as it changes: "Recording state set to
  RECORDING" / "NOT_RECORDING", storage sessions starting, and the light's
  colour ("Recording while charging, LED alternating colors").
- Bluetooth also offers the Nordic UART Service.

The shell is a developer console. `help` lists its commands and `<command> -h`
lists subcommands. Only read-only commands and `ble unpair` have been run.
What they showed:

- `config list`: settings include `led_brightness`, `vad_threshold_ms` (5000),
  `allow_recording_on_usb`, `sync_mode`, microphone and beamforming debug
  options, and an unset server upload (`server_name`, `port_num`,
  `ingest_token`, `upload_method: STREAM`, `upload_period_sec: 300`). There is
  no setting that switches recording off.
- `device list`: a battery gauge (bq27427), a motion sensor (lsm6dsm), NAND
  flash, and no Wi-Fi device. The firmware has a Wi-Fi module, but this
  pendant shows no radio for it.
- `storage status`, `battery info`, `dev ver`, `config get led_brightness`
  and `time synced` print the
  readings their names suggest, matching what Bluetooth reports.

Commands that exist but have not been run: `button push [short|long|double-short]`
(simulates the button, so a long push may switch the pendant off),
`dev shipping_mode`, `dev reset`, `config set`, `ble set_name`,
`date set`, `imu enable/disable`, `settings write/delete` and
`mcuboot request_upgrade`. Several others erase storage or flash (`flash
erase`, `ftl clear`, `storage clear`, `storage full-wipe`, `config reset`,
`mcuboot erase`); do not run them unless you mean to.
