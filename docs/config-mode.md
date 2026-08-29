# Why stickctl needs the stick in "config mode"

If `stick switch` (or the tray) says **"needs config mode"** or **"stick not
connected"** even though the stick is plugged in, this page explains why and what to
do.

## The short version

`stickctl` talks to the stick through a special USB interface that appears as
`VID_2DC8&PID_901A`. That interface only exists while the stick is in **8BitDo config
mode**. The Ultimate Software is what puts the stick into that mode.

When the Ultimate Software is **not** running, the stick reverts to its normal gaming
identity — in X-input mode that's a plain **Xbox 360 controller** (`VID_045E&PID_028E`)
— and the config interface disappears. An Xbox-mode controller accepts no output
reports, so nothing in user space (not stickctl, not the tray) can flip it back.

**Fix today:** launch the 8BitDo Ultimate Software once. It flips the stick into
config mode, the `2dc8:901a` interface re-appears, and stickctl + the tray work. The
app can sit **minimized** — you never need to touch its UI; keep using the tray and
hotkeys. Check the state any time with:

```bash
stick state
```

## The detail

8BitDo sticks have several USB "personalities":

| Physical / software state | USB identity | Writable config interface? |
|---|---|---|
| X-input gaming (app closed) | `045e:028e` Xbox 360 pad | no (input-only) |
| Switch gaming (app closed) | Switch Pro pad | no via this tool yet |
| **Config mode (app running)** | **`2dc8:901a`** | **yes — this is what stickctl uses** |

We verified on this hardware that the Xbox-mode interface (`045e:028e`) rejects every
output and feature report (`write -> -1`), so the documented "jump to config mode"
command can't be delivered from X-input mode. The official app establishes config mode
through a channel that isn't reachable once the stick has settled into pure Xbox-input
mode.

## Fully app-free operation (possible future work)

The [8bitdo-spec SwitchMode notes](https://github.com/TheJayMann/8bitdo-spec) describe
a command (`01 66 AA 00 51 01`) that flips the stick from **Switch mode** into the
8BitDo/config identity. Unlike Xbox mode, a Switch-Pro HID device *does* accept output
reports, so a `stick wake` command that works when the mode switch is on **S** is
plausible — it just needs testing on the hardware. That would let stickctl enter config
mode itself without the Ultimate Software. It's not implemented yet; see the
[project notes](../stickctl/README.md).

Until then: keep the Ultimate Software running (minimized) when you want to switch
profiles with stickctl or the tray.
