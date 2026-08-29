#!/usr/bin/env python3
"""stickctl - fast profile control for the 8BitDo Arcade Stick (PID 0x901a).

Talks the Ultimate-Software HID config protocol directly, so profiles can be
dumped, inspected, captured and (with an explicit flag) applied without the
official GUI. Protocol reverse-engineered from 8BitDoAdvance.dll + the
TheJayMann/8bitdo-spec Pro2 family notes; see docs/protocol.md.

SAFE commands (read-only): read, decode, capture, list
GUARDED command (writes to the device): apply  -- requires --yes-write

    py stickctl.py read [out.bin]
    py stickctl.py decode [dump.bin]
    py stickctl.py capture <name>          # dump live config to captures/<name>.bin
    py stickctl.py list
    py stickctl.py apply <name> --yes-write # write captures/<name>.bin to the stick
"""
import os
import sys
import time

import hid

VID, PID = 0x2DC8, 0x901A
CONFIG_SIZE = 0x234          # 564 bytes (confirmed: _writeArcadeStick@564)
CHUNK = 0x2D                 # 45 bytes max per transfer
CMD_READ = 0x0C
CMD_WRITE = 0x0B
CMD_COMMIT = 0x06
SUBCMD_COMMIT = 0x15
CHANNEL = 0x04               # request header[2] / response[2]
ENABLE_FLAG = 0x20191212     # little-endian bytes 12 12 19 20

CAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "captures")

# Button-map section: 18 physical inputs, one u32 function bitset each.
PHYSICAL = ["A", "B", "X", "Y", "L", "R", "L2", "R2", "L3", "R3",
            "Select", "Start", "Share", "Home", "Up", "Down", "Left", "Right"]
FUNCTION = {
    0: "Start", 1: "L3", 2: "R3", 3: "Select", 4: "X", 5: "Y", 6: "Right",
    7: "Left", 8: "Down", 9: "Up", 10: "L1", 11: "R1", 12: "B", 13: "A",
    14: "L2", 15: "R2", 16: "Menu", 17: "Home", 18: "BT Connect",
    22: "Screenshot", 23: "Turbo", 24: "Turbo Auto", 25: "P1", 26: "P2",
    27: "Dyn swap",
}
# The two 280-byte config blocks each carry a 76-byte button-map section.
BUTTONMAP_OFFSETS = (0xD0, 0x1E8)


def open_stick():
    devs = hid.enumerate(VID, PID)
    if not devs:
        raise SystemExit("Arcade Stick (2dc8:901a) not found. Plug it in via USB, mode switch on X.")
    h = hid.device()
    h.open_path(devs[0]["path"])
    h.set_nonblocking(False)
    return h


def _frame(cmd, offset, size, data=b""):
    inner = bytearray(16)
    inner[0] = cmd
    inner[8] = size
    inner[0x0A] = CONFIG_SIZE & 0xFF
    inner[0x0B] = CONFIG_SIZE >> 8
    inner[0x0C] = offset & 0xFF
    inner[0x0D] = offset >> 8
    body = bytes([0x81, size + 17, CHANNEL]) + bytes(inner) + data
    return body + b"\x00" * (64 - len(body))


def _await(h, cmd, tries=8, timeout_ms=300):
    for _ in range(tries):
        r = bytes(h.read(64, timeout_ms))
        if len(r) >= 18 and r[0] == 0x02 and r[2] == CHANNEL:
            if int.from_bytes(r[6:10], "little") == cmd:
                return r
    return None


def read_config(h):
    blob = bytearray()
    offset = 0
    while offset < CONFIG_SIZE:
        size = min(CHUNK, CONFIG_SIZE - offset)
        h.write(_frame(CMD_READ, offset, size))
        r = _await(h, CMD_READ)
        if r is None:
            raise IOError(f"read: no response at offset {offset}")
        dlen = r[10]
        if dlen == 0:
            raise IOError(f"read: zero-length data at offset {offset}")
        blob += r[18:18 + dlen]
        offset += dlen
    if len(blob) != CONFIG_SIZE:
        raise IOError(f"read: got {len(blob)} bytes, expected {CONFIG_SIZE}")
    return bytes(blob)


def write_config(h, blob):
    if len(blob) != CONFIG_SIZE:
        raise ValueError(f"config must be {CONFIG_SIZE} bytes, got {len(blob)}")
    offset = 0
    while offset < CONFIG_SIZE:
        size = min(CHUNK, CONFIG_SIZE - offset)
        h.write(_frame(CMD_WRITE, offset, size, blob[offset:offset + size]))
        r = _await(h, CMD_WRITE, tries=30)
        if r is None:
            raise IOError(f"write: no ack at offset {offset}")
        offset += r[10] if r[10] else size
    # commit
    commit = bytearray(16)
    commit[0] = CMD_COMMIT
    commit[2] = SUBCMD_COMMIT
    body = bytes([0x81, 0x11, CHANNEL]) + bytes(commit)
    h.write(body + b"\x00" * (64 - len(body)))
    if _await(h, CMD_COMMIT, tries=30) is None:
        raise IOError("write: commit not acknowledged")


