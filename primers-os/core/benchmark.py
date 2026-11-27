"""
PRIMERS OS - benchmark: measure this machine against the design targets.

The Primers knowledge base sets engineering targets for the OS (2 GB minimum
RAM, under 600 MB idle RAM, cold boot to the login screen in under 15 s on an
SSD or 30 s on an old hard disk, base install under 8 GB). The pilot plan asks
for real numbers from real lab hardware. ``benchmark`` in the Brain measures
them and saves a JSON report that can be collected from each machine.

The report holds hardware facts and timings only: no user names, files,
serial numbers or network addresses.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import time
from typing import Callable, Dict, List, Optional, Tuple

# From the knowledge base, section "Design targets".
TARGETS = {
    "min_ram_gb": 2.0,
    "idle_ram_mb": 600,
    "boot_ssd_s": 15.0,
    "boot_hdd_s": 30.0,
    "install_gb": 8.0,
    "min_disk_gb": 16.0,
}

_UNITS = {"us": 1e-6, "ms": 1e-3, "s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0}
_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(us|ms|min|s|h|d)\b")


def parse_duration(text: str) -> Optional[float]:
    """'1min 2.5s' → 62.5 ; '567ms' → 0.567 ; '' → None."""
    parts = _PART.findall(text or "")
    if not parts:
        return None
    return round(sum(float(n) * _UNITS[u] for n, u in parts), 6)


def parse_analyze(output: str) -> Dict[str, float]:
    """Parse `systemd-analyze` (time) output.

    'Startup finished in 3.2s (firmware) + 1.1s (loader) + 2.0s (kernel) +
    9.5s (userspace) = 15.8s' and 'graphical.target reached after 8.9s in
    userspace' → {'firmware': 3.2, ..., 'total': 15.8, 'graphical': 8.9}
    """
    result: Dict[str, float] = {}
    text = " ".join((output or "").split())
    m = re.search(r"Startup finished in (.+?) = ((?:\d+(?:\.\d+)?(?:us|ms|min|s|h|d)\b\s*)+)", text)
    if m:
        for chunk in m.group(1).split("+"):
            seg = re.match(r"\s*(.+?)\s*\((\w+)\)\s*$", chunk)
            if seg:
                value = parse_duration(seg.group(1))
                if value is not None:
                    result[seg.group(2)] = value
        total = parse_duration(m.group(2))
        if total is not None:
            result["total"] = total
    g = re.search(r"graphical\.target reached after (.+?) in userspace", text)
    if g:
        value = parse_duration(g.group(1))
        if value is not None:
            result["graphical"] = value
    return result


def boot_to_login(analyze: Dict[str, float]) -> Optional[float]:
    """Seconds from power-on (or kernel start) to the login screen."""
    if "graphical" not in analyze:
        return analyze.get("total")
    before_userspace = sum(analyze.get(k, 0.0) for k in ("firmware", "loader", "kernel", "initrd"))
    return round(before_userspace + analyze["graphical"], 3)


def parse_meminfo(text: str) -> Dict[str, int]:
    """/proc/meminfo → MB totals."""
    values = {}
    for line in (text or "").splitlines():
        m = re.match(r"(\w+):\s+(\d+)\s*kB", line)
        if m:
            values[m.group(1)] = int(m.group(2)) // 1024
    total, available = values.get("MemTotal"), values.get("MemAvailable")
    out = {}
    if total is not None:
        out["total_mb"] = total
    if total is not None and available is not None:
        out["available_mb"] = available
        out["used_mb"] = total - available
    return out


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def root_device(mountinfo: str) -> Optional[str]:
    """Kernel name of the block device holding / ('sda2', 'nvme0n1p2', 'dm-0')."""
    for line in mountinfo.splitlines():
        fields = line.split()
        if len(fields) > 9 and fields[4] == "/":
            sep = fields.index("-") if "-" in fields else -1
            if sep > 0 and len(fields) > sep + 2:
                source = fields[sep + 2]
                if source.startswith("/dev/"):
                    return os.path.basename(os.path.realpath(source))
    return None


def is_rotational(dev: Optional[str], sys_block: str = "/sys/class/block",
                  read: Callable[[str], str] = _read, depth: int = 0) -> Optional[bool]:
    """True for a spinning disk, False for SSD/NVMe, None if unknown."""
    if not dev or depth > 4:
        return None
    base = os.path.join(sys_block, dev)
    if read(os.path.join(base, "partition")).strip():     # sda2 → sda
        parent = os.path.basename(os.path.dirname(os.path.realpath(base)))
        return is_rotational(parent, sys_block, read, depth + 1)
    slaves = os.path.join(base, "slaves")                  # dm-crypt / LVM
    if os.path.isdir(slaves):
        found = [is_rotational(s, sys_block, read, depth + 1) for s in sorted(os.listdir(slaves))]
        if any(f is True for f in found):
            return True
        if found and all(f is False for f in found):
            return False
    value = read(os.path.join(base, "queue", "rotational")).strip()
    return {"1": True, "0": False}.get(value)


def _cpu_model(cpuinfo: str) -> str:
    m = re.search(r"^model name\s*:\s*(.+)$", cpuinfo, re.MULTILINE)
    return m.group(1).strip() if m else platform.processor() or "unknown"


def collect(run: Optional[Callable[[List[str]], str]] = None,
            read: Callable[[str], str] = _read) -> Dict:
    """Measure this machine. Every field may be missing if it can't be read."""
    def default_run(argv: List[str]) -> str:
        if not shutil.which(argv[0]):
            return ""
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""
    run = run or default_run

    analyze = parse_analyze(run(["systemd-analyze"]))
    memory = parse_meminfo(read("/proc/meminfo"))
    cmdline = read("/proc/cmdline")
    live = "boot=casper" in cmdline
    dev = root_device(read("/proc/self/mountinfo"))
    disk = {"rotational": is_rotational(dev, read=read)}
    try:
        usage = shutil.disk_usage("/")
        disk.update(total_gb=round(usage.total / 1e9, 1), used_gb=round(usage.used / 1e9, 1))
    except OSError:
        pass
    os_name = next((line.split("=", 1)[1].strip().strip('"') for line in read("/etc/os-release").splitlines()
                    if line.startswith("PRETTY_NAME=")), "unknown")
    return {
        "report": "primers-benchmark/1",
        "measured": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "os": os_name,
        "kernel": platform.release(),
        "live_session": live,
        "uptime_s": int(float((read("/proc/uptime").split() or ["0"])[0])),
        "hardware": {
            "cpu": _cpu_model(read("/proc/cpuinfo")),
            "cores": os.cpu_count(),
            "model": read("/sys/class/dmi/id/product_name").strip() or None,
            "vendor": read("/sys/class/dmi/id/sys_vendor").strip() or None,
        },
        "boot": dict(analyze, to_login=boot_to_login(analyze)) if analyze else {},
        "memory": memory,
        "disk": disk,
    }


