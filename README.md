# LinkerBot O6 SDK

SDK for the **LinkerBot / LinkerHand O6 dexterous hand** over CAN, with zero
Python dependencies and **no vendor kernel drivers needed** — it drives
PCAN-USB-compatible adapters (e.g. the XCAN-USB) directly from userspace via
libusb (ctypes). Works on macOS and Linux; see notes for Windows.

## Features

- `probe` — serial number, fault codes, temperatures, joint positions
- `move` — set joint positions (percent 0-100 or raw 0-255), speed, torque
- `grasp` — two-stage ball grasp (fingers close, then thumb wraps) + release
- `presets` — open, fist, thumbs up, V-sign, point, middle finger, rock on
- `web` — browser control panel: live status, sliders, presets, grasp card,
  and **camera hand tracking** (MediaPipe in-browser, one-hand gating)

## Requirements

- Python 3.9+
- libusb 1.0 (`brew install libusb` on macOS, `libusb-1.0-0-dev` on Debian/Ubuntu)
- A PCAN-USB compatible adapter (VID 0x0C72 / PID 0x000C) — e.g. XCAN-USB
- The LinkerHand O6 wired to the adapter's CAN port (1 Mbit/s, standard 11-bit)

## Quick start

```bash
git clone <this-repo> && cd linkerbot-o6-sdk
./setup.sh                 # checks python + libusb, then runs a self-test
python3 -m linkerbot_o6.cli probe
```

No `pip install` required — run straight from source. For a real install:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install .
linkerbot-o6 probe
```

## CLI usage

```bash
python3 -m linkerbot_o6.cli probe                        # health check
python3 -m linkerbot_o6.cli pos                          # read joint positions
python3 -m linkerbot_o6.cli move --pos 80,80,80,80,80,80 --speed 60
python3 -m linkerbot_o6.cli move --preset fist           # presets: open fist thumbs_up v_sign point middle rock_on
python3 -m linkerbot_o6.cli move --raw 67,151,0,0,0,0    # raw 0-255 scale
python3 -m linkerbot_o6.cli grasp --ball 6 --strength 150  # grasp a tennis ball
python3 -m linkerbot_o6.cli grasp --release              # let go
```

Angles are **0-100 percent** (higher = finger extends), converted to the
hardware 0-255 scale. Joint order: `thumb_flex, thumb_abd, index, middle,
ring, pinky`.

## Web panel

```bash
python3 -m linkerbot_o6.web --port 8080
# open http://127.0.0.1:8080
```

- Live status (serial, positions, faults, temps)
- Joint sliders + speed + Apply / Emergency stop
- Preset buttons (Open ✋ Fist ✊ Thumbs up 👍 V-sign ✌️ Point ☝️ Middle 🖕 Rock on 🤘)
- Grasp & hold card (ball size + grip strength)
- **Camera hand control**: Start camera → show exactly ONE hand → enable.
  Fingers follow yours; two hands or no hand = no motion.

## Python API

```python
from linkerbot_o6.hand import LinkerHand

hand = LinkerHand(side="left")        # CAN ID 0x28 (left) / 0x27 (right)
print(hand.get_serial())              # e.g. LHO6-04-079-L-Z-1-D
print(hand.get_positions())           # raw 0-255 list
print(hand.get_faults())              # all-zero = healthy
print(hand.get_temps())               # degrees C
hand.move_raw([255,179,255,255,255,255], speed=60)   # open
hand.set_torque([150]*6)              # grip strength
hand.close()
```

See `examples/basic.py` for a complete script.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `claim_interface failed: LIBUSB_ERROR_ACCESS` | Another process holds the adapter (e.g. the web server). Stop it first, or check `lsof /dev/bus/usb`. |
| `PCAN-USB (0x0c72:0x000c) not found` | Adapter not plugged in / not enumerated (`ioreg -p IOUSB` or `lsusb`). |
| Hand answers nothing (`Serial: n/a`) | Hand is unpowered, cable unseated, or the hand is in a latched fault. **Power-cycle the hand** (unplug power + CAN, 5 s, replug), reseat the DB9 (pins 2 = CAN-L, 7 = CAN-H), then re-run `probe`. |
| Endpoint stall (`LIBUSB_ERROR_PIPE`) | Auto-recovered by the driver (clear halt + retry). If persistent, unplug/replug the adapter's USB. |
| Adapter dead after heavy use | USB-level reset is built in (`CanAdapter.reset_device()`); if that fails, physically replug. |

## Protocol reference

LinkerHand O6: **1 Mbit/s, CAN 2.0 standard (11-bit ID)**, arbitration ID
`0x28` (left) / `0x27` (right), `data[0]` = command byte:

| cmd | function |
|---|---|
| 0x01 | joint positions (6 bytes) — empty payload = query |
| 0x02 | torque limits (6 bytes) |
| 0x05 | speed (6 bytes) |
| 0x20-0x23 | force sensor queries |
| 0x33 | motor temperatures |
| 0x35 | fault codes |
| 0x36 | motor currents |
| 0x64 / 0xC2 | firmware version |
| 0xC0 | serial number (4 indexed chunks) |

PCAN-USB wire protocol reference: Linux kernel
`drivers/net/can/usb/peak_usb/pcan_usb.c`.

## License

MIT. Not affiliated with Linker-Bot / LinkerHand — the CAN protocol is
implemented from the public linkerhand SDKs.
