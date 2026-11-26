#!/usr/bin/env python3
"""
End-to-end tests of PRIMERS OS in a virtual machine.

  run_vm_tests.py exam-escape --iso primers-os.iso --out results/
  run_vm_tests.py exam-power-cut --iso primers-os.iso --out results/
  run_vm_tests.py installed --firmware sb --iso primers-os.iso --out results/

Boots the ISO in QEMU (KVM when available), drives the keyboard through
QMP, checks the guest through qemu-guest-agent, and serves a demo exam site
from this machine (the guest reaches it as 10.0.2.2). Writes results.json
and screenshots to --out and exits non-zero if any check fails.
"""

import argparse
import functools
import http.server
import json
import os
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vmlib import VM, VMError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EXAM_PORT = 8765
EXAM_HOST = "cbt.primers.test"
EXAM_URL = f"http://{EXAM_HOST}:{EXAM_PORT}/exam.html"
CDN_HOST, CDN_PORT, CDN_OLD, CDN_NEW = "cdn.primers.test", 8770, "10.0.2.100", "10.0.2.101"
V6_HOST, V6_PORT, V6_OTHER_PORT = "cbt6.primers.test", 8771, 8772
MOODLE_HOST, MOODLE_PORT = "moodle.primers.test", 8780     # tests/cbt/moodle/setup.sh, on this machine
MOODLE_BLUE = (15, 108, 191)                                 # Moodle 4.5 (Boost) primary buttons
MOODLE_QUESTION = (230, 242, 245)                            # the box around each question
TCEXAM_HOST, TCEXAM_PORT = "tcexam.primers.test", 8781       # tests/cbt/tcexam/setup.sh, on this machine
TCEXAM_BLUE = (0, 51, 153)            # TCExam 17's title bar: page positions are measured from its top
TCEXAM_GO = (170, 255, 170)           # the green 'execute' button on its test list
TCEXAM_WARN = (153, 255, 153)         # the box asking to confirm the end of the test
TCEXAM_BUTTON = (211, 211, 211)       # its grey 'execute' / 'cancel' buttons
GUEST_HOST6 = "fec0::2"              # the host, as the VM sees it over IPv6 (QEMU user networking)
HOST_IPV6 = True                     # can this machine serve over IPv6 (::1)?
STAFF_PASSWORD = "vm-test-staff"      # a throwaway VM's account, not a secret
INSTALLER = "calamares"               # how the 'installed' scenario installs (--installer)


class _V6Server(http.server.ThreadingHTTPServer):
    address_family = __import__("socket").AF_INET6


def serve(directory: str, port: int, host: str = "127.0.0.1") -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *a: None
    server = (_V6Server if ":" in host else http.server.ThreadingHTTPServer)((host, port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


class Suite:
    def __init__(self, vm: VM, out: str):
        self.vm, self.out = vm, out
        self.results = []

    def note(self, text: str) -> None:
        """Something worth recording that is not a pass/fail check."""
        self.results.append({"note": text})
        print(f"  NOTE  {text}", flush=True)

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append({"test": name, "passed": bool(ok), "detail": detail})
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""), flush=True)
        return ok

    def run_step(self, name, fn):
        try:
            fn()
        except Exception as e:          # a broken step is a failed test, never a skipped one
            self.check(name, False, f"{type(e).__name__}: {e}")
            traceback.print_exc()

    def save(self) -> bool:
        with open(os.path.join(self.out, "results.json"), "w") as f:
            json.dump(self.results, f, indent=2)
        checks = [r for r in self.results if "test" in r]
        failed = [r for r in checks if not r["passed"]]
        print(f"\n{len(checks) - len(failed)} passed, {len(failed)} failed")
        return not failed


# ------------------------------------------------------------------ #
#  Exam Mode escape routes (ADR 0003)
# ------------------------------------------------------------------ #

def kiosk_pid(vm: VM) -> str:
    return vm.sh("pgrep -u lab -f 'litebee --kiosk' | head -n1").out.strip()


def screen_drawn(vm: VM) -> bool:
    """Something is on the screen (not a blank display that is still starting)."""
    path = vm.screenshot("_screen-check")
    try:
        from PIL import Image
    except ImportError:
        return True
    with Image.open(path) as img:
        return len(set(img.convert("RGB").resize((64, 40)).getdata())) > 12


def greeter_requests(vm: VM) -> int:
    out = vm.sh("grep -c 'Greeter requests' /var/log/lightdm/lightdm.log").out.strip()
    return int(out) if out.isdigit() else 0


def lab_desktop_pid(vm: VM) -> str:
    return vm.sh("pgrep -u lab -x openbox | head -n1").out.strip()


def prefer_lab_at_login(vm: VM) -> None:
    """The login screen lists the administrator and lab: have it select lab,
    as it does once lab has signed in there. Written while the login screen
    is stopped: it saves its own choice when it stops. (During an exam,
    Exam Mode does this itself.)"""
    vm.sh("systemctl stop display-manager.service; d=/var/lib/lightdm/.cache/lightdm-gtk-greeter && "
          "install -d -o lightdm -g lightdm \"$d\" && printf '[greeter]\\nlast-user=lab\\n' > \"$d/state\" && "
          "chown lightdm:lightdm \"$d/state\"; systemctl start display-manager.service", timeout=180)


def sign_in_lab(vm: VM, suite: Suite, shot: str, signed_in=kiosk_pid) -> str:
    """Sign in to the lab account at the login screen, with the keyboard.
    Keys sent before the login screen is drawn are lost (slow under
    emulation), so wait for it to be on screen, and check LightDM got the
    sign-in; the retries use different keys because the first Tab or Enter
    may or may not have landed."""
    vm.wait_until(lambda: vm.sh("pgrep -u lightdm -f lightdm-gtk-greeter").rc == 0, 300, "login screen")
    vm.wait_until(lambda: screen_drawn(vm), 300, "the login screen to be drawn")
    time.sleep(3)
    for keys in (["tab", "ret"], ["ret"], ["esc", "tab", "ret"]):
        before = greeter_requests(vm)
        for k in keys:
            vm.key(k)
            time.sleep(0.5)
        try:
            vm.wait_until(lambda: greeter_requests(vm) > before or bool(signed_in(vm)), 45, "the sign-in")
            break
        except VMError:
            vm.screenshot(f"{shot}-sign-in-retry")
    vm.wait_until(lambda: bool(signed_in(vm)), 300, "the lab session")
    time.sleep(8)
    vm.screenshot(shot)
    return signed_in(vm)


def exam_escape(vm: VM, suite: Suite) -> None:
    c = suite.check
    vm.start()
    vm.wait_agent(timeout=1200)
    vm.wait_until(lambda: vm.sh("pgrep -x openbox").rc == 0, 600, "the live desktop")
    vm.screenshot("01-live-desktop")

    # Campus setup: the exam server has a name, Lab Mode is on (the boot
    # step is what grants the lab account its passwordless sign-in)
    r = vm.sh(f"echo '10.0.2.2 {EXAM_HOST}' >> /etc/hosts && primers-lab enable && "
              "systemctl start primers-lab-reset.service")
    c("setup: Lab Mode enabled", r.rc == 0, r.err)

    # The live user signs out; starting the exam restarts the login screen locked
    vm.sh("loginctl terminate-user primers")
    vm.wait_until(lambda: vm.sh("pgrep -u primers -x openbox").rc != 0, 60, "sign-out")
    escape_checks(vm, suite)


def escape_checks(vm: VM, suite: Suite, installed: bool = False) -> None:
    """Every escape route of ADR 0003, from starting the exam to stopping it.
    Needs Lab Mode on, the exam server's name in /etc/hosts and nobody
    signed in to the desktop."""
    c = suite.check
    r = vm.sh(f"primers-exam start {EXAM_URL}", timeout=900)
    c("setup: exam started", r.rc == 0 and "sign out of the desktop" not in r.err, r.out + r.err)
    r = vm.sh("primers-exam status")
    c("setup: firewall, USB block and console lock in place", r.rc == 0, r.out)
    if installed:
        c("the boot menu is locked on the installed system", "Boot menu:  locked" in r.out, r.out)

    kiosk = sign_in_lab(vm, suite, "02-kiosk")
    c("setup: candidate signs in to the kiosk", bool(kiosk))
    c("no desktop: no panel, file manager or terminal in the exam session",
      vm.sh("pgrep -u lab -x 'tint2|pcmanfm|xterm|openbox-session'").rc != 0)

    # 1. Text consoles, Ctrl+Alt+Backspace, Magic SysRq
    vt = vm.sh("fgconsole").out.strip()
    for n in range(1, 13):
        vm.key(f"ctrl-alt-f{n}")
        time.sleep(0.3)
    time.sleep(2)
    c("Ctrl+Alt+F1..F12 do not switch away from the exam", vm.sh("fgconsole").out.strip() == vt,
      f"was {vt}, now {vm.sh('fgconsole').out.strip()}")
    vm.key("ctrl-alt-backspace")
    time.sleep(4)
    c("Ctrl+Alt+Backspace does not end the exam", kiosk_pid(vm) == kiosk)
    c("Magic SysRq is off", vm.sh("cat /proc/sys/kernel/sysrq").out.strip() == "0")
    before = vm.sh("dmesg | grep -c 'sysrq:'").out.strip()
    vm.key("alt-sysrq-h")
    time.sleep(2)
    c("Alt+SysRq keys do nothing", vm.sh("dmesg | grep -c 'sysrq:'").out.strip() == before)
    c("no login prompts on text consoles",
      vm.sh("systemctl show -p LoadState --value getty@tty2.service").out.strip() == "masked"
      and vm.sh("pgrep -x agetty").rc != 0, vm.sh("pgrep -a agetty").out)

    # 2. Screenshots and screen recording
    vm.sh("touch /run/exam-marker")
    vm.key("print")
    vm.key("alt-print")
    vm.key("ctrl-print")
    time.sleep(3)
    shots = vm.sh("find /home/lab /tmp -newer /run/exam-marker -name '*.png' 2>/dev/null").out.strip()
    c("Print Screen saves nothing", not shots and vm.sh("pgrep -u lab -x 'scrot|obs|import'").rc != 0, shots)

    # 3. Clipboard: whatever is copied in a session doesn't survive it
    r = vm.as_user("lab", "printf secret-notes | xsel --clipboard --input && xsel --clipboard --output")
    c("setup: clipboard usable inside the exam", r.out == "secret-notes", repr(r))

    # 4. Kiosk killed: the session ends, back to the login screen, no desktop
    vm.sh(f"kill -KILL {kiosk}")
    desktop_seen, ended, deadline = [], False, time.time() + 240
    while time.time() < deadline:
        seen = vm.sh("pgrep -u lab -a -x 'tint2|pcmanfm|xterm|openbox-session|primers-terminal|lite-bee'").out
        if seen.strip():
            desktop_seen.append(seen.strip())
        if vm.sh("pgrep -u lab").rc != 0 and vm.sh("pgrep -u lightdm -f lightdm-gtk-greeter").rc == 0:
            ended = True
            break
        time.sleep(2)
    c("a killed kiosk ends the session and the login screen returns", ended,
      "lab processes or no login screen after 240 s")
    c("no desktop or second kiosk ever appears after the kill", not desktop_seen, "; ".join(desktop_seen))
    c("the log records the stopped kiosk",
      "stopped unexpectedly" in vm.sh("journalctl -t primers-exam --no-pager").out)
    c("the durable exam log has it too (copied from the journal)",
      "stopped unexpectedly" in vm.sh("cat /var/log/primers/exam.jsonl").out)
    vm.screenshot("03-after-kill")

    kiosk = sign_in_lab(vm, suite, "04-kiosk-again")
    r = vm.as_user("lab", "xsel --clipboard --output; xsel --primary --output")
    c("clipboard is empty in the next session", r.out == "", repr(r.out))

    # 5. Clock
    year = vm.sh("date +%Y").out.strip()
    r1 = vm.run(["runuser", "-u", "lab", "--", "timedatectl", "set-time", "2031-01-01 00:00:00"])
    r2 = vm.run(["runuser", "-u", "lab", "--", "date", "-s", "2031-01-01"])
    c("the lab account can't change the clock", r1.rc != 0 and r2.rc != 0 and
      vm.sh("date +%Y").out.strip() == year, f"{r1} {r2}")

    # 6. DNS: no resolver, other DNS servers, DoT, DoH or mDNS for the lab account
    pinned = vm.run(["runuser", "-u", "lab", "--", "getent", "hosts", EXAM_HOST])
    c("the exam server's name works (pinned)", pinned.rc == 0 and "10.0.2.2" in pinned.out, repr(pinned))
    other = vm.run(["runuser", "-u", "lab", "--", "getent", "hosts", "example.com"])
    c("no other names can be looked up", other.rc != 0, repr(other))
    udp = ("import socket,sys\nfor h,p in (('127.0.0.53',53),('1.1.1.1',53),('8.8.8.8',853),('224.0.0.251',5353)):\n"
           " s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)\n try:\n  s.sendto(b'x',(h,p)); print('SENT',h,p)\n"
           " except OSError as e: print('blocked',h,p)\n")
    r = vm.run(["runuser", "-u", "lab", "--", "python3", "-c", udp])
    c("DNS to the system resolver, other servers, DoT and mDNS is blocked", "SENT" not in r.out, r.out)
    r = vm.run(["runuser", "-u", "lab", "--", "curl", "-s", "-m", "8", "-o", "/dev/null", "-w", "%{http_code}",
                "https://1.1.1.1/dns-query?name=example.com"])
    c("DNS over HTTPS is blocked", r.out in ("000", ""), repr(r))
    r = vm.run(["runuser", "-u", "lab", "--", "curl", "-s", "-m", "8", "-o", "/dev/null", "-w", "%{http_code}",
                EXAM_URL])
    c("the exam server is still reachable", r.out == "200", repr(r))

    # 7. No shell, sudo, su or pkexec
    shell = vm.sh("getent passwd lab | cut -d: -f7").out.strip()
    c("the lab account's shell refuses to run", shell == "/usr/lib/primers/exam-shell"
      and vm.run(["su", "lab", "-c", "true"]).rc != 0, shell)
    c("no sudo", vm.run(["runuser", "-u", "lab", "--", "sudo", "-n", "true"]).rc != 0)
    c("no su", vm.sh("runuser -u lab -- su -c true root </dev/null").rc != 0)
    c("no pkexec", vm.run(["runuser", "-u", "lab", "--", "pkexec", "--disable-internal-agent", "true"]).rc != 0)

    # 8. Stopping the exam puts everything back
    r = vm.sh("primers-exam stop", timeout=900)
    c("exam stops", r.rc == 0, r.out + r.err)
    state = vm.sh("getent passwd lab | cut -d: -f7; cat /proc/sys/kernel/sysrq; "
                  "systemctl show -p LoadState --value getty@tty2.service; "
                  "grep -c primers-exam /etc/hosts; ls /etc/X11/xorg.conf.d/ /etc/sysctl.d/ | grep -c primers-exam")
    lines = state.out.split()
    c("after the exam: shell, SysRq, consoles, hosts and display settings restored",
      lines[:3] == ["/bin/bash", "176", "loaded"] and lines[3:] == ["0", "0"], state.out)


