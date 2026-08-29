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
import time

import hid

VID, PID = 0x2DC8, 0x901A
# Switch-mode identity (Nintendo Pro Controller impersonation) + vendor commands
# that flip the stick into config mode. Reverse-engineered from findSwitch/
# writeSwitch in 8BitDoAdvance.dll; see docs/config-mode.md.
SWITCH_VID, SWITCH_PID = 0x057E, 0x2009
CMD_VERSION = bytes([0x01, 0x66, 0xAA, 0x00, 0x21, 0x01])
CMD_JUMP_CONFIG = bytes([0x01, 0x66, 0xAA, 0x00, 0x51, 0x01])
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
class StickNotInConfigMode(SystemExit):
    pass


def stick_state():
    """Return 'config' (2dc8:901a present), 'xbox' (X-input gaming mode),
    'switch' (Switch gaming mode, wake-able), or 'absent'."""
    if hid.enumerate(VID, PID):
        return "config"
    if hid.enumerate(SWITCH_VID, SWITCH_PID):
        return "switch"
    if hid.enumerate(0x045E, 0x028E):
        return "xbox"
    return "absent"


def wake(verbose=True):
    """Flip the stick from Switch mode into config mode, exactly as the
    Ultimate Software's writeSwitch() does: open the 057e:2009 Pro-Controller
    interface and send the 8BitDo vendor jump command. Returns True if the
    config interface (2dc8:901a) appears afterwards.
    """
    if hid.enumerate(VID, PID):
        return True  # already in config mode
    devs = hid.enumerate(SWITCH_VID, SWITCH_PID)
    if not devs:
        return False
    h = hid.device()
    h.open_path(devs[0]["path"])
    try:
        # version request first (confirms it's an 8BitDo, mirrors the app)
        for _ in range(2):
            h.write(CMD_VERSION + b"\x00" * 58)
            r = bytes(h.read(64, 300))
            if verbose and r:
                print(f"  switch-mode reply: {r[:8].hex(' ')}")
        h.write(CMD_JUMP_CONFIG + b"\x00" * 58)
    finally:
        try:
            h.close()
        except Exception:
            pass
    # the device re-enumerates; wait for the config interface to appear
    for _ in range(20):
        time.sleep(0.4)
        if hid.enumerate(VID, PID):
            return True
    return False


def open_stick(auto_wake=True):
    devs = hid.enumerate(VID, PID)
    if not devs and auto_wake and hid.enumerate(SWITCH_VID, SWITCH_PID):
        wake(verbose=False)                    # emulate the app's mode jump
        devs = hid.enumerate(VID, PID)
    if devs:
        h = hid.device()
        h.open_path(devs[0]["path"])
        h.set_nonblocking(False)
        return h
    state = stick_state()
    if state == "xbox":
        raise StickNotInConfigMode(
            "The stick is in Xbox (X-input) mode, which has no writable channel to\n"
            "enter config mode. Slide the mode switch to S (Switch mode) and retry -\n"
            "stickctl will then flip it into config mode automatically. See\n"
            "docs/config-mode.md.")
    raise StickNotInConfigMode(
        "Arcade Stick not found. Plug it in by USB cable (mode switch on S so\n"
        "stickctl can enter config mode automatically). See docs/config-mode.md.")


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
    ident = {"A": {"A"}, "B": {"B"}, "X": {"X"}, "Y": {"Y"}, "L": {"L1"},
             "R": {"R1"}, "L2": {"L2"}, "R2": {"R2"}, "Select": {"Select"},
             "Start": {"Start"}, "Up": {"Up"}, "Down": {"Down"},
             "Left": {"Left"}, "Right": {"Right"}, "Home": {"Home"},
             "Share": {"Menu"}, "L3": {"L3", "-"}, "R3": {"R3", "-"}}
    changes = [f"{p}->{f}" for p, f in active_map(blob) if f not in ident.get(p, set())]
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


# ------------------------------------------------------------ ini compiler
INI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "profiles")
TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.bin")

# ini [Mappings] key -> button-map entry index (physical order in the blob)
INI_PHYS = {"A": 0, "B": 1, "X": 2, "Y": 3, "L": 4, "R": 5, "L2": 6, "R2": 7,
            "L3": 8, "R3": 9, "SELECT": 10, "START": 11, "SHARE": 12,
            "HOME": 13, "UP": 14, "DOWN": 15, "LEFT": 16, "RIGHT": 17}
