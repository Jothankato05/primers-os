"""
Drive a PRIMERS OS virtual machine for end-to-end tests.

QEMU is controlled through QMP (keyboard, screenshots, power) and commands
run inside the guest through qemu-guest-agent (``guest-exec``, as root).
The agent ships in the image but only starts when a VM provides its virtio
channel (org.qemu.guest_agent.0), so on real hardware it never runs.

Used by run_vm_tests.py locally and in the ISO workflow (KVM on GitHub's
runners). Only the standard library and Pillow (for PNG screenshots).
"""

import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Callable, List, Optional, Sequence

OVMF_CODE = "/usr/share/OVMF/OVMF_CODE_4M.fd"
OVMF_CODE_SB = "/usr/share/OVMF/OVMF_CODE_4M.secboot.fd"
OVMF_VARS = "/usr/share/OVMF/OVMF_VARS_4M.fd"
OVMF_VARS_MS = "/usr/share/OVMF/OVMF_VARS_4M.ms.fd"

# QMP "send-key" names for characters
KEYS = {" ": "spc", "-": "minus", ".": "dot", "/": "slash", "_": "shift-minus", "\n": "ret",
        ":": "shift-semicolon", "=": "equal", ",": "comma", ";": "semicolon"}


class VMError(Exception):
    pass