# ------------------------------------------------------------------ #
#  Exam Mode across a power cut (ADR 0004), on an installed system
# ------------------------------------------------------------------ #

def _monotonic(vm: VM, unit: str, prop: str) -> int:
    out = vm.sh(f"systemctl show -p {prop} --value {unit}").out.strip()
    return int(out) if out.isdigit() else 0


def exam_power_cut(vm: VM, suite: Suite) -> None:
    c = suite.check
    subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", vm.disk, "24G"], check=True)

    # 1. Install from the live session (the installer's steps, scripted)
    vm.start()
    vm.wait_agent(timeout=1200)
    vm.wait_until(lambda: vm.sh("pgrep -x openbox").rc == 0, 600, "the live desktop")
    with open(os.path.join(HERE, "install.sh"), encoding="utf-8") as f:
        script = f.read()
    r = vm.run(["/bin/bash", "-s", "/dev/vda", STAFF_PASSWORD], timeout=2400, input_text=script)
    if not c("install: PRIMERS OS installed on the VM's disk", r.rc == 0 and "installed on /dev/vda" in r.out,
             (r.out + r.err)[-3000:]):
        return
    vm.stop()

    # 2. The installed system: Lab Mode, an exam, a candidate signed in
    vm.iso = None
    vm.start()
    vm.wait_agent(timeout=900)
    root = vm.sh("findmnt -n -o SOURCE /").out.strip()
    c("the installed system boots from its own disk", root == "/dev/vda1" and
      "boot=casper" not in vm.sh("cat /proc/cmdline").out, root)
    # Test-only: GRUB also on the serial port, and its menu shown (installed
    # systems hide it), so the test can read the menu and press keys at it
    r = vm.sh("printf 'GRUB_TERMINAL=\"console serial\"\\nGRUB_SERIAL_COMMAND=\"serial --unit=0 --speed=115200\"\\n"
              "GRUB_TIMEOUT_STYLE=menu\\nGRUB_TIMEOUT=5\\n'"
              " > /etc/default/grub.d/99-vm-test-serial.cfg && update-grub", timeout=300)
    c("setup: boot menu on the serial port (test only)", r.rc == 0, r.err)
    r = vm.sh(f"echo '10.0.2.2 {EXAM_HOST}' >> /etc/hosts && primers-lab enable && "
              "systemctl start primers-lab-reset.service")
    c("setup: Lab Mode enabled", r.rc == 0, r.err)
    prefer_lab_at_login(vm)
    r = vm.sh(f"primers-exam start {EXAM_URL}", timeout=900)
    c("setup: exam started", r.rc == 0, r.out + r.err)
    st = vm.sh("primers-exam status")
    c("the boot menu is locked during the exam", st.rc == 0 and "Boot menu:  locked" in st.out, st.out)
    cfg = vm.sh("cat /boot/grub/grub.cfg").out
    entries = [line.strip() for line in cfg.splitlines() if line.strip().startswith(("menuentry ", "submenu "))]
    c("boot menu: a password is set; only the normal entry boots without it; no recovery mode",
      'set superusers="primers-exam"' in cfg and bool(entries) and "--unrestricted" in entries[0]
      and sum("--unrestricted" in e for e in entries) == 1 and "(recovery mode)" not in cfg,
      "\n".join(entries))
    r = vm.sh("grub-script-check /boot/grub/grub.cfg")
    c("the locked grub.cfg is valid GRUB script", r.rc == 0, r.out + r.err)

    kiosk = sign_in_lab(vm, suite, "pc-01-kiosk")
    c("setup: candidate signs in to the kiosk", bool(kiosk))
    marker = f"vm-test candidate event {int(time.time())}"
    vm.as_user("lab", f"logger -t primers-exam '{marker}'")
    time.sleep(1)
    before = vm.sh("cat /var/log/primers/exam.jsonl").out
    vm.screenshot("pc-02-before-power-cut")

    # 3. Pull the plug, one second after the candidate's last event
    vm.power_cut()
    mark = vm.serial_size()
    vm.start()
    # After an unclean shutdown the boot menu stays up: try to edit the entry
    vm.wait_until(lambda: "GNU GRUB" in vm.serial_text(mark), 120, "the boot menu", interval=0.5)
    time.sleep(1)
    vm.key("e")
    time.sleep(3)
    prompt = vm.serial_text(mark)
    vm.screenshot("pc-03-edit-asks-for-password")
    c("pressing e in the boot menu asks for a password instead of opening the editor",
      "Enter username" in prompt, prompt[-600:])
    vm.type("root\n")
    time.sleep(1)
    vm.type("guess\n")
    time.sleep(3)
    denied = vm.serial_text(mark)
    for _ in range(2):
        vm.key("ret")
        time.sleep(2)
    c("a wrong password is refused", "denied" in denied.lower() or "Access" in denied, denied[-600:])
    vm.wait_agent(timeout=900)
    c("the PC then boots normally (the normal entry needs no password)", True)

    # 4. Back on: still in Exam Mode, locks in place before anyone signs in
    st = vm.sh("primers-exam status")
    c("after the power cut the PC is still in Exam Mode with every lock in place",
      st.rc == 0 and "Exam Mode: ON" in st.out, st.out)
    reset_done = _monotonic(vm, "primers-lab-reset.service", "ExecMainExitTimestampMonotonic")
    dm_start = _monotonic(vm, "lightdm.service", "ExecMainStartTimestampMonotonic")
    c("the exam firewall was back before the login screen started", 0 < reset_done <= dm_start,
      f"lab reset done at {reset_done}, login screen started at {dm_start}")
    # Before any network interface came up: the early firewall unit finished
    # (with the exam table in place) before NetworkManager started, and the
    # login screen no longer waits for the network
    fw_done = _monotonic(vm, "primers-exam-firewall.service", "ExecMainExitTimestampMonotonic")
    nm_start = _monotonic(vm, "NetworkManager.service", "ExecMainStartTimestampMonotonic")
    fw = vm.sh("systemctl show -p Result --value primers-exam-firewall.service; "
               "journalctl -b -o cat -t primers-exam | grep -c 'before the network came up'").out.split()
    c("the exam firewall was in place before any network interface came up (before NetworkManager started)",
      0 < fw_done <= nm_start and fw[:1] == ["success"] and fw[-1:] != ["0"],
      f"firewall done at {fw_done}, NetworkManager started at {nm_start}; {fw}")
    after = vm.sh("systemctl list-dependencies --after --all --plain --no-pager display-manager.service").out
    netdeps = sorted({u.strip() for u in after.split() if u.strip() in
                      ("network.target", "network-online.target", "NetworkManager.service",
                       "NetworkManager-wait-online.service")})
    c("the login screen doesn't wait for the network (no network or wait-online units before it)",
      bool(after.strip()) and not netdeps, ", ".join(netdeps) or after[-300:])
    c("consoles and SysRq still locked after the reboot",
      vm.sh("cat /proc/sys/kernel/sysrq").out.strip() == "0"
      and vm.sh("systemctl show -p LoadState --value getty@tty2.service").out.strip() == "masked"
      and vm.sh("pgrep -x agetty").rc != 0)
    log = vm.sh("cat /var/log/primers/exam.jsonl").out
    c("the candidate's last event, a second before the cut, is in the exam log", marker in log,
      f"in the log before the cut: {marker in before}")
    c("the exam log kept the exam start and the session start",
      "exam started:" in log and "exam session started" in log)
    shown = vm.sh("primers-exam log").out
    c("primers-exam log shows the events from before the cut", marker in shown, shown[-800:])
    suite.note("journald kept the event too" if marker in vm.sh("journalctl -t primers-exam --no-pager").out
               else "journald lost the event in the power cut; the exam log has it")

    kiosk = sign_in_lab(vm, suite, "pc-04-kiosk-after-power-cut")
    c("after the reboot, signing in opens the exam kiosk again", bool(kiosk))
    r = vm.run(["runuser", "-u", "lab", "--", "curl", "-s", "-m", "8", "-o", "/dev/null", "-w", "%{http_code}",
                "https://1.1.1.1/"])
    c("after the reboot the lab account still reaches nothing but the exam", r.out in ("000", ""), repr(r))
    r = vm.run(["runuser", "-u", "lab", "--", "curl", "-s", "-m", "8", "-o", "/dev/null", "-w", "%{http_code}",
                EXAM_URL])
    c("after the reboot the exam server is reachable", r.out == "200", repr(r))

    # 5. Stopping the exam unlocks everything, boot menu included
    r = vm.sh("primers-exam stop", timeout=900)
    cfg = vm.sh("cat /boot/grub/grub.cfg").out
    c("stopping the exam unlocks the boot menu", r.rc == 0 and "superusers" not in cfg
      and "--unrestricted" not in cfg and "(recovery mode)" in cfg, r.out + r.err)
    st = vm.sh("primers-exam status")
    c("Exam Mode is off after stop", "Exam Mode: off" in st.out, st.out)


# ------------------------------------------------------------------ #
#  Installed systems: BIOS, and UEFI with Secure Boot enforced
# ------------------------------------------------------------------ #

def install_from_live(vm: VM, suite: Suite) -> bool:
    """Boot the live ISO, install on the VM's disk, boot the installed system."""
    subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", vm.disk, "24G"], check=True)
    vm.start()
    vm.wait_agent(timeout=1200)
    vm.wait_until(lambda: vm.sh("pgrep -x openbox").rc == 0, 600, "the live desktop")
    with open(os.path.join(HERE, "install.sh"), encoding="utf-8") as f:
        script = f.read()
    if INSTALLER == "calamares":
        vm.wait_until(lambda: screen_drawn(vm), 300, "the live desktop to be drawn")
        time.sleep(10)
        if not install_with_installer(vm, suite):
            return False
        if not restart_from_installer(vm, suite):
            return False
        vm.iso = None                   # taken out: later starts of this VM boot the disk only
    else:
        r = vm.run(["/bin/bash", "-s", "/dev/vda", STAFF_PASSWORD], timeout=2400, input_text=script)
        if not suite.check(f"install ({vm.firmware}): PRIMERS OS installed on the VM's disk",
                           r.rc == 0 and "installed on /dev/vda" in r.out, (r.out + r.err)[-3000:]):
            return False
        vm.stop()
        vm.iso = None
        vm.start()
        vm.wait_agent(timeout=900)
    root = vm.sh("findmnt -n -o SOURCE /").out.strip()
    ok = suite.check("the installed system boots from its own disk",
                     root.startswith("/dev/vda") and "boot=casper" not in vm.sh("cat /proc/cmdline").out, root)
    if INSTALLER == "calamares":
        who = vm.sh("id -nG labadmin; hostname; dpkg -l casper calamares 2>/dev/null | grep -c '^ii'; "
                    "test -s /etc/machine-id && echo machine-id").out.split("\n")
        suite.check("the installed system has no installer correction in front of sfdisk",
                    vm.sh("test -e /usr/local/sbin/sfdisk").rc != 0 and
                    vm.sh("systemctl is-active primers-installer-fixes.service").out.strip() != "active")
        suite.check("the installer made the administrator (sudo), named the PC, removed the live "
                    "tools and gave the PC its own machine id",
                    "sudo" in who[0].split() and who[1] == "labadmin-primers" and who[2] == "0"
                    and "machine-id" in who, repr(who))
    return ok


# Where things are in the installer's window (Calamares, 1024x640 client
# area, the same at any screen size), measured from screenshots
INSTALLER_TITLE = "PRIMERS OS Installer"
ERASE_DISK = (172, 61)          # partition page: "Erase disk"
LOGIN_MARK = (374, 101)         # users page: inside the tick (green) or cross (red) by the login name
PASSWORD = (264, 210)
PASSWORD_AGAIN = (470, 210)
PASSWORD_MARK = (580, 210)      # inside the tick (green) or cross (red) after the passwords


def window_origin(vm: VM, title: str):
    """Absolute top-left of a window on the live desktop, and the screen size."""
    info = vm.as_user("primers", f"xwininfo -name '{title}'").out
    x = y = None
    for line in info.splitlines():
        if "Absolute upper-left X:" in line:
            x = int(line.split(":")[1])
        elif "Absolute upper-left Y:" in line:
            y = int(line.split(":")[1])
    dims = vm.as_user("primers", "xdpyinfo | awk '/dimensions:/ {print $2}'").out.strip()
    w, h = (int(v) for v in dims.split("x")) if "x" in dims else (1024, 768)
    if x is None or y is None:
        raise VMError(f"no window '{title}'")
    return x, y, w, h


def pixel(vm: VM, shot: str, x: int, y: int):
    from PIL import Image
    with Image.open(vm.screenshot(shot)) as img:
        return img.convert("RGB").getpixel((x, y))


def reddish(rgb) -> bool:
    r, g, b = rgb
    return r > 150 and r > g + 60 and r > b + 60


def greenish(rgb) -> bool:
    r, g, b = rgb
    return g > 120 and g > r + 40