def evaluate(report: Dict) -> List[Tuple[str, str, str, str]]:
    """(check, measured, target, 'pass' | 'fail' | 'n/a') rows."""
    rows = []
    mem = report.get("memory", {})
    total = mem.get("total_mb")
    if total is not None:
        ok = total / 1024 >= TARGETS["min_ram_gb"] * 0.95      # firmware reserves a little
        rows.append(("RAM installed", f"{total / 1024:.1f} GB", f"≥ {TARGETS['min_ram_gb']:.0f} GB",
                     "pass" if ok else "fail"))
    used = mem.get("used_mb")
    if used is not None:
        rows.append(("RAM in use now", f"{used} MB", f"< {TARGETS['idle_ram_mb']} MB when idle",
                     "pass" if used < TARGETS["idle_ram_mb"] else "fail"))
    boot = report.get("boot", {}).get("to_login")
    rotational = report.get("disk", {}).get("rotational")
    if boot is not None:
        if report.get("live_session"):
            rows.append(("Boot to login", f"{boot:.1f} s", "installed systems only", "n/a"))
        else:
            limit = TARGETS["boot_hdd_s"] if rotational else TARGETS["boot_ssd_s"]
            kind = "hard disk" if rotational else ("SSD" if rotational is False else "SSD (disk type unknown)")
            rows.append(("Boot to login", f"{boot:.1f} s", f"< {limit:.0f} s on {kind}",
                         "pass" if boot < limit else "fail"))
    disk = report.get("disk", {})
    if "used_gb" in disk and not report.get("live_session"):
        rows.append(("Disk used", f"{disk['used_gb']:.1f} GB", f"< {TARGETS['install_gb']:.0f} GB base install + your files",
                     "pass" if disk["used_gb"] < TARGETS["install_gb"] else "n/a"))
    if "total_gb" in disk and not report.get("live_session"):
        rows.append(("Disk size", f"{disk['total_gb']:.0f} GB", f"≥ {TARGETS['min_disk_gb']:.0f} GB",
                     "pass" if disk["total_gb"] >= TARGETS["min_disk_gb"] * 0.95 else "fail"))
    return rows


def save(report: Dict, folder: str) -> str:
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "benchmark-" + time.strftime("%Y%m%d-%H%M%S") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(report, results=[dict(zip(("check", "measured", "target", "result"), r))
                                        for r in evaluate(report)]), f, indent=2)
    return path
