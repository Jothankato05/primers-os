"""
Connection detection through NetworkManager (nmcli) and ModemManager (mmcli).

Everything that parses command output is a pure function so it can be
tested without a modem.
"""

import shutil
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class ConnectionInfo:
    kind: str                       # wifi | ethernet | mobile | none | unknown
    generation: Optional[str] = None  # 2g | 3g | 4g | 5g (mobile only)
    metered: bool = False
    name: str = ""

    def describe(self) -> str:
        if self.kind == "mobile":
            gen = (self.generation or "mobile").upper()
            return f"{gen} mobile data"
        if self.kind == "wifi":
            return "Wi-Fi (metered)" if self.metered else "Wi-Fi"
        if self.kind == "ethernet":
            return "Ethernet"
        if self.kind == "none":
            return "Offline"
        return "Unknown network"


# ModemManager access technologies → generation
_ACCESS_TECH = {
    "gsm": "2g", "gsm-compact": "2g", "gprs": "2g", "edge": "2g",
    "umts": "3g", "hsdpa": "3g", "hsupa": "3g", "hspa": "3g", "hspa-plus": "3g",
    "1xrtt": "2g", "evdo0": "3g", "evdoa": "3g", "evdob": "3g",
    "lte": "4g", "lte-cat-m": "4g", "lte-nb-iot": "2g",
    "5gnr": "5g",
}
_GEN_RANK = {"2g": 0, "3g": 1, "4g": 2, "5g": 3}


def generation_from_access_tech(value: str) -> Optional[str]:
    """'gsm, edge' → '2g'; 'lte' → '4g'. The fastest listed technology wins."""
    best = None
    for tech in value.replace("|", ",").split(","):
        gen = _ACCESS_TECH.get(tech.strip().lower())
        if gen and (best is None or _GEN_RANK[gen] > _GEN_RANK[best]):
            best = gen
    return best


def parse_nmcli_devices(output: str) -> List[Dict[str, str]]:
    """Parse `nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device` (':'-separated, '\\:' escaped)."""
    devices = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts, cur, esc = [], "", False
        for ch in line:
            if esc:
                cur += ch
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == ":":
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        if len(parts) >= 3:
            devices.append({"device": parts[0], "type": parts[1], "state": parts[2],
                            "connection": parts[3] if len(parts) > 3 else ""})
    return devices


def parse_metered(output: str) -> bool:
    """`nmcli -g GENERAL.METERED device show X` → 'yes', 'yes (guessed)', 'no', 'unknown'."""
    return output.strip().lower().startswith("yes")


def parse_mmcli_keyvalue(output: str) -> Dict[str, str]:
    values = {}
    for line in output.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            values[key.strip()] = value.strip()
    return values


def pick_connection(devices: List[Dict[str, str]], metered: Dict[str, bool],
                    mobile_generation: Optional[str]) -> ConnectionInfo:
    """Choose the active connection the way NetworkManager routes: wired > wifi > mobile."""
    active = [d for d in devices if d["state"].startswith("connected") and d["type"] != "loopback"]
    if not active:
        return ConnectionInfo("none")
    order = {"ethernet": 0, "wifi": 1, "gsm": 2, "cdma": 2, "modem": 2, "bt": 3}
    active.sort(key=lambda d: order.get(d["type"], 5))
    d = active[0]
    kind = {"ethernet": "ethernet", "wifi": "wifi", "gsm": "mobile", "cdma": "mobile",
            "modem": "mobile", "bt": "mobile"}.get(d["type"], "unknown")
    return ConnectionInfo(kind=kind,
                          generation=mobile_generation if kind == "mobile" else None,
                          metered=metered.get(d["device"], kind == "mobile"),
                          name=d.get("connection", ""))


def _run(cmd: List[str], timeout: float = 3.0) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def detect() -> ConnectionInfo:
    """Best-effort detection; never raises."""
    if not shutil.which("nmcli"):
        return ConnectionInfo("unknown")
    devices = parse_nmcli_devices(_run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]))
    metered = {}
    for d in devices:
        if d["state"].startswith("connected") and d["type"] != "loopback":
            metered[d["device"]] = parse_metered(_run(["nmcli", "-g", "GENERAL.METERED", "device", "show", d["device"]]))
    generation = None
    if any(d["type"] in ("gsm", "cdma", "modem") for d in devices) and shutil.which("mmcli"):
        kv = parse_mmcli_keyvalue(_run(["mmcli", "-m", "any", "--output-keyvalue"]))
        generation = generation_from_access_tech(kv.get("modem.generic.access-technologies.value[1]", "")
                                                 or kv.get("modem.generic.access-technologies", ""))
    return pick_connection(devices, metered, generation)
