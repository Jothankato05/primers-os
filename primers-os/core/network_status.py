"""
PRIMERS OS - network status from NetworkManager (over D-Bus via busctl).

Used by the Data Saver: background downloads (package lists, upgrades,
firmware metadata) are postponed while the connection is metered. Parsing
is kept pure so it can be tested without NetworkManager.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

OVERRIDE_FILE = "/etc/primers/updates-on-metered"
GATE_SCRIPT = "/usr/lib/primers/unmetered-network"

_NM = ("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
       "org.freedesktop.NetworkManager")

METERED = {0: "unknown", 1: "yes", 2: "no", 3: "yes (guessed)", 4: "no (guessed)"}
CONNECTIVITY = {0: "unknown", 1: "none", 2: "captive portal", 3: "limited", 4: "full"}
CONNECTION_TYPES = {
    "802-3-ethernet": "Ethernet", "802-11-wireless": "Wi-Fi", "gsm": "Mobile data",
    "cdma": "Mobile data", "bluetooth": "Bluetooth tethering", "vpn": "VPN",
    "wireguard": "VPN", "": "None",
}


@dataclass
class NetworkStatus:
    metered_code: Optional[int]
    connectivity_code: Optional[int]
    connection_type: Optional[str]
    override: bool = False

    @property
    def available(self) -> bool:
        return self.metered_code is not None

    @property
    def metered(self) -> bool:
        return self.metered_code in (1, 3)

    @property
    def background_downloads_paused(self) -> bool:
        return self.metered and not self.override

    @property
    def metered_text(self) -> str:
        return METERED.get(self.metered_code, "unknown")

    @property
    def connectivity_text(self) -> str:
        return CONNECTIVITY.get(self.connectivity_code, "unknown")

    @property
    def connection_text(self) -> str:
        if self.connection_type is None:
            return "unknown"
        return CONNECTION_TYPES.get(self.connection_type, self.connection_type)


def parse_busctl_value(output: str):
    """'u 4' → 4 ; 's "802-3-ethernet"' → '802-3-ethernet' ; anything else → None."""
    parts = (output or "").strip().split(None, 1)
    if len(parts) != 2:
        return None
    kind, value = parts
    if kind == "u":
        try:
            return int(value)
        except ValueError:
            return None
    if kind == "s":
        return value.strip().strip('"')
    return None


def _get(prop: str):
    if not shutil.which("busctl"):
        return None
    try:
        out = subprocess.run(["busctl", "get-property", *_NM, prop],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_busctl_value(out)


def read_status() -> NetworkStatus:
    return NetworkStatus(
        metered_code=_get("Metered"),
        connectivity_code=_get("Connectivity"),
        connection_type=_get("PrimaryConnectionType"),
        override=os.path.exists(OVERRIDE_FILE),
    )
