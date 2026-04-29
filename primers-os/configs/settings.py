import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings:
    def __init__(self):
        self.version = "1.0.0-genesis"
        self.cpu_threshold = 90.0
        self.mem_threshold = 85.0
        self.disk_threshold = 90.0
        self.scan_interval = 5.0
        self.max_threat_logs = 1000
        self.security_scan_interval = 10.0
        self.gui_port = 5000
        self.voice_enabled = True
        self.automation_interval = 60.0

        self.VERSION = "1.0.0-genesis"
        self.OS_EDITION = "Genesis"
        self.LOG_DIR = os.environ.get(
            "PRIMERS_LOG_DIR",
            os.path.join(BASE_DIR, "logs")
        )

        # Distro paths (used when running inside the real OS)
        self.SYSTEM_LOG_DIR = "/var/log/primers"
        self.SYSTEM_LIB_DIR = "/var/lib/primers"
        self.MODULES_REGISTRY = "/usr/lib/primers/modules/module_registry.json"

        # Module installer
        self.PRIMERS_INSTALL_CMD = "primers-install"
        self.PRIMERS_COMPAT_CMD = "primers-compat"