def install_with_installer(vm: VM, suite: Suite) -> bool:
    """Install the way a person does: the installer (Calamares) from the live
    desktop, Erase disk, an administrator account, Install now."""
    c = suite.check
    slow = 1 if VM.kvm() else 4
    vm.as_user("primers", "xset s off -dpms; xset s reset")      # screenshots, not a blank screen
    # The live session puts the installer's sfdisk correction in front of
    # sfdisk (Calamares 3.2.61 overruns the end of GPT disks)
    shim = vm.sh("readlink /usr/local/sbin/sfdisk").out.strip()
    c("live session: the installer's GPT correction is in place", shim == "/usr/lib/primers/installer/sfdisk", shim)
    vm.as_user("primers", "nohup sudo -E calamares -d > /tmp/calamares.out 2>&1 &")
    vm.wait_until(lambda: INSTALLER_TITLE in vm.as_user("primers", "xwininfo -root -tree").out, 600, "the installer")
    time.sleep(10 * slow)
    x0, y0, w, h = window_origin(vm, INSTALLER_TITLE)
    at = lambda p: (x0 + p[0], y0 + p[1])  # noqa: E731
    vm.screenshot("installer-01-welcome")
    for _ in range(3):                  # welcome, location, keyboard
        vm.key("alt-n")
        time.sleep(6 * slow)
    vm.screenshot("installer-02-partitions")
    vm.click(*at(ERASE_DISK), w, h)
    time.sleep(6 * slow)
    vm.screenshot("installer-03-erase-disk")
    vm.key("alt-n")
    time.sleep(6 * slow)
    # The login names the system uses are refused (the field starts focused)
    vm.type_then_settle("Lab")
    time.sleep(3 * slow)
    mark = pixel(vm, "installer-04-login-lab-refused", *at(LOGIN_MARK))
    c("the installer refuses 'lab' as the administrator's login name", reddish(mark), f"mark colour {mark}")
    vm.key("ctrl-a")
    vm.type_then_settle("Labadmin")
    time.sleep(3 * slow)
    mark = pixel(vm, "installer-05-login-labadmin", *at(LOGIN_MARK))
    c("the installer accepts 'labadmin'", greenish(mark), f"mark colour {mark}")
    vm.click(*at(PASSWORD), w, h)
    time.sleep(1)
    vm.type_then_settle(STAFF_PASSWORD)
    vm.click(*at(PASSWORD_AGAIN), w, h)
    time.sleep(1)
    vm.type_then_settle(STAFF_PASSWORD)
    time.sleep(3 * slow)
    mark = pixel(vm, "installer-06-users", *at(PASSWORD_MARK))
    if not c("setup: both passwords typed and matching", greenish(mark), f"mark colour {mark}"):
        return False
    vm.key("alt-n")
    time.sleep(6 * slow)
    vm.screenshot("installer-07-summary")
    vm.key("alt-i")                     # Install
    time.sleep(5 * slow)
    vm.screenshot("installer-08-confirm")
    vm.key("ret")                       # Install now
    try:
        return _installer_runs(vm, suite, slow)
    finally:
        # The installer's own debug log, and what the GPT correction did, whatever happened
        for name, cmd in (("installer-session.log", "cat /home/primers/.cache/calamares/session.log"),
                          ("installer-journal.log", "journalctl -b -t primers-installer --no-pager")):
            with open(os.path.join(suite.out, name), "w", encoding="utf-8") as f:
                f.write(vm.sh(cmd).out)


def installer_failed(vm: VM) -> bool:
    windows = vm.as_user("primers", "xwininfo -root -tree").out
    return "Installation Failed" in windows or '"Error"' in windows


def _installer_runs(vm: VM, suite: Suite, slow: int) -> bool:
    c = suite.check
    # Installing. Done when the new system has its boot loader and the
    # administrator, and no install step is still running. (The installer
    # can leave its target mounted after "All done"; the restart unmounts it.)
    vm.wait_until(lambda: installer_failed(vm) or
                  vm.sh("findmnt -rn -o TARGET | grep -q calamares-root").rc == 0, 600, "the installer to start")
    vm.screenshot("installer-09-installing")
    if installer_failed(vm):
        log = vm.sh("grep -n -i -B2 -A12 'sfdisk\\|error\\|failed' /home/primers/.cache/calamares/session.log "
                    "| tail -n 80").out
        return c("install with the installer: finished without errors", False, "installer failed:\n" + log)
    busy = "pgrep -x 'unsquashfs|grub-install|grub-mkconfig|update-grub|update-initramfs|mkinitramfs|apt-get|dpkg'"
    installed = ("t=$(findmnt -rn -o TARGET | grep calamares-root | head -n1); [ -z \"$t\" ] || "
                 "{ test -s \"$t/boot/grub/grub.cfg\" && grep -q '^labadmin:' \"$t/etc/passwd\" && ! " + busy + "; }")
    deadline = time.time() + 3600 * slow
    failed, settled = False, 0
    while time.time() < deadline and settled < 3:
        if installer_failed(vm):
            failed = True
            break
        settled = settled + 1 if vm.sh(installed).rc == 0 else 0
        time.sleep(10)
    vm.sh("sync")
    time.sleep(5)
    vm.as_user("primers", "xset s reset")
    vm.screenshot("installer-10-finished")
    log = vm.sh("grep -n -i -B2 -A12 'error\\|failed' /home/primers/.cache/calamares/session.log | tail -n 80").out
    return c("install with the installer: finished without errors", not failed and settled >= 3 and
             vm.sh("pgrep -x calamares").rc == 0, log or "did not finish")


def restart_from_installer(vm: VM, suite: Suite) -> bool:
    """What a person does at the end: leave 'Restart now' ticked and press
    Done; when the live system asks for the installation medium to be
    removed, take it out and press Enter; the PC starts the installed
    system."""
    before = vm.boot_id()
    vm.screenshot("installer-11-restart-now")
    vm.key("alt-d")                                     # Done ('Restart now' is ticked by default)
    deadline, gone, ejected = time.time() + 900, None, False
    while time.time() < deadline:
        time.sleep(5)
        if gone is None:
            try:
                vm.sh("true", timeout=10)
                continue                                # still the live system
            except (VMError, OSError):
                gone = time.time()                      # it is shutting down
                vm.log(f"[{vm.name}] the live system is restarting")
        if not ejected and time.time() - gone > 20:
            # The medium comes out when the live system asks (it ejects it itself
            # first); with the virtual CD the test takes it out of the drive
            try:
                vm.qmp.call("eject", device="cd0", force=True)
            except VMError:
                pass
            ejected = True
            vm.screenshot("installer-12-remove-medium")
        if ejected:
            vm.key("ret")                               # "...then press ENTER"
            try:
                vm.wait_agent(timeout=10)
                if vm.boot_id() not in ("", before):
                    break
            except (VMError, OSError):
                pass
    root = ""
    try:
        root = vm.sh("findmnt -n -o SOURCE /; grep -c boot=casper /proc/cmdline").out
    except (VMError, OSError):
        pass
    return suite.check("the installer's 'Restart now' starts the installed system (medium removed when asked)",
                       root.startswith("/dev/vda") and root.strip().endswith("0"), root or "no new boot")


def restart_to_login(vm: VM) -> None:
    """Restart, then wait for the login screen: the guest agent is back early
    in the boot, before the Lab Mode boot service (ordered before the login
    screen) has finished."""
    vm.reboot()
    vm.wait_until(lambda: vm.sh("systemctl is-active display-manager.service").out.strip() == "active",
                  600, "the login screen after the restart")


SECURE_BOOT_VAR = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"


def installed_system(vm: VM, suite: Suite) -> None:
    c = suite.check
    if not install_from_live(vm, suite):
        return
    vm.screenshot("in-01-installed-login")

    # Firmware and boot chain
    if vm.firmware == "sb":
        sb = vm.sh(f"od -An -t u1 {SECURE_BOOT_VAR} | awk '{{print $NF}}'").out.strip()
        lockdown = vm.sh("cat /sys/kernel/security/lockdown").out.strip()
        c("UEFI Secure Boot is enforced on the installed system", sb == "1", f"SecureBoot={sb!r}")
        c("the kernel runs locked down (it was verified)", "[integrity]" in lockdown or "[confidentiality]" in lockdown,
          lockdown)
        boot = vm.sh("efibootmgr -v").out
        c("the firmware boots the signed shim", "shimx64.efi" in boot.lower() or "\\EFI\\BOOT" in boot.upper(), boot)
    else:
        c("legacy BIOS boot (no EFI)", vm.sh("test -d /sys/firmware/efi").rc != 0)

    # Lab Mode: turned on, then a real restart
    r = vm.sh(f"echo '10.0.2.2 {EXAM_HOST}' >> /etc/hosts && primers-lab enable")
    c("Lab Mode turned on", r.rc == 0, r.out + r.err)
    prefer_lab_at_login(vm)
    restart_to_login(vm)
    st = vm.sh("primers-lab status")
    c("after a restart Lab Mode is on and the lab account can sign in",
      st.rc == 0 and "after the next restart" not in st.out and "lab" in st.out, st.out)
    c("the boot service reset the lab account", "reset lab account 'lab' (boot)" in
      vm.sh("journalctl -b -t primers-lab --no-pager").out)
    desktop = sign_in_lab(vm, suite, "in-02-lab-desktop", signed_in=lab_desktop_pid)
    c("the lab account signs in to a desktop", bool(desktop))
    r = vm.as_user("lab", "echo 'my notes' > ~/notes.txt && mkdir -p ~/Downloads && touch ~/Downloads/x.pdf && ls ~")
    c("setup: the student saves files", r.rc == 0 and "notes.txt" in r.out, repr(r))
    restart_to_login(vm)                # left signed in: restarted under them
    left = vm.sh("ls -A /home/lab").out
    c("after a restart the student's files are gone", "notes.txt" not in left and "x.pdf" not in
      vm.sh("ls -A /home/lab/Downloads 2>/dev/null").out, left)
    c("Lab Mode is still on after a second restart", vm.sh("primers-lab status").rc == 0)

    # The full exam escape suite, on the installed system
    escape_checks(vm, suite, installed=True)


# ------------------------------------------------------------------ #
#  Real exam sites: probe, a CDN that moves, an IPv6-only exam server
# ------------------------------------------------------------------ #

def lab_get(vm: VM, url: str, *opts: str) -> str:
    """HTTP status the lab account gets for url ('000': refused/blocked)."""
    r = vm.run(["runuser", "-u", "lab", "--", "curl", "-s", "-m", "8", "-o", "/dev/null", "-w", "%{http_code}",
                *opts, url])
    return r.out.strip() or "000"


def exam_network(vm: VM, suite: Suite) -> None:
    c = suite.check
    vm.start()
    vm.wait_agent(timeout=1200)
    vm.wait_until(lambda: vm.sh("pgrep -x openbox").rc == 0, 600, "the live desktop")
    vm.sh(f"printf '10.0.2.2 {EXAM_HOST}\\n{CDN_OLD} {CDN_HOST}\\n{GUEST_HOST6} {V6_HOST}\\n' >> /etc/hosts")
    r = vm.sh(f"curl -s -m 8 -o /dev/null -w '%{{http_code}}' http://{CDN_HOST}:{CDN_PORT}/logo.svg")
    c("setup: the CDN answers at its first address", r.out == "200", repr(r))

    # 1. The probe finds the CDN and its port, and says how to start the exam
    cdn_url = f"http://{EXAM_HOST}:{EXAM_PORT}/exam-cdn.html"
    r = vm.as_user("primers", f"primers-exam probe {cdn_url} --seconds 15 --json", timeout=120)
    try:
        probe = json.loads(r.out)
    except ValueError:
        probe = {}
    c("probe: finds the CDN on its own port and suggests --allow for it",
      probe.get("allow") == [f"{CDN_HOST}:{CDN_PORT}"] and
      probe.get("command") == f"sudo primers-exam start {cdn_url} --allow {CDN_HOST}:{CDN_PORT}", r.out + r.err)

    # 2. The exam, started as the probe said; then the CDN moves
    r = vm.sh("primers-lab enable && systemctl start primers-lab-reset.service")
    c("setup: Lab Mode enabled", r.rc == 0, r.err)
    vm.sh("loginctl terminate-user primers")
    vm.wait_until(lambda: vm.sh("pgrep -u primers -x openbox").rc != 0, 60, "sign-out")
    r = vm.sh(f"primers-exam start {cdn_url} --allow {CDN_HOST}:{CDN_PORT}", timeout=300)
    c("setup: exam started with the CDN allowed", r.rc == 0, r.out + r.err)
    c("the lab account reaches the CDN", lab_get(vm, f"http://{CDN_HOST}:{CDN_PORT}/logo.svg") == "200")
    c("the CDN's next address is still blocked", lab_get(vm, f"http://{CDN_NEW}:{CDN_PORT}/logo.svg") == "000")
    vm.sh(f"sed -i 's/^{CDN_OLD} {CDN_HOST}$/{CDN_NEW} {CDN_HOST}/' /etc/hosts")     # the CDN moves
    c("the address-following timer is on", vm.sh("systemctl is-enabled primers-exam-refresh.timer").out.strip()
      == "enabled" and vm.sh("systemctl is-active primers-exam-refresh.timer").out.strip() == "active")
    r = vm.sh("systemctl start primers-exam-refresh.service", timeout=120)          # what the timer runs
    pinned = vm.run(["runuser", "-u", "lab", "--", "getent", "hosts", CDN_HOST]).out
    c("after the CDN moved, the lab account's name for it points at the new address", CDN_NEW in pinned, pinned)
    c("the CDN works at its new address", lab_get(vm, f"http://{CDN_HOST}:{CDN_PORT}/logo.svg") == "200")
    c("its old address still works for a while (connections already open)",
      lab_get(vm, f"http://{CDN_OLD}:{CDN_PORT}/logo.svg") == "200")
    c("the exam log records the move", "moved: now also " + CDN_NEW in vm.sh("cat /var/log/primers/exam.jsonl").out)
    kiosk = sign_in_lab(vm, suite, "net-01-kiosk-cdn")
    log = lambda: vm.sh("cat /var/log/primers/exam.jsonl").out  # noqa: E731
    vm.wait_until(lambda: f"visited {cdn_url}" in log(), 180, "the kiosk to open the exam page")
    # The CDN's logo is a 48x48 green square: on screen means it came through
    def logo_shown() -> bool:
        _, size, _ = colour_patch(vm.screenshot("net-01-kiosk-cdn"), (30, 158, 98), tol=12)
        return size >= 100
    try:
        vm.wait_until(logo_shown, 120, "the CDN logo on the exam page", interval=5)
        shown = True
    except VMError:
        shown = False
    c("the kiosk shows the exam page with the logo from the CDN", bool(kiosk) and shown and
      "blocked" not in log(), "logo not on screen" if not shown else "something was blocked")
    r = vm.sh("primers-exam stop", timeout=300)
    c("exam stops", r.rc == 0, r.out + r.err)
    vm.wait_until(lambda: vm.sh("pgrep -u lab").rc != 0, 120, "the lab session to end")

    # 3. An exam server reachable only over IPv6
    if not HOST_IPV6:
        if os.environ.get("PRIMERS_VM_REQUIRE_IPV6"):
            c("the test machine can serve over IPv6", False, "no IPv6 on this machine")
        else:
            suite.note("IPv6 part skipped: this machine has no IPv6 (the release workflow requires it)")
        return
    vm.wait_until(lambda: vm.sh("ip -6 addr show | grep -q 'inet6 fec0:'").rc == 0, 120,
                  "an IPv6 address")
    v6_url = f"http://{V6_HOST}:{V6_PORT}/exam.html"
    r = vm.sh(f"curl -s -m 8 -o /dev/null -w '%{{http_code}}' -4 http://10.0.2.2:{V6_PORT}/exam.html; echo; "
              f"curl -s -m 8 -o /dev/null -w '%{{http_code}}' {v6_url}")
    c("setup: the exam server answers over IPv6 only", r.out.split() == ["000", "200"], repr(r))
    r = vm.sh(f"primers-exam start {v6_url}", timeout=300)
    c("setup: an IPv6-only exam starts", r.rc == 0, r.out + r.err)
    rules = vm.sh("nft list table inet primers_exam").out
    c("the exam firewall allows the server's IPv6 address and no IPv4 one",
      GUEST_HOST6 in rules and "allow4" in rules and "10.0.2.2" not in rules, rules)
    c("the lab account reaches the exam over IPv6", lab_get(vm, v6_url) == "200")
    c("another port on the same IPv6 server is blocked for the lab account",
      lab_get(vm, f"http://[{GUEST_HOST6}]:{V6_OTHER_PORT}/") == "000" and
      vm.sh(f"curl -s -m 8 -o /dev/null -w '%{{http_code}}' http://[{GUEST_HOST6}]:{V6_OTHER_PORT}/").out == "200")
    c("the IPv4 exam server of before is blocked for the lab account",
      lab_get(vm, f"http://10.0.2.2:{EXAM_PORT}/exam.html") == "000")
    kiosk = sign_in_lab(vm, suite, "net-02-kiosk-ipv6")
    c("the kiosk opens the IPv6-only exam", bool(kiosk) and
      f"visited {v6_url}" in vm.sh("cat /var/log/primers/exam.jsonl").out)
    r = vm.sh("primers-exam stop", timeout=300)
    c("exam stops", r.rc == 0, r.out + r.err)


