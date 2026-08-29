#!/usr/bin/env python3
"""stickctl - fast profile control for the 8BitDo Arcade Stick (PID 0x901a).

Talks the Ultimate-Software HID config protocol directly, so profiles can be
dumped, inspected, captured and applied without the official GUI. Protocol
reverse-engineered from 8BitDoAdvance.dll + TheJayMann/8bitdo-spec; see
docs/protocol.md.

Everyday workflow:
    stick capture <name>     snapshot the profile currently on the stick
    stick list               show your captured profiles + what they map
    stick switch <name>      load a captured profile onto the stick (~1s)
    stick current            show what's on the stick right now

Lower level:
    stick read [out.bin]     read+decode live config to a file
    stick decode [file.bin]  decode a saved dump (offline)
    stick apply <name> --yes-write   scriptable switch (explicit write flag)

Setup:  py -m pip install hidapi ; connect by USB, mode switch on X.
"""
import datetime
import hashlib
import json
import os
import sys

import hid

VID, PID = 0x2DC8, 0x901A
CONFIG_SIZE = 0x234          # 564 bytes (confirmed: _writeArcadeStick@564)
CHUNK = 0x2D                 # 45 bytes max per transfer
CMD_READ = 0x0C
CMD_WRITE = 0x0B
CMD_COMMIT = 0x06
SUBCMD_COMMIT = 0x15
CHANNEL = 0x04
ENABLE_FLAG = 0x20191212

CAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "captures")

PHYSICAL = ["A", "B", "X", "Y", "L", "R", "L2", "R2", "L3", "R3",
            "Select", "Start", "Share", "Home", "Up", "Down", "Left", "Right"]
FUNCTION = {
    0: "Start", 1: "L3", 2: "R3", 3: "Select", 4: "X", 5: "Y", 6: "Right",
    7: "Left", 8: "Down", 9: "Up", 10: "L1", 11: "R1", 12: "B", 13: "A",
    14: "L2", 15: "R2", 16: "Menu", 17: "Home", 18: "BT Connect",
    22: "Screenshot", 23: "Turbo", 24: "Turbo Auto", 25: "P1", 26: "P2",
    27: "Dyn swap",
}
BUTTONMAP_OFFSETS = (0xD0, 0x1E8)   # block A (XInput), block B (DInput)


# ---------------------------------------------------------------- transport
def open_stick():
    devs = hid.enumerate(VID, PID)
    if not devs:
        raise SystemExit(
            "Arcade Stick (2dc8:901a) not found.\n"
            "Plug it in by USB cable with the mode switch on X, then retry.")
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
    commit = bytearray(16)
    commit[0] = CMD_COMMIT
    commit[2] = SUBCMD_COMMIT
    body = bytes([0x81, 0x11, CHANNEL]) + bytes(commit)
    h.write(body + b"\x00" * (64 - len(body)))
    if _await(h, CMD_COMMIT, tries=30) is None:
        raise IOError("write: commit not acknowledged")


# ------------------------------------------------------------------ decode
def _u32(blob, o):
    return int.from_bytes(blob[o:o + 4], "little")


def profile_name(blob):
    try:
        return blob[0x120:0x140].decode("utf-16-le").rstrip("\x00�")
    except UnicodeDecodeError:
        return blob[0x120:0x140].hex()


def button_map(blob, base):
    out = []
    for i, phys in enumerate(PHYSICAL):
        val = _u32(blob, base + 4 + 4 * i)
        if val == 0:
            out.append((phys, "-"))
        else:
            bit = val.bit_length() - 1
            out.append((phys, FUNCTION.get(bit, f"bit{bit}")))
    return out


def active_map(blob):
    """The DInput block is the one that drives Bluetooth/adapter play."""
    return button_map(blob, BUTTONMAP_OFFSETS[1])


def map_summary(blob):
    """One-line summary: only the buttons that are remapped (not identity)."""
    ident = {"A": "A", "B": "B", "X": "X", "Y": "Y", "L": "L1", "R": "R1",
             "L2": "L2", "R2": "R2", "Select": "Select", "Start": "Start",
             "Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right",
             "Home": "Home", "Share": "Menu", "L3": "-", "R3": "-"}
    changes = [f"{p}->{f}" for p, f in active_map(blob) if ident.get(p) != f]
    return ", ".join(changes) if changes else "identity"


def decode(blob):
    print(f"config: {len(blob)} bytes   name={profile_name(blob)!r}")
    for bi, base in enumerate(BUTTONMAP_OFFSETS):
        flag = _u32(blob, base)
        tag = "active/DInput" if bi == 1 else "stored/XInput"
        state = "enabled" if flag == ENABLE_FLAG else f"flag={flag:08x}"
        print(f"\nbutton map block {bi} @0x{base:03x} ({tag}, {state}):")
        for phys, fn in button_map(blob, base):
            print(f"    {phys:<7} -> {fn}")


