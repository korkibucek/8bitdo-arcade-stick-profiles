# Using this stick on Xbox Series X|S

**Short answer:** this stick can't work *natively* on an Xbox Series X|S or Xbox One —
not even wired — and no firmware or software (ours or anyone's) can change that. But it
**can** work through one specific licensed adapter: the **Brook Wingman XB3**.

## Why it doesn't work directly

This is the 2021 **8BitDo Arcade Stick for Switch & Windows** (config PID `0x901a`). Its
two output modes are **S** (Switch / `057e:2009`) and **X** (X-input, which presents as
an Xbox *360* controller `045e:028e`). X-input is a PC standard.

Modern Xbox consoles (One, Series X|S) don't accept X-input / Xbox 360 devices. They
use the **GIP** protocol with a mandatory **authentication handshake**, and since
November 2023 Microsoft actively blocks unauthorized accessories (error
`0x82d60002`). When you plug this stick into a Series X, it fails auth and is ignored —
which is exactly what you saw over USB.

**Can't we just emulate the auth?** No. Xbox authentication (XSM3/GIP) is a
hardware root-of-trust: even though the algorithm has been reverse-engineered, each
response needs a per-console key derived from a secret that exists **only inside
Microsoft-licensed chips**. It is not defeatable in software. This is a different, much
harder wall than the config-mode protocol we reverse-engineered for profile switching —
that one had no secret; this one does.

## The solution: Brook Wingman XB3

The Wingman XB3 is a licensed converter that performs the Xbox authentication itself and
lets 135+ controllers drive a Series X|S. It sits between the stick and the console.

> **Get the XB3, not the XB2.** The older **Wingman XB2 dropped Xbox Series X|S / Xbox
> One support in February 2024** (it now only does Xbox 360 / Original Xbox). Only the
> **XB3** targets modern Xbox.

### How to connect *this* stick

Confirmed working method (reported by 8BitDo Arcade Stick owners):

1. Set the stick's mode switch to **X** (X-input) and its connection switch to **2.4G**.
2. Plug the stick's **8BitDo 2.4GHz USB dongle** into the **Wingman XB3's** USB input
   port (dongle-into-adapter).
3. Plug the **Wingman XB3** into the Xbox Series X's USB port.
4. Load the stick's Xbox profile first (in this repo: `stick switch "Xbox Series X"`,
   or the Ultimate Software) so the stick's button layout is what you want. The XB3 can
   also remap on its own.

Wired (stick in X mode via USB-C into the XB3's input) is a reasonable fallback, but the
dongle method is the one owners report success with.

### Caveats

- Microsoft and Brook play cat-and-mouse: a console update can temporarily break
  adapters until Brook ships a firmware fix. **Keep the XB3's firmware updated.**
- The stick's own wireless-to-console features don't apply here — everything goes
  through the adapter.

## Alternatives

- **Buy a licensed stick:** the **8BitDo Arcade Stick for Xbox** (2023) or **HORI
  Fighting Stick α** authenticate natively. This replaces the stick rather than reusing
  the one you have.
- A **GP2040-CE** board swap (see the repo issues) gives on-stick profiles and low
  latency but *still* can't authenticate to Series X — same wall.

## Where the repo's "Xbox Series X" profile fits

[`profiles/Xbox Series X.ini`](../profiles/Xbox%20Series%20X.ini) is the **stick-side
X-input mapping** — i.e. what the stick sends *into* the adapter. It's an identity Xbox
layout. It does not (and cannot) make the stick authenticate on its own; it's the
mapping you'd use with the Wingman XB3 in front of it, or on PC.
