#!/usr/bin/env python3
"""
End-to-end tests of PRIMERS OS in a virtual machine.

  run_vm_tests.py exam-escape --iso primers-os.iso --out results/

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
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vmlib import VM, VMError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EXAM_PORT = 8765
EXAM_HOST = "cbt.primers.test"
EXAM_URL = f"http://{EXAM_HOST}:{EXAM_PORT}/exam.html"


def serve(directory: str, port: int) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


class Suite:
    def __init__(self, vm: VM, out: str):
        self.vm, self.out = vm, out
        self.results = []

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
        failed = [r for r in self.results if not r["passed"]]
        print(f"\n{len(self.results) - len(failed)} passed, {len(failed)} failed")
        return not failed


# ------------------------------------------------------------------ #
#  Exam Mode escape routes (ADR 0003)
# ------------------------------------------------------------------ #

def kiosk_pid(vm: VM) -> str:
    return vm.sh("pgrep -u lab -f 'litebee --kiosk' | head -n1").out.strip()


def sign_in_lab(vm: VM, suite: Suite, shot: str) -> str:
    vm.wait_until(lambda: vm.sh("pgrep -u lightdm -f lightdm-gtk-greeter").rc == 0, 180, "login screen")
    time.sleep(5)
    vm.key("tab")
    time.sleep(0.5)
    vm.key("ret")
    vm.wait_until(lambda: bool(kiosk_pid(vm)), 180, "the exam kiosk")
    time.sleep(8)
    vm.screenshot(shot)
    return kiosk_pid(vm)


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
    r = vm.sh(f"primers-exam start {EXAM_URL}", timeout=180)
    c("setup: exam started", r.rc == 0 and "sign out of the desktop" not in r.err, r.out + r.err)
    r = vm.sh("primers-exam status")
    c("setup: firewall, USB block and console lock in place", r.rc == 0, r.out)

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
    ended = True
    try:
        vm.wait_until(lambda: vm.sh("pgrep -u lab").rc != 0, 90, "the exam session to end")
    except VMError:
        ended = False
    c("a killed kiosk ends the session (no relaunch, no desktop)", ended
      and vm.sh("pgrep -u lightdm -f lightdm-gtk-greeter").rc == 0)
    c("the log records the stopped kiosk",
      "stopped unexpectedly" in vm.sh("journalctl -t primers-exam --no-pager").out)
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
    r = vm.sh("primers-exam stop", timeout=180)
    c("exam stops", r.rc == 0, r.out + r.err)
    state = vm.sh("getent passwd lab | cut -d: -f7; cat /proc/sys/kernel/sysrq; "
                  "systemctl show -p LoadState --value getty@tty2.service; "
                  "grep -c primers-exam /etc/hosts; ls /etc/X11/xorg.conf.d/ /etc/sysctl.d/ | grep -c primers-exam")
    lines = state.out.split()
    c("after the exam: shell, SysRq, consoles, hosts and display settings restored",
      lines[:3] == ["/bin/bash", "176", "loaded"] and lines[3:] == ["0", "0"], state.out)


SCENARIOS = {"exam-escape": exam_escape}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--iso", required=True)
    ap.add_argument("--out", default="vm-results")
    ap.add_argument("--firmware", default="bios", choices=["bios", "uefi", "sb"])
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    serve(os.path.join(HERE, "www"), EXAM_PORT)
    vm = VM(args.out, iso=os.path.abspath(args.iso), firmware=args.firmware, name=args.scenario)
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
    return 0 if suite.save() else 1


if __name__ == "__main__":
    sys.exit(main())