# ------------------------------------------------------------------ #
#  A real CBT platform: Moodle 4.5, a quiz taken in the exam kiosk
# ------------------------------------------------------------------ #

def colour_boxes(path: str, rgb, tol: int = 10, cell: int = 4):
    """Every solid patch of `rgb` in a screenshot, as (x0, y0, x1, y1, size
    in cells), top to bottom; and the screen size."""
    from PIL import Image
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        px = img.load()
    gw, gh = w // cell, h // cell
    hit = [[sum(1 for dy in (0, cell // 2) for dx in (0, cell // 2)
                if all(abs(c - want) <= tol for c, want in zip(px[gx * cell + dx, gy * cell + dy], rgb))) >= 3
            for gx in range(gw)] for gy in range(gh)]
    boxes, seen = [], set()
    for y in range(gh):
        for x in range(gw):
            if hit[y][x] and (x, y) not in seen:
                stack, comp = [(x, y)], []
                seen.add((x, y))
                while stack:
                    cx, cy = stack.pop()
                    comp.append((cx, cy))
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if 0 <= nx < gw and 0 <= ny < gh and hit[ny][nx] and (nx, ny) not in seen:
                            seen.add((nx, ny))
                            stack.append((nx, ny))
                xs, ys = [c[0] for c in comp], [c[1] for c in comp]
                boxes.append((min(xs) * cell, min(ys) * cell, (max(xs) + 1) * cell, (max(ys) + 1) * cell, len(comp)))
    return sorted(boxes, key=lambda b: (b[1], b[0])), (w, h)


def colour_patch(path: str, rgb, tol: int = 10, cell: int = 4):
    """Centre and size (in cells) of the largest solid patch of `rgb` in a
    screenshot: a filled button, not the thin text of a link."""
    boxes, (w, h) = colour_boxes(path, rgb, tol, cell)
    if not boxes:
        return None, 0, (w, h)
    x0, y0, x1, y1, size = max(boxes, key=lambda b: b[4])
    return ((x0 + x1) // 2, (y0 + y1) // 2), size, (w, h)


KIOSK_BAR = 30          # the kiosk's own bar along the top: its clock changes every second


def page_image(path: str):
    """The page part of a kiosk screenshot (below the kiosk's bar)."""
    from PIL import Image
    with Image.open(path) as img:
        img = img.convert("RGB")
        return img.crop((0, KIOSK_BAR, img.width, img.height))


def same_page(a, b, cells: int = 24) -> bool:
    """Two looks at the page show the same thing: at most `cells` 16x16
    squares differ (a blinking caret, a clock on the page ticking)."""
    from PIL import Image, ImageChops
    if a is None or b is None or a.size != b.size:
        return False
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > 24 else 0)
    grid = diff.resize((max(1, a.width // 16), max(1, a.height // 16)), Image.BOX)
    return sum(1 for v in grid.getdata() if v) <= cells


def settled(vm: VM, shot: str, before=None, timeout: float = 180) -> str:
    """Wait until the page is drawn: no longer `before` (the page as it was
    before the click or key that changed it) and the same on two looks in a
    row. The kiosk logs a visit when the server answers, and under emulation
    the previous page can stay on screen a good while after that."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        path = vm.screenshot(shot)
        img = page_image(path)
        if before is not None and same_page(img, before):
            last = None
        elif same_page(img, last):
            return path
        else:
            last = img
        time.sleep(3)
    raise VMError(f"timed out waiting for the page to be drawn ({shot})")


def press_primary(vm: VM, shot: str, scroll_end: bool = False):
    """Click the page's main (blue) button, as a candidate would. Returns
    whether it was found, and the page as it was (for settled())."""
    if scroll_end:
        vm.key("end")
        time.sleep(2)
    path = settled(vm, shot)
    before = page_image(path)
    centre, size, (w, h) = colour_patch(path, MOODLE_BLUE)
    if not centre or size < 20:
        return False, before
    vm.click(centre[0], centre[1], w, h)
    vm.pointer_away(w, h)
    return True, before


def visited(vm: VM, part: str, site: str = f"http://{MOODLE_HOST}:{MOODLE_PORT}") -> bool:
    return f"visited {site}{part}" in vm.sh("cat /var/log/primers/exam.jsonl").out


def moodle_attempts(state: str) -> str:
    sql = ("SELECT count(*) FROM mdl_quiz_attempts a JOIN mdl_user u ON u.id = a.userid "
           f"WHERE u.username = 'student1' AND a.state = '{state}'")
    r = subprocess.run(["sudo", "-u", "postgres", "psql", "-qtA", "-d", "moodle", "-c", sql],
                       capture_output=True, text=True)
    return r.stdout.strip() or r.stderr.strip()


def moodle_answers() -> dict:
    """The answers saved in student1's latest finished attempt, and its marks."""
    latest = ("(SELECT a.id FROM mdl_quiz_attempts a JOIN mdl_user u ON u.id = a.userid "
              "WHERE u.username = 'student1' AND a.state = 'finished' ORDER BY a.id DESC LIMIT 1)")
    sql = ("SELECT d.value FROM mdl_question_attempt_step_data d "
           "JOIN mdl_question_attempt_steps s ON s.id = d.attemptstepid "
           "JOIN mdl_question_attempts qa ON qa.id = s.questionattemptid "
           f"JOIN mdl_quiz_attempts a ON a.uniqueid = qa.questionusageid WHERE a.id = {latest} "
           "AND d.name = 'answer' ORDER BY qa.slot")
    run = lambda q: subprocess.run(["sudo", "-u", "postgres", "psql", "-qtA", "-d", "moodle", "-c", q],  # noqa: E731
                                   capture_output=True, text=True).stdout
    grade = run(f"SELECT sumgrades FROM mdl_quiz_attempts WHERE id = {latest}").strip()
    try:
        marks = float(grade)
    except ValueError:
        marks = 0.0
    return {"answers": run(sql).splitlines(), "grade": marks}


def image_size(path: str):
    from PIL import Image
    with Image.open(path) as img:
        return img.size


def exam_moodle(vm: VM, suite: Suite) -> None:
    c = suite.check
    cmid = os.environ.get("MOODLE_CMID", "")
    if not cmid.isdigit():
        c("setup: a Moodle quiz to take (tests/cbt/moodle/setup.sh, MOODLE_CMID)", False, repr(cmid))
        return
    quiz = f"http://{MOODLE_HOST}:{MOODLE_PORT}/mod/quiz/view.php?id={cmid}"
    finished_before = moodle_attempts("finished")
    vm.start()
    vm.wait_agent(timeout=1200)
    vm.wait_until(lambda: vm.sh("pgrep -x openbox").rc == 0, 600, "the live desktop")
    vm.sh(f"echo '10.0.2.2 {MOODLE_HOST}' >> /etc/hosts")

    # The probe, as staff would run it: Moodle 4.5 loads MathJax from a CDN
    # on every page (its default maths filter), so that server must be allowed
    r = vm.as_user("primers", f"primers-exam probe '{quiz}' --seconds 25 --json", timeout=120)
    try:
        probe = json.loads(r.out)
    except ValueError:
        probe = {}
    hosts = [s.get("host") for s in probe.get("servers", [])]
    c("probe: finds Moodle and the CDN it loads MathJax from", hosts[:1] == [MOODLE_HOST] and
      "cdn.jsdelivr.net" in probe.get("allow", []) and set(probe.get("allow", [])) <= {"cdn.jsdelivr.net"},
      r.out[-1500:] + r.err[-500:])
    command = probe.get("command", f"sudo primers-exam start {quiz}")

    r = vm.sh("primers-lab enable && systemctl start primers-lab-reset.service")
    c("setup: Lab Mode enabled", r.rc == 0, r.err)
    vm.sh("loginctl terminate-user primers")
    vm.wait_until(lambda: vm.sh("pgrep -u primers -x openbox").rc != 0, 60, "sign-out")
    argv = shlex.split(command)
    r = vm.run(argv[1:] if argv[0] == "sudo" else argv, timeout=300)     # the probe's command, as root
    c("setup: Exam Mode on for the Moodle quiz, with the probe's command", r.rc == 0, command + "\n" + r.out + r.err)

    # The candidate signs in to the kiosk, then to Moodle, and takes the quiz
    kiosk = sign_in_lab(vm, suite, "moodle-01-login")
    c("the kiosk opens Moodle's sign-in page", bool(kiosk))
    vm.wait_until(lambda: visited(vm, "/login/index.php"), 120, "Moodle's sign-in page")
    time.sleep(5)
    settled(vm, "moodle-01-login")
    signed_in = False
    for attempt in range(3):            # typed keys can be lost under emulation: type again
        vm.key("ctrl-a")
        vm.type_then_settle("student1")
        vm.key("tab")
        time.sleep(1)
        vm.key("ctrl-a")
        vm.type_then_settle("Student-Test-1")
        before = page_image(vm.screenshot("moodle-01-login"))
        vm.key("ret")
        try:
            vm.wait_until(lambda: visited(vm, f"/mod/quiz/view.php?id={cmid}"), 90, "the quiz page")
            signed_in = True
            break
        except VMError:                 # the username field has focus again
            settled(vm, f"moodle-01-sign-in-retry-{attempt + 1}", before)
    c("the candidate signs in to Moodle in the kiosk", signed_in)
    if not signed_in:
        return
    settled(vm, "moodle-02-quiz", before)
    pressed, before = press_primary(vm, "moodle-02-quiz")
    c("'Attempt quiz' pressed", pressed)
    vm.wait_until(lambda: visited(vm, "/mod/quiz/attempt.php"), 120, "the attempt")
    path = settled(vm, "moodle-03-attempt", before)
    c("the questions are shown", moodle_attempts("inprogress") not in ("", "0"))
    # Answer both: 'True' in the first question's box, the second's text field
    boxes = [b for b in colour_boxes(path, MOODLE_QUESTION, tol=4)[0] if b[4] > 500]
    c("both questions are on screen", len(boxes) >= 2, repr(boxes))
    if len(boxes) < 2:
        return
    w, h = image_size(path)
    vm.click(boxes[0][0] + 30, boxes[0][1] + 69, w, h)
    time.sleep(1)
    vm.click(boxes[1][0] + 150, boxes[1][1] + 72, w, h)
    time.sleep(1)
    vm.type_then_settle("Random Access Memory")
    vm.pointer_away(w, h)
    pressed, before = press_primary(vm, "moodle-03-attempt", scroll_end=True)
    c("'Finish attempt' pressed", pressed)
    vm.wait_until(lambda: visited(vm, "/mod/quiz/summary.php"), 120, "the summary")
    settled(vm, "moodle-04-summary", before)
    pressed, before = press_primary(vm, "moodle-04-summary", scroll_end=True)
    c("'Submit all and finish' pressed", pressed)
    settled(vm, "moodle-05-confirm", before)             # a confirmation box over the page
    pressed, before = press_primary(vm, "moodle-05-confirm")
    c("the confirmation's 'Submit all and finish' pressed", pressed)
    vm.wait_until(lambda: visited(vm, "/mod/quiz/review.php"), 120, "the review page")
    settled(vm, "moodle-06-review", before)
    after = moodle_attempts("finished")
    c("Moodle recorded the candidate's submitted attempt", after.isdigit() and finished_before.isdigit()
      and int(after) == int(finished_before) + 1, f"finished attempts before {finished_before}, after {after}")
    answers = moodle_answers()
    c("Moodle saved both answers and marked them", "1" in answers["answers"] and
      any(a.strip() and a != "1" for a in answers["answers"]) and answers["grade"] >= 1,
      json.dumps(answers))
    blocked = [line for line in vm.sh("cat /var/log/primers/exam.jsonl").out.splitlines() if "blocked" in line]
    c("nothing Moodle needed was blocked", not blocked, "\n".join(blocked[:5]))
    r = vm.sh("primers-exam stop", timeout=300)
    c("exam stops", r.rc == 0, r.out + r.err)


# ------------------------------------------------------------------ #
#  A real CBT platform: TCExam 17, a test taken in the exam kiosk
# ------------------------------------------------------------------ #

def page_top(path: str, rgb, tol: int = 6):
    """The screen row where a page starts: its first row mostly of `rgb`
    (the page's title bar; the kiosk's own bar is above it)."""
    from PIL import Image
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        px = img.load()
    for y in range(h):
        if sum(1 for x in range(0, w, 8) if all(abs(c - t) <= tol for c, t in zip(px[x, y], rgb))) >= w // 8 * 0.6:
            return y, (w, h)
    return None, (w, h)


def tcexam_click(vm: VM, path: str, x: int, y: int) -> bool:
    """Click a point of the TCExam page in screenshot `path`: x and y as
    measured on its pages at 1280 wide in the kiosk's engine, y from the top
    of its title bar."""
    top, (w, h) = page_top(path, TCEXAM_BLUE)
    if top is None:
        return False
    vm.click(x, top + y, w, h)
    time.sleep(0.5)
    return True


def tcexam_fields(path: str) -> List[tuple]:
    """TCExam's sign-in fields (username, password): the white boxes inside
    its grey sign-in panel, top to bottom, wherever the screen width puts them."""
    panels = [b for b in colour_boxes(path, (244, 244, 244), tol=2)[0] if b[4] >= 200]
    if not panels:
        return []
    px0, py0, px1, py1, _ = max(panels, key=lambda b: b[4])
    whites = [b for b in colour_boxes(path, (255, 255, 255), tol=2)[0]
              if b[4] >= 20 and px0 < b[0] and b[2] < px1 and py0 < b[1] and b[3] < py1]
    return sorted(whites, key=lambda b: b[1])[:2]


def tcexam_sql(sql: str) -> str:
    r = subprocess.run(["sudo", "-u", "postgres", "psql", "-qtA", "-d", "tcexam", "-c", sql],
                       capture_output=True, text=True)
    return r.stdout.strip() or r.stderr.strip()


def exam_tcexam(vm: VM, suite: Suite) -> None:
    c = suite.check
    testid = os.environ.get("TCEXAM_TESTID", "")
    if not testid.isdigit():
        c("setup: a TCExam test to take (tests/cbt/tcexam/setup.sh, TCEXAM_TESTID)", False, repr(testid))
        return
    site = f"http://{TCEXAM_HOST}:{TCEXAM_PORT}"
    start = f"{site}/public/code/index.php"
    attempt = ("FROM tce_tests_users t JOIN tce_users u ON u.user_id = t.testuser_user_id "
               f"WHERE u.user_name = 'student1' AND t.testuser_test_id = {testid}")
    c("setup: the test hasn't been taken yet", tcexam_sql(f"SELECT count(*) {attempt}") == "0",
      tcexam_sql(f"SELECT testuser_status {attempt}"))
    vm.start()
    vm.wait_agent(timeout=1200)
    vm.wait_until(lambda: vm.sh("pgrep -x openbox").rc == 0, 600, "the live desktop")
    vm.sh(f"echo '10.0.2.2 {TCEXAM_HOST}' >> /etc/hosts")

    # The probe, as staff would run it: TCExam serves everything itself
    r = vm.as_user("primers", f"primers-exam probe '{start}' --seconds 20 --json", timeout=120)
    try:
        probe = json.loads(r.out)
    except ValueError:
        probe = {}
    hosts = [s.get("host") for s in probe.get("servers", [])]
    c("probe: TCExam needs only its own server", hosts == [TCEXAM_HOST] and probe.get("allow") == [],
      r.out[-1500:] + r.err[-500:])
    command = probe.get("command", f"sudo primers-exam start {start}")

    r = vm.sh("primers-lab enable && systemctl start primers-lab-reset.service")
    c("setup: Lab Mode enabled", r.rc == 0, r.err)
    vm.sh("loginctl terminate-user primers")
    vm.wait_until(lambda: vm.sh("pgrep -u primers -x openbox").rc != 0, 60, "sign-out")
    argv = shlex.split(command)
    r = vm.run(argv[1:] if argv[0] == "sudo" else argv, timeout=300)     # the probe's command, as root
    c("setup: Exam Mode on for the TCExam test, with the probe's command", r.rc == 0,
      command + "\n" + r.out + r.err)

    # The candidate signs in to the kiosk, then to TCExam, and takes the test
    kiosk = sign_in_lab(vm, suite, "tcexam-01-login")
    c("the kiosk opens TCExam's sign-in page", bool(kiosk))
    vm.wait_until(lambda: visited(vm, "/public/code/index.php", site), 120, "TCExam's sign-in page")
    def tcexam_page(shot: str, before=None) -> str:
        """A TCExam page, drawn (its blue title bar on screen)."""
        deadline = time.time() + 240
        while True:
            path = settled(vm, shot, before)
            if page_top(path, TCEXAM_BLUE)[0] is not None or time.time() > deadline:
                return path
            time.sleep(3)
    path = tcexam_page("tcexam-01-login")
    c("TCExam's sign-in page is on screen", page_top(path, TCEXAM_BLUE)[0] is not None)

    def test_list() -> bool:
        _, size, _ = colour_patch(vm.screenshot("tcexam-02-tests"), TCEXAM_GO)
        return size >= 20
    signed_in = False
    for attempt_no in range(3):         # typed keys can be lost under emulation: type again
        fields = tcexam_fields(path)                        # username, then password
        if fields:
            x0, y0, x1, y1, _ = fields[0]
            sw, sh = image_size(path)
            vm.click((x0 + x1) // 2, (y0 + y1) // 2, sw, sh)
            time.sleep(0.5)
        vm.key("ctrl-a")
        vm.type_then_settle("student1")
        vm.key("tab")                                       # password
        time.sleep(1)
        vm.key("ctrl-a")
        vm.type_then_settle("Student-Test-1")
        before = page_image(vm.screenshot("tcexam-01-login"))
        vm.key("ret")
        try:
            vm.wait_until(test_list, 90, "the test list", interval=5)
            signed_in = True
            break
        except VMError:                 # the sign-in page again, with a message above it
            path = tcexam_page(f"tcexam-01-sign-in-retry-{attempt_no + 1}", before)
    c("the candidate signs in to TCExam in the kiosk", signed_in)
    if not signed_in:
        return
    path = tcexam_page("tcexam-02-tests")
    before = page_image(path)
    centre, _, (w, h) = colour_patch(path, TCEXAM_GO)
    vm.click(centre[0], centre[1], w, h)                        # 'execute' on the test list
    vm.pointer_away(w, h)
    vm.wait_until(lambda: visited(vm, f"/public/code/tce_test_start.php?testid={testid}", site), 120,
                  "the test's information page")
    path = tcexam_page("tcexam-03-info", before)
    before = page_image(path)
    # 'execute' and 'cancel', grey, centred under the test's details (where depends on the screen width)
    buttons = sorted((b for b in colour_boxes(path, TCEXAM_BUTTON, tol=4)[0] if b[4] >= 20), key=lambda b: b[0])
    if buttons:
        vm.click((buttons[0][0] + buttons[0][2]) // 2, (buttons[0][1] + buttons[0][3]) // 2, w, h)
    c("'execute' pressed on the test's information page", bool(buttons), repr(buttons))
    vm.pointer_away(w, h)
    vm.wait_until(lambda: visited(vm, f"/public/code/tce_test_execute.php?testid={testid}", site), 120,
                  "the first question")
    path = tcexam_page("tcexam-04-question", before)
    c("the test started", tcexam_sql(f"SELECT testuser_status {attempt}") == "1",
      tcexam_sql(f"SELECT testuser_status {attempt}"))

    # Answer the question on screen (its first option), then 'terminate the
    # exam': five Tabs from the answer (confirm, next, the question list,
    # the comment box), the page's own order whatever the fonts
    def confirm_box(path: str):
        boxes = [b for b in colour_boxes(path, TCEXAM_WARN)[0] if b[4] >= 200]
        return max(boxes, key=lambda b: b[4]) if boxes else None
    box = None
    for attempt_no in range(3):         # a lost Tab leaves the focus short of the button: again
        tcexam_click(vm, path, 60, 209)
        for _ in range(5):
            vm.key("tab")
            time.sleep(0.5)
        vm.key("ret")
        try:
            vm.wait_until(lambda: confirm_box(vm.screenshot("tcexam-05-confirm")), 90,
                          "the request to confirm", interval=5)
        except VMError:
            path = tcexam_page(f"tcexam-04-question-retry-{attempt_no + 1}")
            continue
        path = tcexam_page("tcexam-05-confirm")
        box = confirm_box(path)
        break
    c("TCExam asks to confirm the end of the test", box is not None)
    if not box:
        return
    # Its 'terminate' button is just left of the box's centre, at its bottom
    vm.click((box[0] + box[2]) // 2 - 40, box[3] - 14, w, h)
    vm.pointer_away(w, h)
    vm.wait_until(lambda: tcexam_sql(f"SELECT testuser_status {attempt}") == "4", 120, "the test to end")
    settled(vm, "tcexam-06-done")
    answered = tcexam_sql("SELECT count(*) FROM tce_tests_logs_answers a JOIN tce_tests_logs l "
                          "ON l.testlog_id = a.logansw_testlog_id WHERE a.logansw_selected = 1 "
                          f"AND l.testlog_testuser_id IN (SELECT t.testuser_id {attempt})")
    c("TCExam recorded the candidate's answer and the end of the test", answered == "1",
      f"answered questions: {answered}")
    blocked = [line for line in vm.sh("cat /var/log/primers/exam.jsonl").out.splitlines() if "blocked" in line]
    c("nothing TCExam needed was blocked", not blocked, "\n".join(blocked[:5]))
    r = vm.sh("primers-exam stop", timeout=300)
    c("exam stops", r.rc == 0, r.out + r.err)


# ------------------------------------------------------------------ #
#  primers-fleet: an invigilator PC and three lab PCs on one LAN
# ------------------------------------------------------------------ #

FLEET_LAN = "192.168.77"
FLEET_MCAST = "230.0.0.1:47700"
FLEET_LABS = ("lab-01", "lab-02", "lab-03")


def lan_nic(index: int) -> List[str]:
    """A second network card on a LAN shared by the test's VMs (QEMU's
    multicast socket network), with a MAC that says which VM it is."""
    return ["-netdev", f"socket,id=lan,mcast={FLEET_MCAST},localaddr=127.0.0.1",
            "-device", f"e1000,netdev=lan,mac=52:54:00:77:00:{index:02x}"]


def join_lan(vm: VM, index: int, hostname: str) -> str:
    """The LAN card gets 192.168.77.(10+index), NetworkManager kept off it."""
    address = f"{FLEET_LAN}.{10 + index}"
    r = vm.sh(f"set -e; dev=$(ip -o link | awk -F': ' '/52:54:00:77:00:{index:02x}/ {{print $2}}'); "
              f"test -n \"$dev\"; nmcli device set \"$dev\" managed no || true; "
              f"ip addr flush dev \"$dev\"; ip addr add {address}/24 dev \"$dev\"; ip link set \"$dev\" up; "
              f"hostnamectl set-hostname {hostname}")
    if r.rc != 0:
        raise VMError(f"{hostname}: couldn't join the test LAN: {r.err}")
    return address


def fleet_status(vm: VM) -> dict:
    """'primers-fleet status' on the invigilator PC, as JSON."""
    r = vm.sh("primers-fleet status --json", timeout=120)
    try:
        return json.loads(r.out)
    except ValueError:
        return {}


def fleet_scenario(ctrl: VM, suite: Suite) -> None:
    c = suite.check
    labs = [VM(ctrl.workdir, iso=ctrl.iso, name=name, memory=ctrl.memory, cpus=ctrl.cpus,
               extra=lan_nic(i + 1)) for i, name in enumerate(FLEET_LABS)]
    vms = [ctrl] + labs
    try:
        for v in vms:
            v.start()
        for v in vms:
            v.wait_agent(timeout=1500)
        for v in vms:
            v.wait_until(lambda v=v: v.sh("pgrep -x openbox").rc == 0, 900, f"{v.name}: the live desktop")
        ctrl_ip = join_lan(ctrl, 0, "invigilator")
        lab_ips = [join_lan(v, i + 1, v.name) for i, v in enumerate(labs)]
        c("setup: four PCs on one LAN", all(ctrl.sh(f"ping -c1 -W5 {ip}").rc == 0 for ip in lab_ips))
        c("the firewall is on (incoming denied) on every PC",
          all("Status: active" in v.sh("ufw status").out for v in vms))
        for v in labs:      # campus setup on each lab PC: the exam server's name, Lab Mode on
            r = v.sh(f"echo '10.0.2.2 {EXAM_HOST}' >> /etc/hosts && primers-lab enable && "
                     "systemctl start primers-lab-reset.service")
            c(f"setup: Lab Mode on {v.name}", r.rc == 0, r.err)

        # Not paired yet: lab-03 can't be reached or controlled
        c("an unpaired PC's agent port is closed",
          ctrl.sh(f"timeout 5 bash -c '</dev/tcp/{lab_ips[2]}/7480'").rc != 0)
        r = ctrl.sh("primers-fleet exam-stop --pc lab-03")
        c("an unpaired PC can't be named in a command", r.rc != 0 and "not paired" in r.err, r.out + r.err)

        # Pairing: the invigilator opens it and reads out the code
        ctrl.sh("setsid -f primers-fleet pair --minutes 20 > /root/pair.log 2>&1 < /dev/null")
        ctrl.wait_until(lambda: "primers-fleet join" in ctrl.sh("cat /root/pair.log").out, 120, "the pairing code")
        m = re.search(r"primers-fleet join (\S+) ([2-9A-Z]{4}-[2-9A-Z]{4}-[2-9A-Z]{4})", ctrl.sh("cat /root/pair.log").out)
        code = m.group(2) if m else ""
        c("pairing shows a one-time code", bool(code), ctrl.sh("cat /root/pair.log").out)
        wrong = "ABCD-EFGH-JKMN" if code != "ABCD-EFGH-JKMN" else "ZZZZ-ZZZZ-ZZZZ"
        r = labs[2].sh(f"primers-fleet join {ctrl_ip} {wrong}", timeout=120)
        c("a wrong code pairs nothing", r.rc != 0 and labs[2].sh("ls /etc/primers/fleet/controllers 2>/dev/null").out == "",
          r.out + r.err)
        for v in labs:
            r = v.sh(f"primers-fleet join {ctrl_ip} {code}", timeout=180)
            c(f"{v.name} pairs with the invigilator PC", r.rc == 0, r.out + r.err)
        listed = ctrl.sh("primers-fleet list").out
        c("the invigilator PC lists the three lab PCs", all(n in listed for n in FLEET_LABS), listed)
        c("each lab PC runs the agent", all(v.sh("systemctl is-active primers-fleet-agent.service").out.strip()
                                            == "active" for v in labs))
        r = labs[1].sh(f"timeout 5 bash -c '</dev/tcp/{lab_ips[0]}/7480'")
        c("a lab PC's agent port is open to the invigilator PC only (not to another lab PC)", r.rc != 0)
        # Pairing ends (the command runs as primers_fleet.py; [p] keeps pgrep off its own shell)
        ctrl.sh("pkill -f '[p]rimers_fleet.py pair'")
        ctrl.wait_until(lambda: ctrl.sh("pgrep -f '[p]rimers_fleet.py pair'").rc != 0, 60, "pairing to close")
        c("the pairing port is closed again when pairing ends", "7481" not in ctrl.sh("ufw status").out,
          ctrl.sh("ufw status").out)

        st = fleet_status(ctrl)
        c("status: every lab PC answers, Lab Mode on, no exam",
          sorted(st) == list(FLEET_LABS) and all(r.get("ok") and r["status"].get("lab") is True and
                                                 r["status"].get("exam") is False for r in st.values()),
          json.dumps(st)[:1500])

        # The exam, started from the invigilator's PC on all three
        for v in labs:
            v.sh("loginctl terminate-user primers")
        r = ctrl.sh(f"primers-fleet exam-start {EXAM_URL}", timeout=900)
        c("exam-start on every lab PC", r.rc == 0 and r.out.count("exam on") == 3, r.out + r.err)
        c("each lab PC is in Exam Mode with the exam",
          all(EXAM_URL in v.sh("primers-exam status").out for v in labs),
          "\n".join(v.sh("primers-exam status").out for v in labs))
        kiosk = sign_in_lab(labs[0], suite, "fleet-01-lab-01-kiosk")
        c("a candidate on lab-01 gets the exam kiosk", bool(kiosk))
        labs[0].wait_until(lambda: f"visited {EXAM_URL}" in labs[0].sh("cat /var/log/primers/exam.jsonl").out,
                           180, "lab-01: the exam page")
        st = fleet_status(ctrl)
        c("status: exam on everywhere, the candidate on lab-01 shows",
          all(r.get("ok") and r["status"].get("exam") for r in st.values()) and
          st.get("lab-01", {}).get("status", {}).get("candidate") is True, json.dumps(st)[:1500])
        r = ctrl.sh("primers-fleet status")
        c("status view (table)", r.rc == 0 and all(n in r.out for n in FLEET_LABS) and "signed in" in r.out, r.out)

        # A controller that isn't paired (another key on the same PC) is refused, and logged
        rogue = ("python3 -I -c \"import sys; sys.path.insert(0, '/usr/share/primers/brain'); "
                 "from core import fleet as f; p = f.FleetPaths('/root/rogue', '/root/rogue.jsonl'); "
                 "f.ensure_identity(p); pc = [x for x in f.load_pcs(f.FleetPaths()) if x.name == 'lab-01'][0]; "
                 "print(f.call(p, pc, 'exam-stop'))\"")
        r = ctrl.sh(rogue, timeout=120)
        c("a controller that isn't paired can't stop the exam", "'ok': False" in r.out and
          EXAM_URL in labs[0].sh("primers-exam status").out, r.out + r.err)
        c("the refusal is in lab-01's fleet log", '"refused"' in labs[0].sh("cat /var/log/primers/fleet.jsonl").out)

        # The exam logs, collected
        r = ctrl.sh("primers-fleet collect /root/exam-logs && cd /root/exam-logs && sha256sum -c SHA256SUMS",
                    timeout=300)
        c("collect: every PC's exam log, checksums verify", r.rc == 0 and r.out.count(": OK") == 3, r.out + r.err)
        c("collect: lab-01's log has the candidate's page",
          f"visited {EXAM_URL}" in ctrl.sh("cat /root/exam-logs/lab-01/exam.jsonl").out)

        r = ctrl.sh("primers-fleet exam-stop", timeout=900)
        c("exam-stop on every lab PC", r.rc == 0 and r.out.count("exam off") == 3, r.out + r.err)
        c("no lab PC is in Exam Mode any more",
          all("Exam Mode: off" in v.sh("primers-exam status").out for v in labs),
          "\n".join(v.sh("primers-exam status").out for v in labs))
        ctrl_fp = ctrl.sh("primers-fleet id").out.strip()
        logs = [v.sh("cat /var/log/primers/fleet.jsonl").out for v in labs]
        c("every command is in each lab PC's log, with the invigilator PC's fingerprint",
          all('"cmd": "exam-start"' in t and '"cmd": "exam-stop"' in t and ctrl_fp in t for t in logs),
          logs[0][-1500:])
        c("and in the invigilator PC's log", ctrl.sh("grep -c '\"event\": \"sent\"' /var/log/primers/fleet.jsonl")
          .out.strip().isdigit())

        # A PC that leaves can't be controlled any more
        r = labs[2].sh("primers-fleet leave")
        c("lab-03 leaves", r.rc == 0, r.out + r.err)
        st = fleet_status(ctrl)
        c("lab-03 no longer answers the invigilator PC", st.get("lab-03", {}).get("ok") is False and
          st.get("lab-01", {}).get("ok"), json.dumps(st)[:1000])
    finally:
        for v in labs:
            try:
                v.screenshot(f"99-{v.name}")
            except Exception:
                pass
            v.stop()


# ------------------------------------------------------------------ #
#  Performance on a 2 GB, 2-CPU PC with a hard disk or an SSD
#  (docs/benchmarks.md): boot to the login screen, idle memory, and how
#  long a candidate waits for the exam after signing in
# ------------------------------------------------------------------ #

PERF_MEMORY_MB, PERF_CPUS = 2048, 2
PERF_TARGETS = {"boot_hdd_s": 30.0, "boot_ssd_s": 15.0, "idle_ram_mb": 600, "kiosk_s": 3.0}
PERF_BOOTS = int(os.environ.get("PRIMERS_PERF_BOOTS", "5"))     # cold boots per disk profile


def spread(values) -> Optional[dict]:
    """Median and worst of several measurements (None when one is missing)."""
    if not values or any(v is None for v in values):
        return None
    return {"n": len(values), "median": round(statistics.median(values), 1), "worst": max(values),
            "best": min(values), "each": values}


def guest_benchmark(vm: VM) -> dict:
    """The OS's own benchmark (what 'benchmark' in the Brain reports)."""
    r = vm.sh("python3 -I -c \"import sys, json; sys.path.insert(0, '/usr/share/primers/brain'); "
              "from core import benchmark as b; print(json.dumps(b.collect()))\"", timeout=120)
    try:
        return json.loads(r.out)
    except ValueError:
        return {}


def journal_times(vm: VM, pattern: str) -> List[tuple]:
    """(time, line) for this boot's journal lines matching an extended regex."""
    out = []
    # (not the guest agent's own lines: it logs every command, these greps included)
    for line in vm.sh(f"journalctl -b -o short-unix --no-pager | grep -v ' qemu-ga\\[' | "
                      f"grep -E {shlex.quote(pattern)}").out.splitlines():
        with_time = line.split(" ", 1)
        try:
            out.append((float(with_time[0]), with_time[1] if len(with_time) > 1 else ""))
        except ValueError:
            continue
    return out


def cold_boot(vm: VM) -> Optional[float]:
    """Shut down cleanly, then switch on: nothing of the last boot in the
    guest's memory. Returns the seconds from power-on to the login screen
    as a person sees it (firmware, boot menu, kernel and services), timed
    from outside the VM."""
    try:
        vm.sh("systemctl poweroff", timeout=15)
    except Exception:
        pass
    try:
        vm.proc.wait(180)
    except Exception:
        pass
    vm.stop()
    t0 = time.time()
    vm.start()
    vm.wait_agent(timeout=900)
    deadline = time.time() + 600
    while time.time() < deadline:
        if vm.sh("pgrep -f lightdm-gtk-greeter").rc == 0:
            return round(time.time() - t0, 1)
        time.sleep(0.5)
    return None


KIOSK_STEPS = (("session opened", r"session opened for user lab\b"),
               ("lab account reset", r"primers-lab.*(reset|session-setup)"),
               ("exam session started", r"exam session started"),
               ("exam browser opened", r"exam opened: "),
               ("exam page answered", r"visited http"),
               ("exam page shown", r"exam page shown"))


def kiosk_open_seconds(vm: VM, suite: Suite, shot: str):
    """From the candidate's sign-in (the session opens) to the exam page on
    screen, and when each step in between happened (seconds after the
    sign-in), to see where the time goes."""
    before = len(journal_times(vm, "exam page shown"))
    sign_in_lab(vm, suite, shot)
    vm.wait_until(lambda: len(journal_times(vm, "exam page shown")) > before, 180, "the exam page")
    shown = journal_times(vm, "exam page shown")[-1][0]
    opened = [t for t, line in journal_times(vm, KIOSK_STEPS[0][1]) if t <= shown]
    if not opened:
        return None, {}
    start = opened[-1]
    steps = {}
    for name, pattern in KIOSK_STEPS[1:]:
        times = [t for t, line in journal_times(vm, pattern) if start <= t <= shown]
        if times:
            steps[name] = round(times[0] - start, 2)
    detail = vm.sh(f"journalctl -b -o short-unix --no-pager --since=@{int(start) - 1} --until=@{int(shown) + 1} "
                   "| grep -v ' qemu-ga\\['").out
    steps["journal"] = detail[-6000:]
    return round(shown - start, 2), steps


def greeter_after_kernel(vm: VM) -> Optional[float]:
    """When the login screen appeared, in seconds after the kernel started."""
    vm.wait_until(lambda: vm.sh("pgrep -f lightdm-gtk-greeter").rc == 0, 300, "the login screen")
    r = vm.sh("echo $(cut -d' ' -f1 /proc/uptime) $(ps -o etimes= -p \"$(pgrep -o -f lightdm-gtk-greeter)\")")
    try:
        uptime, age = (float(x) for x in r.out.split()[:2])
        return round(uptime - age, 1)
    except ValueError:
        return None


def performance(vm: VM, suite: Suite) -> None:
    c = suite.check
    global INSTALLER
    INSTALLER = "script"            # measuring the installed system, not the installer's screens
    if not install_from_live(vm, suite):
        return
    r = vm.sh(f"echo '10.0.2.2 {EXAM_HOST}' >> /etc/hosts && primers-lab enable")
    c("setup: Lab Mode on", r.rc == 0, r.err)
    results = {"vm": {"memory_mb": vm.memory, "cpus": vm.cpus, "kvm": VM.kvm(),
                      "host_cpu": open("/proc/cpuinfo").read().split("model name", 1)[-1].split("\n", 1)[0]
                      .strip(" :\t")},
               "targets": PERF_TARGETS, "disks": {}}
    for profile in ("hdd", "ssd"):
        vm.disk_profile = profile
        boots = []
        for n in range(PERF_BOOTS):                             # one boot proves nothing
            power_on = cold_boot(vm)
            vm.wait_until(lambda: vm.sh("systemd-analyze").rc == 0, 600, f"{profile}: the boot to finish")
            vm.wait_until(lambda: vm.sh("systemctl is-active display-manager.service").out.strip() == "active",
                          300, f"{profile}: the login screen")
            bench = guest_benchmark(vm)
            boots.append({"power_on_to_login_s": power_on, "login_screen_after_kernel_s": greeter_after_kernel(vm),
                          "boot": bench.get("boot", {}),
                          "login_screen_chain": vm.sh("systemd-analyze critical-chain --no-pager "
                                                      "display-manager.service | head -25").out,
                          "lab_reset_log": vm.sh("journalctl -b -o short-monotonic --no-pager -t primers-lab "
                                                 "| tail -n 20").out,
                          "slowest_units": vm.sh("systemd-analyze blame --no-pager | head -12").out})
            vm.log(f"[{vm.name}] {profile} boot {n + 1}: power-on to login {power_on} s, "
                   f"kernel to login {boots[-1]['login_screen_after_kernel_s']} s")
        c(f"{profile}: {PERF_BOOTS} cold boots measured (power-on and kernel to the login screen)",
          all(b["power_on_to_login_s"] is not None and b["login_screen_after_kernel_s"] is not None for b in boots),
          json.dumps([[b["power_on_to_login_s"], b["login_screen_after_kernel_s"]] for b in boots]))
        c(f"{profile}: the system sees a {'rotating' if profile == 'hdd' else 'solid-state'} disk",
          bench.get("disk", {}).get("rotational") is (profile == "hdd"), json.dumps(bench.get("disk")))
        c(f"{profile}: boot to the login screen measured", all(b["boot"].get("to_login") is not None for b in boots),
          json.dumps([b["boot"] for b in boots]))
        power_on = spread([b["power_on_to_login_s"] for b in boots])
        greeter_s = spread([b["login_screen_after_kernel_s"] for b in boots])
        to_login = spread([b["boot"].get("to_login") for b in boots])
        boot = boots[-1]["boot"]
        slowest, dm_chain, lab_log = (boots[-1][k] for k in ("slowest_units", "login_screen_chain", "lab_reset_log"))
        chain = vm.sh("systemd-analyze critical-chain --no-pager graphical.target | head -25").out
        time.sleep(120)                                         # idle at the login screen
        login_ram = guest_benchmark(vm).get("memory", {}).get("used_mb")
        prefer_lab_at_login(vm)
        desktop = sign_in_lab(vm, suite, f"perf-{profile}-desktop", signed_in=lab_desktop_pid)
        c(f"{profile}: the lab account's desktop", bool(desktop))
        time.sleep(120)                                         # idle at the desktop
        bench_desk = guest_benchmark(vm)
        desk_ram = bench_desk.get("memory", {}).get("used_mb")
        top = vm.sh("ps -eo rss,comm --sort=-rss --no-headers | head -12").out
        vm.sh("loginctl terminate-user lab")
        vm.wait_until(lambda: vm.sh("pgrep -u lab").rc != 0, 120, "the lab session to end")
        r = vm.sh(f"primers-exam start {EXAM_URL}", timeout=600)
        c(f"{profile}: exam started", r.rc == 0, r.out + r.err)
        # Candidates sit down after the exam is started: by then the exam
        # browser has been read into memory (primers-exam-prewarm)
        t0 = time.time()
        vm.wait_until(lambda: vm.sh("systemctl is-active primers-exam-prewarm.service").out.strip()
                      not in ("activating", "active"), 300, f"{profile}: the exam browser loaded into memory")
        prewarm_s = round(time.time() - t0, 1)
        kiosk_s, kiosk_steps = kiosk_open_seconds(vm, suite, f"perf-{profile}-kiosk")
        c(f"{profile}: time to the exam page measured", kiosk_s is not None)
        vm.sh("primers-exam stop", timeout=600)
        vm.wait_until(lambda: vm.sh("pgrep -u lab").rc != 0, 120, "the lab session to end")
        results["disks"][profile] = {"power_on_to_login_s": power_on, "login_screen_after_kernel_s": greeter_s,
                                     "services_up_after_kernel_s": to_login, "boots": boots,
                                     "exam_browser_prewarm_s": prewarm_s,
                                     "kiosk_steps": kiosk_steps, "boot": boot,
                                     "login_screen_ram_mb": login_ram, "desktop_ram_mb": desk_ram,
                                     "kiosk_s": kiosk_s, "memory": bench_desk.get("memory", {}),
                                     "slowest_units": slowest, "critical_chain": chain,
                                     "login_screen_chain": dm_chain, "lab_reset_log": lab_log, "top_rss_kb": top}
        target = PERF_TARGETS["boot_hdd_s" if profile == "hdd" else "boot_ssd_s"]
        for what, value in (("power-on to login screen", power_on), ("kernel start to login screen", greeter_s),
                            ("kernel start to all services up", to_login)):
            if value is None:
                suite.note(f"{profile}: {what}: not measured")
                continue
            suite.note(f"{profile}: {what} over {value['n']} cold boots: median {value['median']} s "
                       f"({'meets' if value['median'] < target else 'MISSES'}), worst {value['worst']} s "
                       f"({'meets' if value['worst'] < target else 'MISSES'}) (target < {target} s); "
                       f"each: {value['each']}")
        for what, value, limit, unit in (("idle RAM at the desktop", desk_ram, PERF_TARGETS["idle_ram_mb"], "MB"),
                                         ("idle RAM at the login screen", login_ram, PERF_TARGETS["idle_ram_mb"], "MB"),
                                         ("sign-in to exam page", kiosk_s, PERF_TARGETS["kiosk_s"], "s")):
            verdict = "n/a" if value is None else ("meets" if value < limit else "MISSES")
            suite.note(f"{profile}: {what} {value} {unit} (target < {limit} {unit}): {verdict}")
    with open(os.path.join(suite.out, "performance.json"), "w") as f:
        json.dump(results, f, indent=2)


# ------------------------------------------------------------------ #
#  Brand: the boot splash (white P on Night Ink, its green cursor
#  blinking in 0.5 s steps), login screen, desktop, exam kiosk; and the
#  reduced-motion switch. Screenshots for docs/screenshots/.
# ------------------------------------------------------------------ #

NIGHT_INK, CHALK, READY_GREEN = (18, 22, 28), (245, 242, 234), (30, 158, 98)


def splash_state(path: str) -> Optional[str]:
    """'on' or 'off' when the screen is the boot splash (Night Ink with the
    Chalk P in the middle, its green cursor shown or not), else None."""
    return splash_cursor(path)[0]


def near(p, rgb, tol: int) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(p, rgb))


def cursor_state(ppm: str, box) -> Optional[str]:
    """The cursor's state from a raw screen dump, looking only where the
    cursor was found (fast enough to time its blink); None when the screen
    is no longer the splash."""
    from PIL import Image
    x0, y0, x1, y1 = box
    with Image.open(ppm) as img:
        img = img.convert("RGB")
        if not all(near(img.getpixel(xy), NIGHT_INK, 6) for xy in ((4, 4), (img.width - 5, img.height - 5))):
            return None
        region = img.crop((x0 - 2, y0 - 2, x1 + 3, y1 + 3))
        green = sum(1 for p in region.getdata() if near(p, READY_GREEN, 14))
    return "on" if green >= max(4, (x1 - x0) * (y1 - y0) // 4) else "off"


def splash_cursor(path: str):
    """(state, the cursor's box when it is shown) for a full screenshot."""
    from PIL import Image
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        small = img.resize((64, 40))
    ink = sum(1 for p in small.getdata() if all(abs(a - b) <= 6 for a, b in zip(p, NIGHT_INK)))
    if ink < 64 * 40 * 0.85:
        return None, None
    chalk = [b for b in colour_boxes(path, CHALK, tol=12)[0] if b[4] >= 20]
    middle = [b for b in chalk if abs((b[0] + b[2]) / 2 - w / 2) < w * 0.12 and abs((b[1] + b[3]) / 2 - h / 2) < h * 0.2]
    if not middle:
        return None, None
    px0, py0, px1, py1, _ = max(middle, key=lambda b: b[4])
    green = [b for b in colour_boxes(path, READY_GREEN, tol=14)[0]
             if b[4] >= 6 and px0 - 10 <= b[0] and b[2] <= px1 + 60 and py0 <= b[1] and b[3] <= py1 + 30]
    if not green:
        return "off", None
    return "on", max(green, key=lambda b: b[4])[:4]


def brand(vm: VM, suite: Suite) -> None:
    c = suite.check
    vm.start()
    t0, seen, last, box, flips = time.time(), {}, None, None, 0
    samples = []                        # (time, state) from fast samples of the cursor only
    # Whether the desktop is up is asked in the background: the guest agent can
    # take seconds to answer, and the screen must be sampled without pauses
    desktop = threading.Event()

    def watch_desktop() -> None:
        while not desktop.is_set() and time.time() - t0 < 1200:
            try:
                vm.wait_agent(timeout=10)
                if vm.sh("pgrep -x openbox").rc == 0:
                    desktop.set()
                    return
            except VMError:
                pass
            time.sleep(2)
    threading.Thread(target=watch_desktop, daemon=True).start()
    while not desktop.is_set() and time.time() - t0 < 1200:
        state = None
        if box:                         # the cursor found: sample just it, fast
            ppm = vm.screendump_now("_blink")
            state = cursor_state(ppm, box)
            if state:
                samples.append((time.time(), state))
                if not seen.get(state):     # keep a picture of each state for the docs
                    from PIL import Image
                    seen[state] = os.path.join(vm.workdir, f"brand-01-splash-cursor-{state}.png")
                    with Image.open(ppm) as img:
                        img.save(seen[state])
            else:
                box = None
        if not box:
            path = vm.screenshot("_boot")
            state, found = splash_cursor(path)
            if state and not seen.get(state):
                seen[state] = os.path.join(vm.workdir, f"brand-01-splash-cursor-{state}.png")
                shutil.copy(path, seen[state])
            box = found or box
        if state:
            seen.setdefault(state, "")
            if last and state != last:
                flips += 1              # any change seen, however slow the sampling
            last = state
    # Changes between fast samples taken close together (a slow sample can hide a blink)
    changes = [b[0] for a, b in zip(samples, samples[1:]) if a[1] != b[1] and b[0] - a[0] < 0.2]
    c("boot splash: the white P on Night Ink, with its green cursor", "on" in seen, repr(seen))
    c("boot splash: the cursor blinks (frames without it too)", "off" in seen and flips >= 2,
      f"{flips} changes seen; {len(changes)} between fast samples ({len(samples)} taken)")
    gaps = [b - a for a, b in zip(changes, changes[1:]) if b - a < 1.5]
    steps = sorted(b[0] - a[0] for a, b in zip(samples, samples[1:]))
    step = steps[len(steps) // 2] if steps else 9.0
    if gaps and VM.kvm() and step < 0.15:
        half = sorted(gaps)[len(gaps) // 2]
        c("boot splash: the cursor changes every ~0.5 s (a 1.0 s blink, in steps)", 0.35 <= half <= 0.7,
          f"median {half:.2f} s over {len(gaps)} changes, sampled every {step:.2f} s")
    else:
        suite.note(f"blink timing not checked ({'emulated CPU' if not VM.kvm() else 'sampling too slow'}): "
                   f"{len(changes)} changes, sampled every {step:.2f} s")
    vm.wait_agent(timeout=1200)
    vm.wait_until(lambda: screen_drawn(vm), 300, "the desktop to be drawn")
    vm.wait_until(lambda: vm.sh("pgrep -u primers -x xterm").rc == 0, 300, "the PRIMERS Brain window")
    time.sleep(15)
    vm.pointer_away(*image_size(vm.screenshot("brand-02-desktop")))
    time.sleep(2)
    vm.screenshot("brand-02-desktop")                       # the Brain window: app icon, window frame
    c("the Brain window shows the Primers app icon",
      "primers_48x48.xpm" in vm.sh("tr '\\0' ' ' < /proc/$(pgrep -u primers -x xterm | head -1)/cmdline").out)
    vm.sh("pkill -u primers -x xterm")
    time.sleep(5)
    vm.screenshot("brand-02-desktop-wallpaper")
    c("the theme files: blinking and still splashes from the official app icon",
      vm.sh("test -f /usr/share/plymouth/themes/primers-still/throbber-0032.png && "
            "cmp -s /usr/share/plymouth/themes/primers/throbber-0001.png /usr/share/plymouth/themes/primers-still/throbber-0032.png && "
            "! cmp -s /usr/share/plymouth/themes/primers/throbber-0001.png /usr/share/plymouth/themes/primers/throbber-0032.png").rc == 0)
    # Plymouth plays a throbber's frames over a fixed 2 s: on 8, off 8, twice = 0.5 s steps
    sums = vm.sh("cd /usr/share/plymouth/themes/primers && md5sum throbber-*.png | cut -c1-32").out.split()
    pattern = "".join("A" if h == sums[0] else "B" for h in sums) if sums else ""
    c("the blink's frames: the cursor on for 8 frames and off for 8, twice (0.5 s steps in Plymouth's 2 s)",
      pattern == "AAAAAAAABBBBBBBBAAAAAAAABBBBBBBB", pattern)

    # Reduced motion on a running system: the still splash and no GTK animations
    r = vm.sh("primers-reduce-motion on && primers-reduce-motion status && "
              "update-alternatives --query default.plymouth | sed -n 's/^Value: //p' && cat /etc/gtk-3.0/settings.ini",
              timeout=300)
    c("reduced motion: the splash's cursor stays still, GTK stops animating",
      r.rc == 0 and "Reduced motion: on" in r.out and "primers-still.plymouth" in r.out
      and "gtk-enable-animations=false" in r.out, r.out + r.err)
    r = vm.sh("primers-reduce-motion off && update-alternatives --query default.plymouth | sed -n 's/^Value: //p'",
              timeout=300)
    c("reduced motion off: the blinking splash again", r.rc == 0 and "primers/primers.plymouth" in r.out, r.out + r.err)

    # The login screen and the exam kiosk
    r = vm.sh(f"echo '10.0.2.2 {EXAM_HOST}' >> /etc/hosts && primers-lab enable && "
              "systemctl start primers-lab-reset.service")
    c("setup: Lab Mode on", r.rc == 0, r.err)
    vm.sh("loginctl terminate-user primers")
    vm.wait_until(lambda: vm.sh("pgrep -u lightdm -f lightdm-gtk-greeter").rc == 0, 300, "the login screen")
    vm.wait_until(lambda: screen_drawn(vm), 300, "the login screen to be drawn")
    time.sleep(5)
    vm.screenshot("brand-03-login-screen")
    r = vm.sh(f"primers-exam start {EXAM_URL}", timeout=300)
    c("setup: exam started", r.rc == 0, r.out + r.err)
    kiosk = sign_in_lab(vm, suite, "brand-04-exam-kiosk")
    c("the exam kiosk", bool(kiosk))
    vm.wait_until(lambda: journal_times(vm, "exam page shown"), 300, "the exam page")

    def page_text() -> bool:              # the exam's dark text painted on its white page
        from PIL import Image
        with Image.open(vm.screenshot("brand-04-exam-kiosk")) as img:
            page = img.convert("L").crop((0, KIOSK_BAR + 10, img.width, img.height))
        # Counted at full size (shrinking first greys thin text out): text is ~1.1-1.4 %
        # of the demo exam page, 0 % of a blank one
        return sum(1 for v in page.getdata() if v < 110) >= page.width * page.height * 0.003
    vm.wait_until(page_text, 300, "the exam page's text on screen", interval=5)
    settled(vm, "brand-04-exam-kiosk")
    vm.sh("primers-exam stop", timeout=300)


# ------------------------------------------------------------------ #
#  Primers ID: OIDC sign-in in the image against a mock provider on this
#  machine (the device flow, approved here as a phone would), then offline
#  sign-in with the PIN when the provider can't be reached
# ------------------------------------------------------------------ #

ID_PORT = 8790


def primers_id_scenario(vm: VM, suite: Suite) -> None:
    c = suite.check
    sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "primers-os", "tests"))
    from mock_oidc import MockProvider
    provider = MockProvider(issuer=f"http://10.0.2.2:{ID_PORT}", port=ID_PORT)
    try:
        vm.start()
        vm.wait_agent(timeout=1200)
        vm.wait_until(lambda: vm.sh("pgrep -x openbox").rc == 0, 600, "the live desktop")
        r = vm.sh("primers-id status; sed -n 's/^issuer = //p' /etc/primers/id.conf")
        c("the image is set up for the Primers ID service", "https://id.primersgroup.ng" in r.out, r.out)
        # Ask Primers answers from the one knowledge base, installed from docs/knowledge
        r = vm.sh("test -f /usr/share/primers/knowledge/PRIMERS_KNOWLEDGE.md && "
                  "! test -e /usr/share/primers/brain/knowledge && primers -c 'ask who founded Primers?'", timeout=120)
        c("Ask Primers answers from the knowledge base in /usr/share/primers/knowledge",
          r.rc == 0 and "Jothan Jerry Kato" in r.out, (r.out + r.err)[-600:])
        # The test provider: a change to the configuration only
        r = vm.sh(f"printf '[primers-id]\\nissuer = http://10.0.2.2:{ID_PORT}\\nclient_id = primers-os\\n"
                  "allow_http = true\\n' > /etc/primers/id.conf")
        c("setup: the test provider, by configuration", r.rc == 0, r.err)

        # The person signs in: the PC shows a code, they approve it (here: the test, as their phone)
        vm.sh("rm -f /tmp/id-login.out; setsid -f su - primers -c 'printf \"2468\\n\" | primers-id login --pin-stdin "
              "> /tmp/id-login.out 2>&1; echo rc=$? >> /tmp/id-login.out' > /dev/null 2>&1 < /dev/null")
        vm.wait_until(lambda: provider.devices, 120, "the device sign-in to start")
        code = next(iter(provider.devices.values()))["user_code"]
        shown = vm.sh("cat /tmp/id-login.out").out
        vm.wait_until(lambda: code in vm.sh("cat /tmp/id-login.out").out, 60, "the code on screen")
        c("the PC shows the code to type at Primers ID", code in vm.sh("cat /tmp/id-login.out").out, shown)
        provider.approve(code)
        vm.wait_until(lambda: "rc=" in vm.sh("cat /tmp/id-login.out").out, 120, "the sign-in to finish")
        out = vm.sh("cat /tmp/id-login.out").out
        c("signed in with Primers ID (token signature and claims checked)",
          "rc=0" in out and "Signed in as Ada Okafor" in out, out)
        st = vm.as_user("primers", "primers-id status --json")
        try:
            session = json.loads(st.out)
        except ValueError:
            session = {}
        c("the session names the person and keeps no secrets in view",
          session.get("sub") == "pid-0001" and "refresh_token" not in session and "pin_hash" not in session,
          st.out)
        perms = vm.sh("stat -c '%a %U' /home/primers/.local/share/primers/id /home/primers/.local/share/primers/id/session.json").out.split("\n")
        c("the session is readable by its owner only", perms[:2] == ["700 primers", "600 primers"], repr(perms))

        # No way to reach Primers ID: offline sign-in with the PIN
        vm.sh("ip route add blackhole 10.0.2.2/32")
        r = vm.as_user("primers", "printf '\\n' | primers-id login --pin-stdin", timeout=120)
        c("without the provider, online sign-in says so and points to the PIN",
          r.rc == 2 and "--offline" in r.err, r.out + r.err)
        r = vm.as_user("primers", "printf '0000\\n' | primers-id login --offline --pin-stdin")
        c("a wrong PIN is refused", r.rc == 1 and "wrong PIN" in r.err, r.out + r.err)
        r = vm.as_user("primers", "printf '2468\\n' | primers-id login --offline --pin-stdin")
        c("offline sign-in with the PIN", r.rc == 0 and "offline, with your PIN" in r.out, r.out + r.err)
        vm.sh("ip route del blackhole 10.0.2.2/32")
        r = vm.as_user("primers", "primers-id logout && primers-id status", timeout=60)
        c("sign out, and the refresh token is revoked at the provider",
          "Not signed in" in r.out and len(provider.revoked) == 1, r.out + r.err)
    finally:
        provider.close()


PRIVACY_TITLE = "PRIMERS OS privacy notice"


def privacy_scenario(vm: VM, suite: Suite) -> None:
    """The privacy notice at the first sign-in of an installed PC and in the
    menu, the logs' retention (the daily run, an exam in progress, a new
    retention time, the journal) and exporting them."""
    c = suite.check
    global INSTALLER
    INSTALLER = "script"
    if not install_from_live(vm, suite):
        return
    r = vm.sh("systemctl is-enabled primers-privacy-retention.timer; "
              "for t in motd-news ua-timer apport-autoreport; do systemctl is-enabled $t.timer; done; "
              "python3 -c 'import json; print(json.load(open(\"/etc/firefox/policies/policies.json\"))[\"policies\"])'; "
              "systemd-analyze cat-config systemd/journald.conf | grep -E '^Max(Retention|File)Sec='")
    out = r.out.split("\n")
    c("the image: the retention timer on; motd news, Ubuntu Pro and crash-report timers off; "
      "Firefox telemetry off; the journal kept 90 days",
      out[0] == "enabled" and all(x != "enabled" for x in out[1:4])
      and "'DisableTelemetry': True" in r.out and "MaxRetentionSec=90day" in r.out, r.out + r.err)

    # The first sign-in of an account shows the notice until it is confirmed
    def notice_open() -> bool:
        return vm.as_user("labadmin", f"xwininfo -name '{PRIVACY_TITLE}'").rc == 0
    vm.sh("mkdir -p /etc/lightdm/lightdm.conf.d && "
          "printf '[Seat:*]\\nautologin-user=labadmin\\n' > /etc/lightdm/lightdm.conf.d/99-vm-test.conf && "
          "systemctl restart display-manager.service", timeout=180)
    vm.wait_until(lambda: vm.sh("pgrep -u labadmin -x openbox").rc == 0, 300, "the staff desktop")
    try:
        vm.wait_until(notice_open, 120, "the privacy notice")
    except VMError:
        pass
    time.sleep(3)
    vm.screenshot("privacy-01-first-sign-in")
    c("the first sign-in shows the privacy notice", notice_open())
    vm.key("ret")                       # OK does nothing until "I have read" is ticked
    time.sleep(2)
    c("it can't be dismissed with OK before 'I have read this privacy notice' is ticked", notice_open())
    for k in ("tab", "spc", "ret"):     # tick it, then OK
        vm.key(k)
        time.sleep(1)
    vm.wait_until(lambda: not notice_open(), 30, "the notice to close")
    ack = vm.sh("cat /home/labadmin/.local/state/primers/privacy-notice").out.strip()
    c("ticked and OK: it closes and is remembered for this account", not notice_open() and ack.count("-") == 2, ack)
    vm.sh("loginctl terminate-user labadmin; sleep 3; systemctl restart display-manager.service", timeout=180)
    vm.wait_until(lambda: vm.sh("pgrep -u labadmin -x openbox").rc == 0, 300, "the staff desktop again")
    time.sleep(20)
    c("the next sign-in doesn't show it again", not notice_open())
    vm.as_user("labadmin", "setsid -f primers-privacy notice > /dev/null 2>&1 < /dev/null")
    try:
        vm.wait_until(notice_open, 60, "the notice from the menu")
    except VMError:
        pass
    time.sleep(2)
    vm.screenshot("privacy-02-from-the-menu")
    menu = vm.sh("grep -c 'primers-privacy notice</command>' /home/labadmin/.config/openbox/menu.xml").out.strip()
    c("System › Privacy notice opens it any time", notice_open() and menu == "1", menu)
    vm.sh("pkill -u labadmin -x zenity; rm -f /etc/lightdm/lightdm.conf.d/99-vm-test.conf")
    r = vm.sh("primers-privacy notice --text; primers-privacy notice --short")
    flat = " ".join(r.out.split())                  # the notice is wrapped at 74 columns
    c("the notice names the NDPA, the retention time and the rights; the lab account's short version",
      "Nigeria Data Protection Act 2023" in flat and "Kept for 90 days" in flat
      and "ndpc.gov.ng" in flat and "System › Privacy notice" in flat, r.out[-800:])

    # Retention: records older than 90 days go at the daily run, the rest stay
    def line(days_ago: int, message: str) -> str:
        return ("python3 -c 'import json,datetime,sys; t=datetime.datetime.now(datetime.timezone.utc)"
                f"-datetime.timedelta(days={days_ago}); print(json.dumps({{\"time\": t.strftime(\"%Y-%m-%dT%H:%M:%S.%fZ\"), "
                f"\"message\": \"{message}\", \"uid\": 0, \"user\": \"root\", \"pid\": 1, \"boot\": \"\"}}))'")
    setup = " && ".join([
        "install -d -m 2750 -o root -g adm /var/log/primers",
        f"{{ {line(120, 'exam started: https://old.example')}; {line(95, 'visited https://old.example/q1')}; "
        f"{line(40, 'exam started: https://cbt.example')}; {line(1, 'visited https://cbt.example/q9')}; }}"
        " > /var/log/primers/exam.jsonl",
        "chown root:adm /var/log/primers/exam.jsonl && chmod 640 /var/log/primers/exam.jsonl",
        "cp /var/log/primers/exam.jsonl /var/log/primers/fleet.jsonl"])
    c("setup: an exam log with records 120, 95, 40 and 1 days old", vm.sh(setup).rc == 0)
    vm.sh("mkdir -p /etc/primers && printf 'URL=https://cbt.example\\n' > /etc/primers/exam.conf && "
          "systemctl start primers-privacy-retention.service")
    kept = vm.sh("grep -c . /var/log/primers/exam.jsonl; grep -c . /var/log/primers/fleet.jsonl").out.split()
    c("while an exam is running, the exam log is kept whole (the lab control log is pruned)",
      kept == ["4", "2"], repr(kept))
    vm.sh("rm -f /etc/primers/exam.conf; systemctl start primers-privacy-retention.service")
    r = vm.sh("cat /var/log/primers/exam.jsonl; stat -c '%a %U:%G' /var/log/primers/exam.jsonl")
    c("the daily run removes the exam records older than 90 days and keeps the rest (owner and mode too)",
      "old.example" not in r.out and r.out.count("cbt.example") == 2 and "640 root:adm" in r.out, r.out)
    r = vm.sh("primers-privacy retention --days 30 && systemctl is-active systemd-journald && "
              "systemd-analyze cat-config systemd/journald.conf | grep '^MaxRetentionSec=' && "
              "grep -c . /var/log/primers/exam.jsonl && journalctl -n1 -q --no-pager > /dev/null && echo journal-ok")
    c("a new retention time (30 days): set, applied at once, and the journal follows",
      "MaxRetentionSec=30day" in r.out and r.out.strip().split("\n")[-2:] == ["1", "journal-ok"]
      and "active" in r.out, r.out + r.err)
    r = vm.sh("rm -rf /root/export && primers-privacy export /root/export && cd /root/export && "
              "sha256sum -c SHA256SUMS && head -n1 exam.csv && stat -c '%a' /root/export")
    c("export: JSON lines and CSV of both logs, with checksums that check, readable by root only",
      r.rc == 0 and "exam.jsonl: OK" in r.out and "fleet.csv: OK" in r.out
      and "time,user,uid,pid,boot,message" in r.out and r.out.strip().endswith("700"), r.out + r.err)
    r = vm.sh("rm -rf /root/exam-export && primers-exam log --all --export /root/exam-export && "
              "cd /root/exam-export && sha256sum -c SHA256SUMS")
    c("primers-exam log --export makes the same files for the exam log", r.rc == 0, r.out + r.err)


SCENARIOS = {"exam-escape": exam_escape, "exam-power-cut": exam_power_cut, "installed": installed_system,
             "exam-network": exam_network, "exam-moodle": exam_moodle, "exam-tcexam": exam_tcexam,
             "fleet": fleet_scenario, "performance": performance, "brand": brand,
             "primers-id": primers_id_scenario, "privacy": privacy_scenario}
DISK_SCENARIOS = ("exam-power-cut", "installed", "performance", "privacy")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--iso", required=True)
    ap.add_argument("--out", default="vm-results")
    ap.add_argument("--firmware", default="bios", choices=["bios", "uefi", "sb"])
    ap.add_argument("--installer", default="calamares", choices=["calamares", "script"],
                    help="installed scenario: the real installer's screens, or tests/vm/install.sh")
    ap.add_argument("--disk-dir", help="where the VM disk goes (default: a temporary directory, "
                                       "deleted afterwards; never the results directory)")
    args = ap.parse_args()
    global INSTALLER
    INSTALLER = args.installer
    os.makedirs(args.out, exist_ok=True)
    serve(os.path.join(HERE, "www"), EXAM_PORT)
    serve(os.path.join(HERE, "www"), CDN_PORT)                      # the "CDN" (two guest addresses)
    global HOST_IPV6
    try:
        serve(os.path.join(HERE, "www"), V6_PORT, "::1")            # an IPv6-only exam server
        serve(os.path.join(HERE, "www"), V6_OTHER_PORT, "::1")      # another IPv6 server, not allowed
    except OSError as e:
        HOST_IPV6 = False
        print(f"(this machine has no IPv6: {e})", flush=True)
    disk_dir = args.disk_dir or tempfile.mkdtemp(prefix="primers-vm-disk-")
    os.makedirs(disk_dir, exist_ok=True)
    fleet_test = args.scenario == "fleet"           # four VMs at once: smaller ones
    vm = VM(args.out, iso=os.path.abspath(args.iso), firmware=args.firmware,
            name="invigilator" if fleet_test else args.scenario,
            memory=2048 if fleet_test else PERF_MEMORY_MB if args.scenario == "performance" else 4096,
            cpus=PERF_CPUS if args.scenario == "performance" else 2,
            extra=lan_nic(0) if fleet_test else (),
            disk=os.path.join(disk_dir, f"{args.scenario}.qcow2") if args.scenario in DISK_SCENARIOS else None)
    relay = os.path.join(HERE, "relay.py")
    vm.guestfwd = [(CDN_OLD, CDN_PORT, f"{sys.executable} {relay} {CDN_PORT}"),
                   (CDN_NEW, CDN_PORT, f"{sys.executable} {relay} {CDN_PORT}")]
    suite = Suite(vm, args.out)
    print(f"== {args.scenario} ==", flush=True)
    try:
        suite.run_step(args.scenario, lambda: SCENARIOS[args.scenario](vm, suite))
    finally:
        with_shot = vm.proc is not None
        if with_shot:
            try:
                vm.screenshot("99-final")
            except Exception:
                pass
        vm.stop()
        if not args.disk_dir:
            shutil.rmtree(disk_dir, ignore_errors=True)
    return 0 if suite.save() else 1


if __name__ == "__main__":
    sys.exit(main())
