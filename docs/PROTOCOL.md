# LinkerHand O6 CAN protocol (from the public linkerhand-ros-sdk / linkerbot-python-sdk)

## Bus settings

- Bitrate: **1 Mbit/s**
- Format: CAN 2.0 standard, **11-bit identifier**
- Arbitration ID: **0x28** (left hand) / **0x27** (right hand)
- The hand answers on the same ID it receives commands on.

## Frame format

`data[0]` is the command byte; `data[1:]` is the payload (6 values for motion).

## Commands

| cmd | direction | payload | description |
|---|---|---|---|
| 0x01 | both | 6 bytes | joint positions; empty payload = query current positions |
| 0x02 | both | 6 bytes | torque limits (grip strength); empty = query |
| 0x05 | both | 6 bytes | speed |
| 0x20 | query | — | normal force sensors |
| 0x21 | query | — | tangential force |
| 0x22 | query | — | tangential force direction |
| 0x23 | query | — | approach increment |
| 0x33 | query | — | motor temperatures (°C) |
| 0x35 | query | — | fault codes (all zero = healthy) |
| 0x36 | query | — | motor currents |
| 0x64 / 0xC2 | query | — | firmware version |
| 0xC0 | query | — | serial number (4 indexed chunks, index in payload[0]) |

## Joint order and scale

Joints: `[thumb_flex, thumb_abd, index, middle, ring, pinky]`.

User-facing values are **0-100 percent** (higher = finger extends), converted to
the hardware **0-255 raw** scale with `raw = round(pct * 255 / 100)`.

Reference anchor poses (raw, left hand):

| pose | raw values |
|---|---|
| open | 255, 179, 255, 255, 255, 255 |
| fist | 67, 151, 0, 0, 0, 0 |

## PCAN-USB adapter wire protocol

- Command pipe: bulk EP 0x01 (out) / 0x81 (in); 16-byte packets
  `[func, num, args...14]`
- Message pipe: bulk EP 0x02 (out) / 0x82 (in); 64-byte packets
- Init: GET serial (func 6) -> SJA1000 init mode (func 9, arg[1]=1) ->
  bitrate (func 1: args = [BTR1, BTR0]) -> bus on (func 3, num 2, arg[0]=1)
- Reference: Linux kernel `drivers/net/can/usb/peak_usb/pcan_usb.c`
