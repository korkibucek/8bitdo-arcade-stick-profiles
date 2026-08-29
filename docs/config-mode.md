# Why stickctl needs the stick in "config mode"

If `stick switch` (or the tray) says **"needs config mode"** or **"stick not
connected"** even though the stick is plugged in, this page explains why and what to
do.

## The short version

`stickctl` talks to the stick through a USB interface that appears as
`VID_2DC8&PID_901A`. That interface only exists while the stick is in **8BitDo config
mode**. Otherwise the stick is a gaming controller and the interface is gone.

**stickctl now enters config mode by itself**, emulating exactly what the Ultimate
Software does — *as long as the stick's mode switch is on `S` (Switch mode)*. Slide the
switch to **S**, plug in USB, and `stick switch` / the tray just work; the mode jump
happens automatically. You can also do it explicitly:

```bash
stick wake      # flip Switch-mode -> config mode
stick state     # show the current mode
```

The one mode we **cannot** wake from is **X (Xbox) mode**: that interface
(`045e:028e`) accepts no output reports at all, so there's no channel to send the jump.
On `S`, the stick impersonates a Switch Pro Controller (`057e:2009`), which *does*
accept the vendor command — that's the door the app uses too.

If you keep the switch on `X` for gaming, the fallback is still: launch the Ultimate
Software once (minimized) to establish config mode.

## The detail

8BitDo sticks have several USB "personalities":

| Mode switch | USB identity | Writable? | Config-mode reachable? |
|---|---|---|---|
| X (Xbox) | `045e:028e` Xbox 360 pad | no (input-only) | only via the Ultimate Software |
| S (Switch) | `057e:2009` Switch Pro pad | **yes** | **yes — `stick wake` jumps it** |
| (after jump) | `2dc8:901a` config | yes | this is what stickctl uses |

## How the mechanism was reverse-engineered

`8BitDoAdvance.dll` uses only the Windows HID API (`HidD_*`), and its **only**
mode-jump code is the exports `findSwitch` / `writeSwitch`:

- `findSwitch` enumerates HID for **`057e:2009`** — a Nintendo Switch Pro Controller,
  i.e. the stick in `S` mode.
- `writeSwitch` opens that device and does a 64-byte HID write then a 64-byte read
  (twice), sending the 8BitDo vendor command.

The command bytes (from the [8bitdo-spec SwitchMode notes](https://github.com/TheJayMann/8bitdo-spec),
matching the DLL's transport):

```
version request : 01 66 AA 00 21 01   -> reply 81 66 A5 <pid-be> ...
jump to config  : 01 66 AA 00 51 01   -> re-enumerates as 2dc8:901a
exit to Switch  : 81 05 00 51 04       (sent to the 2dc8:901a device)
```

There is **no** equivalent finder/writer for the Xbox interface anywhere in the DLL,
and we confirmed on hardware that `045e:028e` rejects every output and feature report
(`write -> -1`). So config mode is fundamentally a **Switch-mode** operation — which is
exactly what `stick wake` reproduces (see `wake()` in
[`stickctl.py`](../stickctl/stickctl.py)).

`stick selftest-wake` proves the whole cycle without touching the physical switch
(config → exit-to-Switch → wake → config, verifying the profile survives). Run it with
the Ultimate Software closed.
