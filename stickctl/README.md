# stickctl

A command-line tool that talks the 8BitDo Arcade Stick's config protocol directly
over USB HID — capture, inspect and switch the on-stick mapping without opening the
Ultimate Software GUI. Protocol write-up: [../docs/protocol.md](../docs/protocol.md).

## Status

- ✅ **Read / decode / capture** the live 564-byte config (safe, read-only)
- ✅ **Write + commit** — proven on hardware (`roundtrip` self-test, byte-verified)
- ✅ **Capture-and-switch workflow** — `capture`, `list`, `switch`, `current`

## Setup

```bash
py -m pip install hidapi
```

Connect the stick by **USB cable**, mode switch on **X**. From the repo root you can
use the `stick` wrapper instead of `py stickctl\stickctl.py`:

```bash
stick <command> ...
```

## Everyday workflow

The stick stores one mapping at a time, so the model is: keep a *library* of captured
profiles on the PC, and push whichever one you need.

**1. Build the library (once per console).** Sync a console's profile in the Ultimate
Software as usual, then snapshot exactly what's on the stick:

```bash
stick capture ps3 "PlayStation 3 (Bluetooth)"
stick capture genesis "Analogue Pocket - Genesis"
stick capture snes
```

Each capture writes `captures/<name>.bin` (the raw config image) plus a `.json`
sidecar with the decoded name, a mapping summary and a checksum.

**2. See what you've got:**

```bash
stick list
```

```
name         profile          mapping
------------------------------------------------------------
ps3          PS3 (1)          A->B, B->X, X->A, L2->Select, R2->Start, Select->L3, Start->R3
genesis      Genesis (1)      identity
```

**3. Switch in ~1 second, no GUI:**

```bash
stick switch genesis
```

`switch` skips the write if that profile is already loaded, and always reads the
config back to verify. Plug the stick into the console and play.

**4. Check what's loaded right now:**

```bash
stick current
```

## All commands

| Command | Writes? | Purpose |
|---|---|---|
| `capture <name> [label]` | no | snapshot the stick's current config to the library |
| `list` | no | list captured profiles and their mappings |
| `current` | no | show what's on the stick, and which capture it matches |
| `switch <name>` | **yes** | load a captured profile onto the stick |
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
| `stickctl.py` | the tool |
| `disasm2.py`, `disasm3.py` | export/thunk disassembly helpers used to RE the protocol |
| `analyze.py` | hex-dump + structure scan for a config blob |
