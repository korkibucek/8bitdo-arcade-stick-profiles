# 8BitDo Arcade Stick config protocol (reverse-engineered)

How the Ultimate Software reads and writes the Arcade Stick's stored mapping over
USB HID. Reverse-engineered from `8BitDoAdvance.dll` (a debug build, symbols intact)
and cross-checked against [TheJayMann/8bitdo-spec](https://github.com/TheJayMann/8bitdo-spec)
(Pro2 family). Everything here is validated against a real Arcade Stick (VID `0x2DC8`,
PID `0x901A`) by [`stickctl.py`](../stickctl/stickctl.py).

> The device shares the Pro2 read/write/CRC/slot functions but with **PID-specific
> variations**. The values below are the Arcade-Stick-specific ones and differ from the
> published Pro2 notes (different command bytes and a different, smaller config layout).

## Transport

- Interface: `USB\VID_2DC8&PID_901A`, HID usage page `0x01` usage `0x05` (Game Pad).
- All requests are a single 64-byte HID write. All responses are a 64-byte HID read.
- Must be connected in **X-input mode over USB** (mode switch on `X`). The config
  interface is served on the same HID endpoint as gamepad input.

## Request frame (host → stick)

```
byte 0      0x81            report id / framing
byte 1      size + 17       length of the meaningful payload
byte 2      0x04            channel constant (echoed in response[2])
bytes 3..18 inner header (16 bytes, see below)
bytes 19..  up to 45 data bytes (write only; ignored on read)
pad to 64 with 0x00
```

### Inner 16-byte header

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0x00 | 1 | command | `0x0C` read · `0x0B` write · `0x06` commit |
| 0x08 | 1 | chunk size | ≤ `0x2D` (45) |
| 0x0A | 2 | total size | `0x0234` = 564, little-endian |
| 0x0C | 2 | offset | little-endian |

(This layout is Arcade-Stick specific — the Pro2 uses a 4-byte command + 2-byte
size + 2-byte CRC + 4-byte total + 4-byte offset. The Arcade Stick uses a `0`
checksum, so no CRC field is sent.)

## Response frame (stick → host)

```
byte 0      0x02            output-endpoint constant
byte 1      0x04
byte 2      0x04            echoes request channel
bytes 6..10 command (u32 LE) echoes the request command (0x0C / 0x0B / 0x06)
byte 10     data length     bytes of config data in this packet
bytes 18..  data
```

The library matches a response by checking `resp[0]==0x02 && resp[2]==0x04 &&
u32(resp[6])==command`, then copies `resp[10]` bytes starting at `resp[18]`.

## Read sequence

Loop `offset` from 0 to 564 in 45-byte steps; send a `0x0C` frame, read the ack,
append `resp[10]` bytes. Retries up to 8× per chunk (device occasionally NAKs with a
zero-data ack until it's ready).

## Write sequence

1. Loop `offset` 0→564 in 45-byte steps; send a `0x0B` frame carrying the config
   bytes for that slice, read the ack. Retries up to 30× per chunk.
2. **Commit**: send one `0x06` frame with sub-command `0x15` at inner byte 2 and no
   data (`81 11 04 06 00 15 00 …`). The stick echoes command `0x06` when the new
   config is persisted to flash. Without the commit the writes are discarded.

`stickctl apply` always reads the config back after committing and diffs it against
what it wrote.

## Config binary (564 bytes)

The Arcade Stick stores a single active configuration (not the Pro2's three slots).

```
0x000  4    header / CRC16 (observed be 65 00 01)
0x004  ...  block A (280 bytes)  <- one gamepad-mode config
0x11C  ...  block B (280 bytes)  <- the other gamepad-mode config
```

Each 280-byte block is three sub-sections, each prefixed with the 4-byte enable flag
`0x20191212` (bytes `12 12 19 20`):

| Sub-section | Size | Contents |
|---|---|---|
| name    | 36  | 4-byte flag + 32-byte UTF-16LE profile name (e.g. `PS3 (1)`) |
| params  | 168 | rumble / stick deadzones / trigger ranges / special-feature bits / P1-P2 |
| buttons | 76  | 4-byte flag + **18 × u32** function bitsets |

Block A holds the X-input mapping (identity for our profiles); block B holds the
D-input mapping (where the PS3 remap lives). `stickctl decode` prints both.

### Button-map function values

Each of the 18 entries (physical order: `A B X Y L R L2 R2 L3 R3 Select Start Share
Home Up Down Left Right`) is a u32 with exactly one bit set:

| Bit | Fn | Bit | Fn | Bit | Fn | Bit | Fn |
|--|--|--|--|--|--|--|--|
| 0 | Start | 4 | X | 10 | L1 | 16 | Menu |
| 1 | L3 | 5 | Y | 11 | R1 | 17 | Home |
| 2 | R3 | 6 | Right | 12 | B | 23 | Turbo |
| 3 | Select | 7 | Left | 13 | A | 25 | P1 |
| | | 8 | Down | 14 | L2 | 26 | P2 |
| | | 9 | Up | 15 | R2 | | |

A value of `0` disables the button. Example — the live PS3 profile's D-input block
decodes to `A→B, B→X, X→A, Y→Y, L2→Select, R2→Start, Select→L3, Start→R3`, matching
[`profiles/PS3.ini`](../profiles/PS3.ini) exactly.

## Function map in the DLL

| Export | Meaning |
|---|---|
| `_readArcadeStick@4` | read loop (command `0x0C`, total `0x234`) |
| `_writeArcadeStick@564` | write loop + commit (command `0x0B`, then `0x06`/`0x15`) |
| `hid_write` / `hid_read_timeout` | the raw transport (hidapi) |

The `@564` decoration on the write export is itself the confirmation that the config
image is 564 bytes.