# ini output value -> function bit (empirically verified against GUI-synced dumps)
INI_FUNC = {"START": 0, "L3": 1, "R3": 2, "SELECT": 3, "X": 4, "Y": 5,
            "RIGHT": 6, "LEFT": 7, "DOWN": 8, "UP": 9, "L": 10, "R": 11,
            "L1": 10, "R1": 11, "B": 12, "A": 13, "L2": 14, "R2": 15,
            "TURBO": 16, "MENU": 16, "SWITCHHOME": 17, "HOME": 17}


def parse_ini_mappings(path):
    mappings, in_section = {}, False
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("["):
                in_section = line.lower() == "[mappings]"
                continue
            if in_section and "=" in line:
                k, v = line.split("=", 1)
                mappings[k.strip().upper()] = v.strip().upper()
    return mappings


def compile_ini(path):
    """Build a 564-byte config image from an Ultimate Software ini profile.

    Patches the template's name and BOTH button-map blocks (XInput + DInput)
    with the ini's [Mappings]; stick/trigger/rumble params stay at the
    template's GUI-written defaults, which is what all our profiles use.
    """
    blob = bytearray(open(TEMPLATE, "rb").read())
    mappings = parse_ini_mappings(path)
    entries = [0] * 18
    for key, val in mappings.items():
        if key not in INI_PHYS:
            continue
        idx = INI_PHYS[key]
        if val == "N":
            entries[idx] = 0
        elif val in INI_FUNC:
            entries[idx] = 1 << INI_FUNC[val]
        else:
            raise ValueError(f"{os.path.basename(path)}: unknown output {val!r} for {key}")
    for base in BUTTONMAP_OFFSETS:
        blob[base:base + 4] = ENABLE_FLAG.to_bytes(4, "little")
        for i, v in enumerate(entries):
            blob[base + 4 + 4 * i:base + 8 + 4 * i] = v.to_bytes(4, "little")
    name = os.path.splitext(os.path.basename(path))[0][:16]
    raw = name.encode("utf-16-le")
    blob[0x11C:0x120] = ENABLE_FLAG.to_bytes(4, "little")
    blob[0x120:0x140] = raw + b"\x00" * (32 - len(raw))
    return bytes(blob)


def list_inis():
    if not os.path.isdir(INI_DIR):
        return []
    return sorted(fn[:-4] for fn in os.listdir(INI_DIR) if fn.lower().endswith(".ini"))


def resolve_profile(name):
    """Return (kind, blob) for a capture or ini profile; case-insensitive."""
    for cap in list_captures():
        if cap.lower() == name.lower():
            return "capture", open(cap_path(cap), "rb").read()
    for ini in list_inis():
        if ini.lower() == name.lower():
            return "ini", compile_ini(os.path.join(INI_DIR, ini + ".ini"))
    return None, None


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


def same_config(a, b):
    """Equality ignoring the 4-byte header (device recomputes its CRC there)."""
    return a[4:] == b[4:]


def find_matching_capture(blob):
    for name in list_captures():
        try:
            if same_config(open(cap_path(name), "rb").read(), blob):
                return name
        except OSError:
            pass
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
    caps = list_captures()
    inis = list_inis()
    print(f"{'name':<22} {'source':<9} mapping")
    print("-" * 78)
    for name in caps:
        m = load_meta(name)
        print(f"{name:<22} {'capture':<9} {m.get('map','?')}")
    for name in inis:
        try:
            summary = map_summary(compile_ini(os.path.join(INI_DIR, name + ".ini")))
        except ValueError as e:
            summary = f"(compile error: {e})"
        print(f"{name:<22} {'ini':<9} {summary}")
    if not caps and not inis:
        print("(nothing found - add ini files to profiles/ or run 'stick capture <name>')")


def cmd_switch(args):
    if not args:
        raise SystemExit("usage: stick switch <name>   (see 'stick list')")
    name = " ".join(a for a in args if not a.startswith("--"))
    kind, blob = resolve_profile(name)
    if blob is None:
        avail = ", ".join(list_captures() + list_inis()) or "(none)"
        raise SystemExit(f"no profile named '{name}'. Available: {avail}")
    h = open_stick()
    current = read_config(h)
    if same_config(current, blob):
        print(f"'{name}' is already loaded on the stick. Nothing to do.")
        return
    print(f"switching to '{name}' ({kind}, {profile_name(blob)!r})...")
    write_config(h, blob)
    back = read_config(h)
    if same_config(back, blob):
        print(f"done. active mapping: {map_summary(blob)}")
    else:
        diff = sum(a != b for a, b in zip(back, blob))
        print(f"WARNING: read-back differs in {diff} bytes; re-sync in the app if the stick misbehaves.")