# ---------------------------------------------------------------- captures
def cap_path(name):
    return os.path.join(CAP_DIR, name + ".bin")


def meta_path(name):
    return os.path.join(CAP_DIR, name + ".json")


def save_capture(name, blob, label=None):
    os.makedirs(CAP_DIR, exist_ok=True)
    with open(cap_path(name), "wb") as f:
        f.write(blob)
    meta = {
        "label": label or name,
        "config_name": profile_name(blob),
        "map": map_summary(blob),
        "captured_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(blob).hexdigest(),
    }
    with open(meta_path(name), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    return meta


def load_meta(name):
    try:
        with open(meta_path(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def list_captures():
    if not os.path.isdir(CAP_DIR):
        return []
    return sorted(fn[:-4] for fn in os.listdir(CAP_DIR) if fn.endswith(".bin"))


def find_matching_capture(blob):
    digest = hashlib.sha256(blob).hexdigest()
    for name in list_captures():
        m = load_meta(name)
        if m.get("sha256") == digest:
            return name
        if not m:  # no metadata: compare bytes directly
            if open(cap_path(name), "rb").read() == blob:
                return name
    return None


# ------------------------------------------------------------------ commands
def cmd_capture(args):
    if not args:
        raise SystemExit("usage: stick capture <name>   (name the console, e.g. ps3)")
    name = args[0]
    label = " ".join(args[1:]) if len(args) > 1 else None
    h = open_stick()
    blob = read_config(h)
    meta = save_capture(name, blob, label)
    print(f"captured '{name}' <- profile {meta['config_name']!r}")
    print(f"  mapping: {meta['map']}")
    print(f"  saved:   {os.path.normpath(cap_path(name))}")


def cmd_list(args):
    names = list_captures()
    if not names:
        print("No captures yet. Sync a profile in the Ultimate Software,\n"
              "then run:  stick capture <name>")
        return
    print(f"{'name':<12} {'profile':<16} mapping")
    print("-" * 60)
    for name in names:
        m = load_meta(name)
        print(f"{name:<12} {str(m.get('config_name','?')):<16} {m.get('map','?')}")


def cmd_switch(args):
    if not args:
        raise SystemExit("usage: stick switch <name>   (see 'stick list')")
    name = args[0]
    if not os.path.exists(cap_path(name)):
        avail = ", ".join(list_captures()) or "(none)"
        raise SystemExit(f"no capture named '{name}'. Available: {avail}")
    blob = open(cap_path(name), "rb").read()
    h = open_stick()
    current = read_config(h)
    if current == blob:
        print(f"'{name}' is already loaded on the stick. Nothing to do.")
        return
    print(f"switching to '{name}' ({profile_name(blob)!r})...")
    write_config(h, blob)
    back = read_config(h)
    if back == blob:
        print(f"done. active mapping: {map_summary(blob)}")
    else:
        diff = sum(a != b for a, b in zip(back, blob))
        print(f"WARNING: read-back differs in {diff} bytes; re-sync in the app if the stick misbehaves.")


def cmd_current(args):
    h = open_stick()
    blob = read_config(h)
    match = find_matching_capture(blob)
    print(f"on stick: {profile_name(blob)!r}   mapping: {map_summary(blob)}")
    if match:
        print(f"matches captured profile: '{match}'")
    else:
        print("does not match any capture (run 'stick capture <name>' to save it)")


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


def cmd_apply(args):
    if not args:
        raise SystemExit("usage: stick apply <name> --yes-write")
    name = args[0]
    if "--yes-write" not in args:
        raise SystemExit(f"writes flash; re-run:  stick apply {name} --yes-write")
    cmd_switch([name])


def cmd_roundtrip(args):
    if "--yes-write" not in args:
        raise SystemExit("writes the identical current config back; re-run: stick roundtrip --yes-write")
    h = open_stick()
    before = read_config(h)
    print(f"read {len(before)} bytes, name={profile_name(before)!r}")
    write_config(h, before)
    after = read_config(h)
    print("PASS: byte-identical" if after == before else "DIFF: investigate")


COMMANDS = {
    "capture": cmd_capture, "list": cmd_list, "switch": cmd_switch,
    "current": cmd_current, "read": cmd_read, "decode": cmd_decode,
    "apply": cmd_apply, "roundtrip": cmd_roundtrip,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return 1
    COMMANDS[sys.argv[1]](sys.argv[2:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
