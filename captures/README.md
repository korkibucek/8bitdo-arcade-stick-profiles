# captures

Snapshots of the Arcade Stick's on-device config, one per console, used by
[`stickctl`](../stickctl/) to switch profiles without the Ultimate Software GUI.

Each profile is two files:

- `<name>.bin` — the raw 564-byte config image read off the stick
- `<name>.json` — decoded metadata (profile name, mapping summary, capture time, SHA-256)

Create them with `stick capture <name>` after syncing a profile in the official app;
load one with `stick switch <name>`. See the [stickctl README](../stickctl/README.md).

These `.bin` images are specific to the Arcade Stick (PID `0x901a`) and encode a
single active mapping; they aren't interchangeable with the `.ini` profiles in
[`../profiles/`](../profiles/), which are the Ultimate Software's own format.
