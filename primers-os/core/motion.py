"""
PRIMERS OS — reduced motion (``primers-reduce-motion on|off|status``).

The Primers mark's cursor blinks on the boot splash (1.06 s, in steps), and
GTK and web pages animate. With reduced motion on:

- the boot splash keeps the cursor still (the ``primers-still`` Plymouth
  theme; it takes effect from the next boot: the splash lives in the
  initramfs, which is rebuilt; a live USB keeps its own splash);
- GTK stops animating for everyone (``gtk-enable-animations=false`` in
  /etc/gtk-3.0/settings.ini), which also makes web pages in Primers Lite Bee
  see ``prefers-reduced-motion: reduce``.

Settings for one person (their own GTK settings.ini) still win over this.
"""

import os
import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence

THEMES = "/usr/share/plymouth/themes"
SPLASH = {True: f"{THEMES}/primers-still/primers-still.plymouth", False: f"{THEMES}/primers/primers.plymouth"}
GTK_KEY = "gtk-enable-animations"


class MotionError(Exception):
    pass


@dataclass
class MotionPaths:
    marker: str = "/etc/primers/reduced-motion"
    gtk3: str = "/etc/gtk-3.0/settings.ini"
    cmdline: str = "/proc/cmdline"


def _default_run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=600)


def gtk_settings_text(old: str, reduce: bool) -> str:
    """settings.ini with gtk-enable-animations set (reduce) or removed, the rest kept."""
    lines, in_settings, done, seen_settings = [], False, False, False
    for line in old.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            if in_settings and reduce and not done:
                lines.append(f"{GTK_KEY}=false")
                done = True
            in_settings = stripped == "[Settings]"
            seen_settings = seen_settings or in_settings
        elif in_settings and stripped.split("=", 1)[0].strip() == GTK_KEY:
            if reduce and not done:
                lines.append(f"{GTK_KEY}=false")
                done = True
            continue
        lines.append(line)
    if reduce and not done:
        if not in_settings:
            lines.append("[Settings]")
        lines.append(f"{GTK_KEY}=false")
    text = "\n".join(lines).strip("\n")
    return text + "\n" if text else ""


class Motion:
    def __init__(self, paths: MotionPaths = MotionPaths(),
                 run: Callable[[Sequence[str]], subprocess.CompletedProcess] = _default_run):
        self.paths, self.run = paths, run

    def reduced(self) -> bool:
        return os.path.exists(self.paths.marker)

    def live_session(self) -> bool:
        try:
            with open(self.paths.cmdline, encoding="utf-8") as f:
                return "boot=casper" in f.read().split()
        except OSError:
            return False

    def set(self, reduce: bool) -> str:
        """Turn reduced motion on or off; returns what the person should know."""
        # GTK, for everyone
        try:
            with open(self.paths.gtk3, encoding="utf-8") as f:
                old = f.read()
        except FileNotFoundError:
            old = ""
        new = gtk_settings_text(old, reduce)
        os.makedirs(os.path.dirname(self.paths.gtk3), exist_ok=True)
        if new:
            with open(self.paths.gtk3, "w", encoding="utf-8") as f:
                f.write(new)
        elif os.path.exists(self.paths.gtk3):
            os.unlink(self.paths.gtk3)
        # The boot splash
        r = self.run(["update-alternatives", "--set", "default.plymouth", SPLASH[reduce]])
        if r.returncode != 0:
            raise MotionError(f"couldn't switch the boot splash: {(r.stderr or r.stdout).strip()}")
        note = "The boot splash changes from the next boot."
        if self.live_session():
            note = "This live session keeps its boot splash; installed systems change it from the next boot."
        else:
            r = self.run(["update-initramfs", "-u"])
            if r.returncode != 0:
                raise MotionError(f"couldn't rebuild the boot files: {(r.stderr or r.stdout).strip()[-300:]}")
        # Remembered last, so 'status' only says on when everything is
        os.makedirs(os.path.dirname(self.paths.marker), exist_ok=True)
        if reduce:
            with open(self.paths.marker, "w", encoding="utf-8") as f:
                f.write("Reduced motion is on (primers-reduce-motion).\n")
        elif os.path.exists(self.paths.marker):
            os.unlink(self.paths.marker)
        return note
