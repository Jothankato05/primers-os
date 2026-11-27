"""
PRIMERS OS - tunable configuration.

Values can be overridden with environment variables of the same name
prefixed with ``PRIMERS_`` (e.g. ``PRIMERS_GUI_PORT=8080``).
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VERSION = "1.0.0-genesis"
OS_EDITION = "Genesis"


def _env(name: str, default, cast):
    raw = os.environ.get(f"PRIMERS_{name}")
    if raw is None:
        return default
    try:
        if cast is bool:
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return cast(raw)
    except ValueError:
        return default


class Settings:
    def __init__(self):
        self.VERSION = VERSION
        self.OS_EDITION = OS_EDITION
        self.version = VERSION  # legacy alias

        # Resource alert thresholds (percent)
        self.CPU_ALERT_THRESHOLD = _env("CPU_ALERT_THRESHOLD", 90.0, float)
        self.MEMORY_ALERT_THRESHOLD = _env("MEMORY_ALERT_THRESHOLD", 85.0, float)
        self.DISK_ALERT_THRESHOLD = _env("DISK_ALERT_THRESHOLD", 90.0, float)

        # Background loops (seconds)
        self.MONITOR_INTERVAL = _env("MONITOR_INTERVAL", 5.0, float)
        self.SECURITY_SCAN_INTERVAL = _env("SECURITY_SCAN_INTERVAL", 10.0, float)
        self.AUTOMATION_INTERVAL = _env("AUTOMATION_INTERVAL", 10.0, float)
        self.MAX_THREAT_LOGS = _env("MAX_THREAT_LOGS", 1000, int)

        # Web dashboard - localhost only unless explicitly overridden
        self.GUI_HOST = _env("GUI_HOST", "127.0.0.1", str)
        self.GUI_PORT = _env("GUI_PORT", 5000, int)

        self.VOICE_ENABLED = _env("VOICE_ENABLED", True, bool)

        # Distro integration (used when running inside PRIMERS OS)
        self.MODULES_REGISTRY = "/usr/lib/primers/modules/module_registry.json"
        self.PRIMERS_INSTALL_CMD = "primers-install"
        self.PRIMERS_COMPAT_CMD = "primers-compat"

        # Legacy lowercase names kept for older plugins
        self.cpu_threshold = self.CPU_ALERT_THRESHOLD
        self.mem_threshold = self.MEMORY_ALERT_THRESHOLD
        self.disk_threshold = self.DISK_ALERT_THRESHOLD
        self.scan_interval = self.MONITOR_INTERVAL
        self.security_scan_interval = self.SECURITY_SCAN_INTERVAL
        self.max_threat_logs = self.MAX_THREAT_LOGS
        self.gui_port = self.GUI_PORT
        self.voice_enabled = self.VOICE_ENABLED
        self.automation_interval = self.AUTOMATION_INTERVAL

    @property
    def gui_url(self) -> str:
        host = "localhost" if self.GUI_HOST in ("127.0.0.1", "0.0.0.0", "::1") else self.GUI_HOST
        return f"http://{host}:{self.GUI_PORT}"