class _JsonSocket:
    def __init__(self, path: str, timeout: float):
        deadline = time.time() + timeout
        while True:
            try:
                self.sock = socket.socket(socket.AF_UNIX)
                self.sock.connect(path)
                break
            except OSError:
                self.sock.close()
                if time.time() > deadline:
                    raise VMError(f"can't connect to {path}")
                time.sleep(0.5)
        self.buf = b""

    def send(self, obj) -> None:
        self.sock.sendall(json.dumps(obj).encode() + b"\n")

    def recv(self, timeout: float):
        self.sock.settimeout(timeout)
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise VMError("connection closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        line = line.lstrip(b"\xff")
        return json.loads(line) if line.strip() else self.recv(timeout)

    def close(self):
        self.sock.close()


class QMP(_JsonSocket):
    def __init__(self, path: str, timeout: float = 30):
        super().__init__(path, timeout)
        self.recv(timeout)                       # greeting
        self.call("qmp_capabilities")

    def call(self, cmd: str, timeout: float = 60, **args):
        self.send({"execute": cmd, "arguments": args} if args else {"execute": cmd})
        while True:
            reply = self.recv(timeout)
            if "return" in reply:
                return reply["return"]
            if "error" in reply:
                raise VMError(f"QMP {cmd}: {reply['error']}")


class QGA(_JsonSocket):
    """qemu-guest-agent client. Messages can be lost while the agent starts,
    so every exchange is preceded by guest-sync."""

    def __init__(self, path: str, timeout: float = 30):
        super().__init__(path, timeout)
        self._sync_id = int(time.time())

    def sync(self, timeout: float = 5) -> None:
        self._sync_id += 1
        self.buf = b""
        self.sock.sendall(b"\xff")
        self.send({"execute": "guest-sync-delimited", "arguments": {"id": self._sync_id}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            reply = self.recv(max(0.1, deadline - time.time()))
            if reply.get("return") == self._sync_id:
                return
        raise VMError("guest agent did not answer")

    def call(self, cmd: str, timeout: float = 30, **args):
        self.send({"execute": cmd, "arguments": args} if args else {"execute": cmd})
        reply = self.recv(timeout)
        if "error" in reply:
            raise VMError(f"QGA {cmd}: {reply['error']}")
        return reply.get("return")


class Result:
    def __init__(self, rc: int, out: str, err: str):
        self.rc, self.out, self.err = rc, out, err

    def __repr__(self):
        return f"Result(rc={self.rc}, out={self.out[:200]!r}, err={self.err[:200]!r})"


# Disk profiles for performance tests: (rotation rate the guest sees, QEMU
# I/O limits). HDD: a 7200 rpm desktop disk, ~120 random I/Os a second and
# ~110 MB/s sequential. SSD: a SATA SSD, ~20000 I/Os a second, ~500 MB/s.
DISK_PROFILES = {
    "hdd": (7200, {"iops-total": 120, "bps-total": 110 * 1024 * 1024}),
    "ssd": (1, {"iops-total": 20000, "bps-total": 500 * 1024 * 1024}),
}


class VM:
    def __init__(self, workdir: str, iso: Optional[str] = None, disk: Optional[str] = None,
                 firmware: str = "bios", memory: int = 4096, cpus: int = 2, name: str = "vm",
                 extra: Sequence[str] = (), log: Callable[[str], None] = print,
                 disk_profile: Optional[str] = None):
        self.workdir, self.iso, self.disk = workdir, iso, disk
        self.disk_profile = disk_profile     # None (virtio, as fast as the host), "hdd" or "ssd"
        self.firmware, self.memory, self.cpus, self.name = firmware, memory, cpus, name
        self.extra = list(extra)
        self.guestfwd: List[tuple] = []     # (guest address, port, host command) per extra address
        self.log = log
        self.proc: Optional[subprocess.Popen] = None
        self.qmp: Optional[QMP] = None
        self._qga: Optional[QGA] = None
        os.makedirs(workdir, exist_ok=True)
        # Unix socket paths are limited to 107 bytes: use a short directory
        # when the work directory's path is long
        sockdir = workdir if len(os.path.abspath(workdir)) + len(name) < 90 else \
            tempfile.mkdtemp(prefix="pvm-")
        self.qmp_path = os.path.join(sockdir, f"{name}.qmp")
        self.qga_path = os.path.join(sockdir, f"{name}.qga")
        self.vars_path = os.path.join(workdir, f"{name}-vars.fd")
        # The guest's first serial port (GRUB can be told to use it too)
        self.serial_path = os.path.join(workdir, f"{name}-serial.log")

    @staticmethod
    def kvm() -> bool:
        return os.access("/dev/kvm", os.R_OK | os.W_OK)

    def argv(self) -> List[str]:
        args = ["qemu-system-x86_64", "-m", str(self.memory), "-smp", str(self.cpus),
                "-vga", "std", "-display", "none", "-device", "qemu-xhci", "-device", "usb-tablet",
                "-qmp", f"unix:{self.qmp_path},server=on,wait=off",
                "-chardev", f"socket,path={self.qga_path},server=on,wait=off,id=qga0",
                "-device", "virtio-serial", "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0",
                "-nic", "user,model=e1000" + "".join(f",guestfwd=tcp:{a}:{p}-cmd:{c}" for a, p, c in self.guestfwd),
                "-chardev", f"file,id=ser0,path={self.serial_path},append=on", "-serial", "chardev:ser0"]
        args += ["-accel", "kvm", "-cpu", "host"] if self.kvm() else ["-accel", "tcg,thread=multi"]
        if self.firmware in ("uefi", "sb"):
            code = OVMF_CODE_SB if self.firmware == "sb" else OVMF_CODE
            if not os.path.exists(self.vars_path):
                shutil.copy(OVMF_VARS_MS if self.firmware == "sb" else OVMF_VARS, self.vars_path)
            args += ["-drive", f"if=pflash,format=raw,readonly=on,file={code}",
                     "-drive", f"if=pflash,format=raw,file={self.vars_path}"]
            if self.firmware == "sb":
                args += ["-machine", "q35,smm=on", "-global", "driver=cfi.pflash01,property=secure,value=on"]
        if self.disk and self.disk_profile in DISK_PROFILES:
            # A SATA-like disk the guest sees as rotating (HDD) or not (SSD), limited
            # to what such a disk does (docs/benchmarks.md)
            rotation, limits = DISK_PROFILES[self.disk_profile]
            args += ["-device", "virtio-scsi-pci,id=scsi0",
                     "-drive", f"file={self.disk},if=none,id=disk0,format=qcow2" +
                     "".join(f",throttling.{k}={v}" for k, v in limits.items()),
                     "-device", f"scsi-hd,drive=disk0,bus=scsi0.0,rotation_rate={rotation}"]
        elif self.disk:
            args += ["-drive", f"file={self.disk},if=virtio,format=qcow2"]
        if self.iso:
            args += ["-drive", f"file={self.iso},media=cdrom,if=none,id=cd0,readonly=on",
                     "-device", f"ide-cd,drive=cd0,bootindex={0 if not self.disk else 1}"]
        return args + self.extra

    # ---------------- lifecycle ----------------

    def start(self) -> "VM":
        for path in (self.qmp_path, self.qga_path):
            if os.path.exists(path):
                os.unlink(path)
        self.log(f"[{self.name}] starting ({'KVM' if self.kvm() else 'TCG'}, {self.firmware})")
        self.proc = subprocess.Popen(self.argv(), stdout=subprocess.DEVNULL,
                                     stderr=open(os.path.join(self.workdir, f"{self.name}.log"), "ab"))
        self.qmp = QMP(self.qmp_path)
        self._qga = None
        return self

    def power_cut(self) -> None:
        """Pull the plug: QEMU is killed, whatever the guest had not written is lost."""
        self.log(f"[{self.name}] power cut")
        if self.proc:
            self.proc.kill()
            self.proc.wait()
        self.proc, self.qmp, self._qga = None, None, None

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.qmp.call("quit")
            except Exception:
                pass
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    # ---------------- guest agent ----------------

    def wait_agent(self, timeout: float = 600) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self._qga is None:
                    self._qga = QGA(self.qga_path, timeout=10)
                self._qga.sync(timeout=5)
                self._qga.call("guest-ping")
                return
            except (VMError, OSError):
                if self._qga:
                    self._qga.close()
                self._qga = None
                time.sleep(3)
        raise VMError("the guest agent never came up")

    def boot_id(self) -> str:
        return self.sh("cat /proc/sys/kernel/random/boot_id").out.strip()

    def reboot(self, timeout: float = 900) -> None:
        """A clean restart from inside the guest; returns once it is back."""
        before = self.boot_id()
        self.log(f"[{self.name}] reboot")
        try:
            self._qga.sync()
            self._qga.call("guest-exec", path="/bin/systemctl", arg=["reboot"])
        except (VMError, OSError):
            pass                        # the agent may go before it answers
        self._qga.close()
        self._qga = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(5)
            try:
                self.wait_agent(timeout=max(10, deadline - time.time()))
                if self.boot_id() not in ("", before):
                    return
            except VMError:
                pass
            if self._qga:
                self._qga.close()
            self._qga = None
        raise VMError("the guest did not come back after a reboot")

    def run(self, argv: Sequence[str], timeout: float = 120, input_text: Optional[str] = None) -> Result:
        if self._qga is None:
            self.wait_agent()
        self._qga.sync()
        args = {"path": argv[0], "arg": list(argv[1:]), "capture-output": True}
        if input_text is not None:
            args["input-data"] = base64.b64encode(input_text.encode()).decode()
        pid = self._qga.call("guest-exec", **args)["pid"]
        deadline = time.time() + timeout
        while True:
            status = self._qga.call("guest-exec-status", pid=pid)
            if status.get("exited"):
                dec = lambda k: base64.b64decode(status.get(k, "")).decode("utf-8", "replace")  # noqa: E731
                return Result(status.get("exitcode", -1), dec("out-data"), dec("err-data"))
            if time.time() > deadline:
                raise VMError(f"guest command timed out: {argv}")
            time.sleep(0.3)

    def sh(self, script: str, timeout: float = 120) -> Result:
        return self.run(["/bin/sh", "-c", script], timeout=timeout)

    def as_user(self, user: str, script: str, timeout: float = 60) -> Result:
        """Run as `user` inside that user's X session (DISPLAY and XAUTHORITY found from it)."""
        prelude = (f'pid=$(pgrep -u {user} -o -x openbox || pgrep -u {user} -o -f litebee); '
                   'if [ -n "$pid" ]; then eval "$(tr "\\0" "\\n" < /proc/$pid/environ | '
                   'grep -E "^(DISPLAY|XAUTHORITY|DBUS_SESSION_BUS_ADDRESS)=" | sed "s/^/export /")"; fi; ')
        return self.run(["runuser", "-u", user, "--", "/bin/sh", "-c", prelude + script], timeout=timeout)

    def wait_until(self, check: Callable[[], bool], timeout: float, what: str, interval: float = 2) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if check():
                    return
            except VMError:
                pass
            time.sleep(interval)
        raise VMError(f"timed out waiting for {what}")

    def serial_size(self) -> int:
        try:
            return os.path.getsize(self.serial_path)
        except OSError:
            return 0

    def serial_text(self, since: int = 0) -> str:
        """What the guest wrote to its serial port, from byte `since` on."""
        try:
            with open(self.serial_path, "rb") as f:
                f.seek(since)
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    # ---------------- keyboard and screen ----------------

    def key(self, combo: str, hold_ms: int = 100) -> None:
        self.qmp.call("send-key", keys=[{"type": "qcode", "data": k} for k in combo.split("-")],
                      **{"hold-time": hold_ms})

    def type(self, text: str, gap: float = 0.03) -> None:
        for ch in text:
            self.key(KEYS.get(ch, ("shift-" + ch.lower()) if ch.isupper() else ch))
            time.sleep(gap)

    def type_then_settle(self, text: str) -> None:
        """Type, then wait for the keys to reach the guest: they queue in the
        emulated keyboard and arrive slower than they are sent, while a
        mouse click arrives at once (and would move focus too early)."""
        self.type(text, gap=0.25)
        time.sleep(1.5 + 0.1 * len(text))

    def click(self, x: int, y: int, width: int, height: int) -> None:
        """Left click at (x, y) on a width x height screen (usb-tablet: absolute)."""
        self.qmp.call("input-send-event", events=[
            {"type": "abs", "data": {"axis": "x", "value": int(x * 32767 / max(1, width - 1))}},
            {"type": "abs", "data": {"axis": "y", "value": int(y * 32767 / max(1, height - 1))}}])
        time.sleep(0.2)
        for down in (True, False):
            self.qmp.call("input-send-event", events=[{"type": "btn", "data": {"down": down, "button": "left"}}])
            time.sleep(0.1)

    def pointer_away(self, width: int, height: int) -> None:
        """Park the pointer in a corner (hover colours change what's on screen)."""
        self.qmp.call("input-send-event", events=[
            {"type": "abs", "data": {"axis": "x", "value": 0}},
            {"type": "abs", "data": {"axis": "y", "value": 32767}}])

    def screenshot(self, name: str) -> str:
        ppm = os.path.join(self.workdir, f"{name}.ppm")
        self.qmp.call("screendump", filename=ppm)
        time.sleep(0.3)
        try:
            from PIL import Image
            png = ppm[:-4] + ".png"
            Image.open(ppm).save(png)
            os.unlink(ppm)
            return png
        except ImportError:
            return ppm
