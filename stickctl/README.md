# stickctl

A command-line tool that talks the 8BitDo Arcade Stick's config protocol directly
over USB HID — capture, inspect and switch the on-stick mapping without opening the
Ultimate Software GUI. Protocol write-up: [../docs/protocol.md](../docs/protocol.md).

## Status

- ✅ **Read / decode / capture** the live 564-byte config (safe, read-only)
- ✅ **Write + commit** — proven on hardware (`roundtrip` self-test, byte-verified)
- ✅ **Capture-and-switch workflow** — `capture`, `list`, `switch`, `current`
- ✅ **ini profiles baked in** — every profile in [`../profiles/`](../profiles/) is
  compiled to a device image on the fly (no sync-then-capture needed); validated by
  compiling `PS3.ini` and matching the GUI-synced capture byte-for-byte
- ✅ **Tray + hotkey app** — `tray.py` / `stick-tray.cmd`

## Setup

```bash
py -m pip install hidapi
```

Connect the stick by **USB cable**, mode switch on **X**. From the repo root you can
use the `stick` wrapper instead of `py stickctl\stickctl.py`:

```bash
stick <command> ...
```

## Config mode (now automatic on Switch mode)

stickctl reaches the stick through a USB interface (`2dc8:901a`) that only exists in
**8BitDo config mode**. stickctl enters that mode itself — emulating the Ultimate
Software — when the stick's mode switch is on **S (Switch mode)**: `switch`/`wake`
open the `057e:2009` interface and send the vendor jump command. On **X (Xbox mode)**
there's no writable channel, so fall back to launching the Ultimate Software once.
Details + how it was reverse-engineered: [../docs/config-mode.md](../docs/config-mode.md).
`stick state` shows the current mode; `stick selftest-wake` proves the jump cycle
(app closed).

## The tray app

```bash
stick-tray.cmd        # from the repo root; or:  pyw stickctl\tray.py
```

Puts a joystick icon in the notification area. Click it for a menu of **every**
profile — captured images *and* all the ini profiles, compiled on the fly — with a
check on whatever's currently loaded. Click a profile to switch (~1s, verified, with
a toast notification). The first ten profiles also get global hotkeys
**Ctrl+Alt+1 … Ctrl+Alt+0**, shown in the menu.

To start it with Windows: Win+R → `shell:startup` → drop in a shortcut to
`stick-tray.cmd`.

## The CLI workflow

Every ini profile in [`../profiles/`](../profiles/) is available by name — no setup:

```bash
stick list                      # everything: captures + ini profiles, with mappings
stick switch "Pocket SNES"      # compile the ini and load it, ~1s
stick switch ps3                # or load a captured image
stick current                   # what's on the stick right now?
```

Captures still exist for snapshotting a GUI-tuned profile exactly as synced:

```bash
stick capture ps3 "PlayStation 3 (Bluetooth)"
```

`switch` skips the write if the profile is already loaded, and always reads the
config back to verify (ignoring the 4-byte header, which the stick re-checksums
itself on commit).

## All commands

| Command | Writes? | Purpose |
|---|---|---|
| `capture <name> [label]` | no | snapshot the stick's current config to the library |
| `list` | no | list all profiles (captures + inis) and their mappings |
| `current` | no | show what's on the stick, and which profile it matches |
| `compile <ini-name> [out]` | no | compile an ini to a device image and decode it |
| `switch <name>` | **yes** | load a capture or ini profile onto the stick |
| `read [out.bin]` | no | dump+decode live config to a file |
| `decode [file.bin]` | no | decode a saved dump offline |
| `apply <name> --yes-write` | **yes** | scriptable `switch` (explicit flag) |
| `roundtrip --yes-write` | **yes** | self-test: rewrite the current config, verify identical |

## Safety

Read commands never write. Every write is followed by a read-back-and-verify, and a
bad write is fully recoverable by re-syncing any profile from the Ultimate Software.

## Files

| File | Purpose |
|---|---|
| `stickctl.py` | the CLI tool + protocol/compiler library |
| `tray.py` | tray + global-hotkey switcher (`py tray.py --check` self-tests) |
| `template.bin` | GUI-written config image the ini compiler patches |
| `disasm2.py`, `disasm3.py` | export/thunk disassembly helpers used to RE the protocol |
| `analyze.py` | hex-dump + structure scan for a config blob |

Tray/hotkey dependencies: `py -m pip install pystray Pillow keyboard`.