def decode(blob):
    def u32(o):
        return int.from_bytes(blob[o:o + 4], "little")

    print(f"config: {len(blob)} bytes  header={blob[:4].hex(' ')}")
    for bi, base in enumerate(BUTTONMAP_OFFSETS):
        flag = u32(base)
        tag = "active/DInput" if bi == 1 else "stored/XInput"
        state = "enabled" if flag == ENABLE_FLAG else f"flag={flag:08x}"
        print(f"\nbutton map block {bi} @0x{base:03x} ({tag}, {state}):")
        for i, phys in enumerate(PHYSICAL):
            val = u32(base + 4 + 4 * i)
            if val == 0:
                fn = "-"
            else:
                bit = val.bit_length() - 1
                fn = FUNCTION.get(bit, f"bit{bit}")
            print(f"    {phys:<7} -> {fn}")
    # profile name lives just after the block-2 name enable flag (0x11c)
    name = blob[0x120:0x140]
    try:
        txt = name.decode("utf-16-le").rstrip("\x00￿")
    except UnicodeDecodeError:
        txt = name.hex()
    print(f"\nprofile name: {txt!r}")


def cmd_read(args):
    h = open_stick()
    blob = read_config(h)
    out = args[0] if args else "config_dump.bin"
    with open(out, "wb") as f:
        f.write(blob)
    print(f"read {len(blob)} bytes -> {out}")
    decode(blob)


def cmd_decode(args):
    path = args[0] if args else "config_dump.bin"
    decode(open(path, "rb").read())


def cmd_capture(args):
    if not args:
        raise SystemExit("usage: capture <name>")
    os.makedirs(CAP_DIR, exist_ok=True)
    h = open_stick()
    blob = read_config(h)
    path = os.path.join(CAP_DIR, args[0] + ".bin")
    with open(path, "wb") as f:
        f.write(blob)
    print(f"captured live config -> {os.path.normpath(path)}")
    decode(blob)


def cmd_list(args):
    if not os.path.isdir(CAP_DIR):
        print("no captures yet")
        return
    for fn in sorted(os.listdir(CAP_DIR)):
        if fn.endswith(".bin"):
            print(" ", fn[:-4])


def cmd_apply(args):
    if not args:
        raise SystemExit("usage: apply <name> --yes-write")
    name = args[0]
    if "--yes-write" not in args:
        raise SystemExit(
            f"REFUSING to write: this changes the stick's stored mapping.\n"
            f"Re-run with:  py stickctl.py apply {name} --yes-write")
    path = os.path.join(CAP_DIR, name + ".bin")
    blob = open(path, "rb").read()
    h = open_stick()
    print(f"writing {name} ({len(blob)} bytes) to the stick...")
    write_config(h, blob)
    print("write + commit ok; verifying...")
    back = read_config(h)
    if back == blob:
        print("VERIFIED: device config matches the applied profile.")
    else:
        diff = sum(a != b for a, b in zip(back, blob))
        print(f"WARNING: read-back differs in {diff} bytes (some fields may be device-normalized).")


def cmd_roundtrip(args):
    """Read current config, write the SAME bytes back, commit, verify. No net change."""
    if "--yes-write" not in args:
        raise SystemExit(
            "This performs a real write+commit (of the identical current config).\n"
            "Re-run with:  py stickctl.py roundtrip --yes-write")
    h = open_stick()
    print("reading current config...")
    before = read_config(h)
    print(f"  {len(before)} bytes, name={decode_name(before)!r}")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "roundtrip_backup.bin"), "wb") as f:
        f.write(before)
    print("wrote local safety backup: roundtrip_backup.bin")
    print("writing the same bytes back + commit...")
    write_config(h, before)
    print("reading back to verify...")
    after = read_config(h)
    if after == before:
        print("\nPASS: full write+commit cycle works and config is byte-identical.")
    else:
        diff = [(i, before[i], after[i]) for i in range(len(before)) if before[i] != after[i]]
        print(f"\nDIFF in {len(diff)} bytes (first few): {diff[:8]}")
        print("Config still valid (we wrote back what was there); investigate before real applies.")


def decode_name(blob):
    try:
        return blob[0x120:0x140].decode("utf-16-le").rstrip("\x00￿")
    except UnicodeDecodeError:
        return blob[0x120:0x140].hex()


COMMANDS = {
    "read": cmd_read, "decode": cmd_decode, "capture": cmd_capture,
    "list": cmd_list, "apply": cmd_apply, "roundtrip": cmd_roundtrip,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return 1
    COMMANDS[sys.argv[1]](sys.argv[2:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
