"""
PRIMERS OS — System Monitor
Tracks CPU, memory, disk and network in a background thread.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import psutil

from configs.settings import Settings
from utils.logger import PrimersLogger

MAX_ALERTS = 200
ALERT_REPEAT_SECONDS = 60  # same alert type is not repeated within this window


@dataclass
class SystemSnapshot:
    timestamp: float
    cpu_percent: float
    cpu_per_core: List[float]
    memory_total: int
    memory_used: int
    memory_percent: float
    swap_percent: float
    disk_usage: Dict[str, dict]
    net_bytes_sent: int
    net_bytes_recv: int
    process_count: int
    top_processes: List[dict] = field(default_factory=list)


class SystemMonitor:
    def __init__(self, settings: Optional[Settings] = None):
        self.logger = PrimersLogger.get_logger("system_monitor")
        self.settings = settings or Settings()
        self._running = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._latest: Optional[SystemSnapshot] = None
        self._alerts: List[dict] = []
        self._last_alert_at: Dict[str, float] = {}
        self._interval = self.settings.MONITOR_INTERVAL
        self._net_baseline = psutil.net_io_counters()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="SystemMonitor")
        self._thread.start()
        self.logger.info("System monitor started.")

    def stop(self):
        self._running = False
        self._stop.set()

    @property
    def running(self) -> bool:
        return self._running

    def refresh(self, interval: float = 1.0) -> SystemSnapshot:
        """Capture a snapshot synchronously (used by one-shot commands)."""
        snap = self._capture(cpu_interval=interval)
        with self._lock:
            self._latest = snap
        self._check_thresholds(snap)
        return snap

    def get_snapshot(self) -> Optional[SystemSnapshot]:
        with self._lock:
            return self._latest

    def get_alerts(self, clear: bool = False) -> List[dict]:
        with self._lock:
            alerts = list(self._alerts)
            if clear:
                self._alerts.clear()
        return alerts

    def get_metrics(self) -> dict:
        """Numeric metrics for programmatic consumers (dashboard, tests)."""
        snap = self.get_snapshot()
        if not snap:
            return {"ready": False}
        return {
            "ready": True,
            "timestamp": snap.timestamp,
            "cpu_percent": snap.cpu_percent,
            "cpu_per_core": snap.cpu_per_core,
            "memory_percent": snap.memory_percent,
            "memory_used": snap.memory_used,
            "memory_total": snap.memory_total,
            "swap_percent": snap.swap_percent,
            "process_count": snap.process_count,
            "net_bytes_sent": snap.net_bytes_sent,
            "net_bytes_recv": snap.net_bytes_recv,
            "disks": snap.disk_usage,
            "top_processes": snap.top_processes,
        }

    def get_summary(self) -> dict:
        snap = self.get_snapshot()
        if not snap:
            return {"status": "initialising"}
        return {
            "cpu": f"{snap.cpu_percent:.1f}%",
            "memory": f"{snap.memory_percent:.1f}% ({self._fmt_bytes(snap.memory_used)} / {self._fmt_bytes(snap.memory_total)})",
            "swap": f"{snap.swap_percent:.1f}%",
            "processes": snap.process_count,
            "net_sent": self._fmt_bytes(snap.net_bytes_sent),
            "net_recv": self._fmt_bytes(snap.net_bytes_recv),
            "disks": snap.disk_usage,
            "top_processes": snap.top_processes[:5],
        }

    # ------------------------------------------------------------------ #
    #  Internal
    # ------------------------------------------------------------------ #

    def _monitor_loop(self):
        while self._running:
            try:
                self.refresh(interval=1.0)
            except Exception as e:  # keep the monitor alive whatever happens
                self.logger.error(f"Monitor loop error: {e}")
            self._stop.wait(self._interval)

    def _capture(self, cpu_interval: float = 1.0) -> SystemSnapshot:
        net = psutil.net_io_counters()
        disks = {}
        for part in psutil.disk_partitions(all=False):
            if part.fstype in ("squashfs", "iso9660") or part.mountpoint.startswith("/snap/"):
                continue  # read-only images are always "100% full"
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            disks[part.mountpoint] = {
                "total": self._fmt_bytes(usage.total),
                "used": self._fmt_bytes(usage.used),
                "percent": usage.percent,
            }

        top = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                top.append(dict(proc.info))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        top = sorted(top, key=lambda p: p.get("cpu_percent") or 0, reverse=True)[:5]

        vm = psutil.virtual_memory()
        return SystemSnapshot(
            timestamp=time.time(),
            cpu_percent=psutil.cpu_percent(interval=cpu_interval),
            cpu_per_core=psutil.cpu_percent(percpu=True),
            memory_total=vm.total,
            memory_used=vm.used,
            memory_percent=vm.percent,
            swap_percent=psutil.swap_memory().percent,
            disk_usage=disks,
            net_bytes_sent=max(0, net.bytes_sent - self._net_baseline.bytes_sent),
            net_bytes_recv=max(0, net.bytes_recv - self._net_baseline.bytes_recv),
            process_count=len(psutil.pids()),
            top_processes=top,
        )

    def _check_thresholds(self, snap: SystemSnapshot):
        s = self.settings
        candidates = []
        if snap.cpu_percent > s.CPU_ALERT_THRESHOLD:
            candidates.append(("CPU", snap.cpu_percent, f"High CPU: {snap.cpu_percent:.1f}%"))
        if snap.memory_percent > s.MEMORY_ALERT_THRESHOLD:
            candidates.append(("MEMORY", snap.memory_percent, f"High memory: {snap.memory_percent:.1f}%"))
        for mount, info in snap.disk_usage.items():
            if info["percent"] > s.DISK_ALERT_THRESHOLD:
                candidates.append((f"DISK:{mount}", info["percent"], f"Disk {mount} at {info['percent']}%"))

        new_alerts = []
        with self._lock:
            for key, value, msg in candidates:
                last = self._last_alert_at.get(key, 0)
                if snap.timestamp - last < ALERT_REPEAT_SECONDS:
                    continue
                self._last_alert_at[key] = snap.timestamp
                alert = {"type": key.split(":")[0], "value": value, "msg": msg, "timestamp": snap.timestamp}
                self._alerts.append(alert)
                new_alerts.append(alert)
            if len(self._alerts) > MAX_ALERTS:
                del self._alerts[:-MAX_ALERTS]
        for a in new_alerts:
            self.logger.warning(a["msg"])

    @staticmethod
    def _fmt_bytes(b: float) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} PB"
