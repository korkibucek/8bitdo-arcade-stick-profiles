# stickctl

A tiny command-line tool that talks the 8BitDo Arcade Stick's config protocol
directly over USB HID — no Ultimate Software GUI needed. This is the foundation for a
fast profile switcher (see the [protocol write-up](../docs/protocol.md)).

## Status

- ✅ **Read** the live 564-byte config off the stick
- ✅ **Decode** it (gamepad mode, profile name, full button map for both blocks)
- ✅ **Capture** the current config to a named file
- ✅ **Write + commit** — proven on hardware via the `roundtrip` self-test
  (writes the current config back byte-for-byte and verifies). The `apply` command
  (write a *different* captured profile) is guarded behind `--yes-write` and always
  read-back-verifies.

## Setup

```bash
py -m pip install hidapi
```

Connect the stick by **USB cable** with the mode switch on **X**.

## Usage

```bash
# read + decode the live config (safe)
py stickctl.py read

# decode a saved dump (safe, offline)
py stickctl.py decode config_dump.bin

# save the current on-stick config under a name (safe)
py stickctl.py capture ps3

# list captured profiles
py stickctl.py list

# write a captured profile back to the stick (writes flash!)
py stickctl.py apply ps3 --yes-write
```

## The switcher idea

Because `capture` grabs a complete, valid config image, the fast-switch workflow is:

1. In the official app, sync a console profile once.
2. `py stickctl.py capture <console>` — stores that exact image.
3. Repeat for each console.

After that, `py stickctl.py apply <console> --yes-write` swaps the stick to any
captured profile in ~1 second, cable in, no GUI. A tray app / hotkey wrapper is the
natural next step.

## Files

| File | Purpose |
|---|---|
| `stickctl.py` | the tool (read / decode / capture / list / apply) |
| `disasm2.py`, `disasm3.py` | export/thunk disassembly helpers used to RE the protocol |
| `analyze.py` | hex-dump + structure scan for a config blob |

## Safety

`read`, `decode`, `capture`, `list` never write to the device. `apply` refuses to run
without `--yes-write`, and always reads the config back and diffs it. A bad write is
recoverable by re-syncing any profile from the official Ultimate Software.
