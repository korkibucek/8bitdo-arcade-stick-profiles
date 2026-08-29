#!/usr/bin/env python3
"""stickctl tray - system-tray + global-hotkey profile switcher for the
8BitDo Arcade Stick.

Sits in the Windows notification area. Left-click (or right-click) the icon for
a menu of every profile - captured images in captures/ AND the Ultimate
Software ini profiles in profiles/, compiled on the fly. Click one to load it
onto the stick (~1s, read-back-verified). The active profile shows a check.

Global hotkeys: Ctrl+Alt+1 .. Ctrl+Alt+9, Ctrl+Alt+0 switch to the first ten
profiles in menu order (the number is shown in the menu).

Run:      pyw tray.py        (or stick-tray.cmd from the repo root)
Self-test: py tray.py --check
"""
import sys
import threading

import stickctl as ctl

APP = "8BitDo Stick"
HOTKEY_MODS = "ctrl+alt"


def profile_names():
    """Menu order: capture profiles first, then ini profiles (dedup by name)."""
    names = list(ctl.list_captures())
    for ini in ctl.list_inis():
        if ini.lower() not in (n.lower() for n in names):
            names.append(ini)
    return names


def make_icon_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 34, 58, 58], radius=8, fill=(35, 42, 54, 255),
                        outline=(226, 112, 90, 255), width=3)
    d.line([20, 40, 20, 18], fill=(226, 112, 90, 255), width=5)
    d.ellipse([12, 6, 28, 22], fill=(226, 112, 90, 255))
    d.ellipse([36, 40, 44, 48], fill=(245, 245, 245, 255))
    d.ellipse([48, 44, 56, 52], fill=(245, 245, 245, 255))
    return img


class TrayApp:
    def __init__(self):
        self.lock = threading.Lock()
        self.current = None          # name of profile on the stick, if known
        self.status = "not checked yet"
        self.icon = None

    # ------------------------------------------------------------- device
    def refresh_current(self):
        try:
            h = ctl.open_stick()
            blob = ctl.read_config(h)
            self.current = ctl.identify(blob)
            self.status = f"on stick: {ctl.profile_name(blob) or self.current or 'unknown'}"
        except SystemExit as e:
            self.current, self.status = None, "stick not connected"
        except Exception as e:
            self.current, self.status = None, f"error: {e}"

    def switch(self, name):
        if not self.lock.acquire(blocking=False):
            return  # a switch is already in flight
        try:
            kind, blob = ctl.resolve_profile(name)
            if blob is None:
                self.notify(f"profile '{name}' not found")
                return
            try:
                h = ctl.open_stick()
            except SystemExit:
                self.notify("stick not connected (USB, mode switch on X)")
                return
            try:
                if ctl.same_config(ctl.read_config(h), blob):
                    self.current = name
                    self.notify(f"'{name}' already loaded")
                    return
                ctl.write_config(h, blob)
                ok = ctl.same_config(ctl.read_config(h), blob)
            except Exception as e:
                self.notify(f"switch failed: {e}")
                return
            if ok:
                self.current = name
                self.status = f"on stick: {name}"
                self.notify(f"switched to '{name}'")
            else:
                self.notify(f"'{name}' written but read-back differs - re-sync in the app if odd")
        finally:
            self.lock.release()
            if self.icon:
                self.icon.update_menu()

    def switch_async(self, name):
        threading.Thread(target=self.switch, args=(name,), daemon=True).start()

    def notify(self, msg):
        if self.icon:
            try:
                self.icon.notify(msg, APP)
            except Exception:
                pass
        print(msg)

    # --------------------------------------------------------------- menu
    def build_menu(self):
        import pystray
        items = [pystray.MenuItem(lambda item: self.status, None, enabled=False)]
        names = profile_names()
        for i, name in enumerate(names):
            hk = f"  ({HOTKEY_MODS}+{(i + 1) % 10})" if i < 10 else ""
            items.append(pystray.MenuItem(
                f"{name}{hk}",
                (lambda n: lambda icon, item: self.switch_async(n))(name),
                checked=(lambda n: lambda item: self.current == n)(name),
                radio=True))
        items += [
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Refresh", lambda icon, item: threading.Thread(
                target=self._refresh_and_update, daemon=True).start()),
            pystray.MenuItem("Quit", lambda icon, item: icon.stop()),
        ]
        return pystray.Menu(*items)

    def _refresh_and_update(self):
        self.refresh_current()
        if self.icon:
            self.icon.update_menu()

    def register_hotkeys(self):
        try:
            import keyboard
        except ImportError:
            print("keyboard package missing - hotkeys disabled")
            return
        for i, name in enumerate(profile_names()[:10]):
            combo = f"{HOTKEY_MODS}+{(i + 1) % 10}"
            keyboard.add_hotkey(combo, (lambda n: lambda: self.switch_async(n))(name))

    def run(self):
        import pystray
        self.refresh_current()
        self.icon = pystray.Icon(APP, make_icon_image(), APP, menu=self.build_menu())
        self.register_hotkeys()
        self.icon.run()


def main():
    if "--check" in sys.argv:
        names = profile_names()
        print(f"{len(names)} profiles:", ", ".join(names))
        for name in names:
            kind, blob = ctl.resolve_profile(name)
            assert blob is not None and len(blob) == ctl.CONFIG_SIZE, name
        make_icon_image()
        import keyboard  # noqa: F401  (import check only)
        import pystray  # noqa: F401
        print("self-test OK (profiles compile, icon renders, deps import)")
        return 0
    TrayApp().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
