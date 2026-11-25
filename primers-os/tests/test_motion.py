"""primers-reduce-motion: the still boot splash, GTK animations, the live case."""

import os
import subprocess

import pytest

from core import motion


class Run:
    def __init__(self, rc=0):
        self.calls, self.rc = [], rc

    def __call__(self, argv):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.rc, "", "" if self.rc == 0 else "failed")


@pytest.fixture
def m(tmp_path):
    (tmp_path / "cmdline").write_text("BOOT_IMAGE=/boot/vmlinuz root=UUID=1 ro quiet splash\n")
    paths = motion.MotionPaths(marker=str(tmp_path / "etc/primers/reduced-motion"),
                               gtk3=str(tmp_path / "etc/gtk-3.0/settings.ini"), cmdline=str(tmp_path / "cmdline"))
    mo = motion.Motion(paths, run=Run())
    return mo


def test_on_makes_the_splash_still_turns_gtk_animations_off_and_rebuilds_the_initramfs(m):
    assert not m.reduced()
    note = m.set(True)
    assert m.reduced() and "next boot" in note
    assert m.run.calls == [["update-alternatives", "--set", "default.plymouth", motion.SPLASH[True]],
                           ["update-initramfs", "-u"]]
    assert open(m.paths.gtk3).read() == "[Settings]\ngtk-enable-animations=false\n"
    assert motion.SPLASH[True].endswith("primers-still/primers-still.plymouth")


def test_off_restores_the_blinking_splash_and_keeps_other_gtk_settings(m):
    os.makedirs(os.path.dirname(m.paths.gtk3))
    with open(m.paths.gtk3, "w") as f:
        f.write("[Settings]\ngtk-theme-name=Adwaita-dark\n")
    m.set(True)
    assert "gtk-theme-name=Adwaita-dark" in open(m.paths.gtk3).read()
    m.run.calls.clear()
    m.set(False)
    assert not m.reduced()
    assert m.run.calls[0] == ["update-alternatives", "--set", "default.plymouth", motion.SPLASH[False]]
    assert open(m.paths.gtk3).read() == "[Settings]\ngtk-theme-name=Adwaita-dark\n"


def test_a_live_session_switches_without_rebuilding_the_live_usb(m):
    with open(m.paths.cmdline, "w") as f:
        f.write("BOOT_IMAGE=/casper/vmlinuz boot=casper quiet splash ---\n")
    note = m.set(True)
    assert ["update-initramfs", "-u"] not in m.run.calls and "live session" in note


def test_a_failure_leaves_it_off(m):
    m.run = Run(rc=1)
    with pytest.raises(motion.MotionError):
        m.set(True)
    assert not m.reduced()


@pytest.mark.parametrize("old,reduce,want", [
    ("", True, "[Settings]\ngtk-enable-animations=false\n"),
    ("[Settings]\ngtk-enable-animations=true\nx=1\n", True, "[Settings]\ngtk-enable-animations=false\nx=1\n"),
    ("[Settings]\nx=1\ngtk-enable-animations=false\n", False, "[Settings]\nx=1\n"),
    ("[Settings]\ngtk-enable-animations=false\n", False, "[Settings]\n"),
    ("", False, ""),
])
def test_gtk_settings_text(old, reduce, want):
    assert motion.gtk_settings_text(old, reduce) == want


def test_both_splash_themes_are_built_from_the_official_artwork():
    hook = open(os.path.join(os.path.dirname(__file__), "..", "..", "primers-distro", "config", "hooks", "chroot",
                             "0050-configure-desktop.hook.chroot")).read()
    assert 'icon = load("app-icon-1024.png")' in hook and 'lockup = load("lockup-horizontal-dark.png")' in hook
    assert '("primers", [on] * 16 + [off] * 16), ("primers-still", [on] * 32)' in hook
    assert "primers-still/primers-still.plymouth 150" in hook
    assert "BackgroundStartColor=0x12161c" in hook