def identify(blob):
    """Name of the capture or ini profile this blob matches, else None."""
    match = find_matching_capture(blob)
    if match:
        return match
    for ini in list_inis():
        try:
            if same_config(compile_ini(os.path.join(INI_DIR, ini + ".ini")), blob):
                return ini
        except ValueError:
            pass
    return None


def cmd_state(args):
    s = stick_state()
    msg = {
        "config": "config mode (2dc8:901a) - ready. stickctl can read/write.",
        "switch": "Switch mode (057e:2009) - run 'stick wake' (or just switch); it enters config mode automatically.",
        "xbox": "Xbox mode (045e:028e) - no writable channel. Slide mode switch to S to make it wake-able.",
        "absent": "not detected. Plug in by USB.",
    }[s]
    print(f"stick state: {msg}")


def to_switch_mode(h):
    """Emulate the app's swExitDinput: tell the config device to drop back to
    Switch gaming mode. The 2dc8:901a interface disappears afterwards."""
    body = bytes([0x81, 0x05, 0x00, 0x51, 0x04])
    h.write(body + b"\x00" * (64 - len(body)))


def cmd_selftest_wake(args):
    """End-to-end proof of the mode emulation, no physical switch needed:
    config -> (exit to Switch) -> Switch -> (wake) -> config, verifying the
    config survives. Only run with the Ultimate Software closed."""
    if any("8bitdo" in (p or "").lower() for p in _running_processes()):
        raise SystemExit("Close the 8BitDo Ultimate Software first (it fights for the device).")
    if stick_state() != "config":
        raise SystemExit(f"need to start in config mode; current state: {stick_state()}")
    h = open_stick(auto_wake=False)
    before = read_config(h)
    name = profile_name(before)
    print(f"start: config mode, profile {name!r}")
    print("sending exit-to-Switch...")
    to_switch_mode(h)
    try:
        h.close()
    except Exception:
        pass
    for _ in range(20):
        time.sleep(0.4)
        if hid.enumerate(SWITCH_VID, SWITCH_PID):
            break
    if not hid.enumerate(SWITCH_VID, SWITCH_PID):
        raise SystemExit("stick did not drop to Switch mode; state=" + stick_state())
    print(f"now in Switch mode ({SWITCH_VID:04x}:{SWITCH_PID:04x}). Running wake()...")
    if not wake():
        raise SystemExit("wake() failed - stick is in Switch mode; replug or open the app to recover.")
    h2 = open_stick(auto_wake=False)
    after = read_config(h2)
    if same_config(after, before):
        print(f"PASS: full config<->Switch<->config cycle works; profile {name!r} intact.")
    else:
        print("config differs after cycle; investigate (stick still functional).")


def _running_processes():
    try:
        import subprocess
        out = subprocess.check_output(
            ["tasklist", "/fo", "csv", "/nh"], text=True, stderr=subprocess.DEVNULL)
        return [line.split(",")[0].strip('"') for line in out.splitlines()]
    except Exception:
        return []


def cmd_wake(args):
    s = stick_state()
    if s == "config":
        print("already in config mode.")
        return
    if s == "switch":
        print("flipping stick from Switch mode into config mode...")
        if wake():
            print("config mode entered (2dc8:901a present).")
        else:
            print("wake sent but config interface did not appear; try 'stick state'.")
        return
    if s == "xbox":
        raise SystemExit("stick is in Xbox mode - slide the mode switch to S, then 'stick wake'.")
    raise SystemExit("stick not detected on USB.")


def cmd_current(args):
    h = open_stick()
    blob = read_config(h)
    match = identify(blob)
    print(f"on stick: {profile_name(blob)!r}   mapping: {map_summary(blob)}")
    if match:
        print(f"matches profile: '{match}'")
    else:
        print("does not match any known profile (run 'stick capture <name>' to save it)")


def cmd_compile(args):
    if not args:
        raise SystemExit("usage: stick compile <ini-name> [out.bin]")
    name = args[0]
    path = os.path.join(INI_DIR, name + ".ini")
    if not os.path.exists(path):
        raise SystemExit(f"no ini profile {name!r} in profiles/")
    blob = compile_ini(path)
    if len(args) > 1:
        with open(args[1], "wb") as f:
            f.write(blob)
        print(f"wrote {args[1]}")
    decode(blob)


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
    "apply": cmd_apply, "roundtrip": cmd_roundtrip, "compile": cmd_compile,
    "state": cmd_state, "wake": cmd_wake, "selftest-wake": cmd_selftest_wake,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return 1
    COMMANDS[sys.argv[1]](sys.argv[2:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
