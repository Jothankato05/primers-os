"""
PRIMERS OS — System Monitor
Tracks CPU, memory, disk and network in a background thread.
"""

import threading
import time
import psutil
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from utils.logger import PrimersLogger


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
    def __init__(self):
        self.logger = PrimersLogger.get_logger("system_monitor")
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._latest: Optional[SystemSnapshot] = None
        self._alerts: List[dict] = []
        self._interval = 5  # seconds

        # Baseline network counters
        self._net_baseline = psutil.net_io_counters()

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="SystemMonitor"
        )
        self._thread.start()
        self.logger.info("System monitor started.")

    def stop(self):
        self._running = False

    def get_snapshot(self) -> Optional[SystemSnapshot]:
        with self._lock:
            return self._latest

    def get_alerts(self, clear: bool = False) -> List[dict]:
        with self._lock:
            alerts = list(self._alerts)
            if clear:
                self._alerts.clear()
        return alerts

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
                snap = self._capture()
                with self._lock:
                    self._latest = snap
                self._check_thresholds(snap)
            except Exception as e:
                self.logger.error(f"Monitor loop error: {e}")
            time.sleep(self._interval)

    def _capture(self) -> SystemSnapshot:
        net = psutil.net_io_counters()
        disks = {}
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks[part.mountpoint] = {
                    "total": self._fmt_bytes(usage.total),
                    "used": self._fmt_bytes(usage.used),
                    "percent": usage.percent,
                }
            except PermissionError:
                pass

        # Top 5 processes by CPU
        top = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
            try:
                top.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        top = sorted(top, key=lambda p: p.get("cpu_percent") or 0, reverse=True)[:5]

        return SystemSnapshot(
            timestamp=time.time(),
            cpu_percent=psutil.cpu_percent(interval=1),
            cpu_per_core=psutil.cpu_percent(percpu=True),
            memory_total=psutil.virtual_memory().total,
            memory_used=psutil.virtual_memory().used,
            memory_percent=psutil.virtual_memory().percent,
            swap_percent=psutil.swap_memory().percent,
            disk_usage=disks,
            net_bytes_sent=net.bytes_sent - self._net_baseline.bytes_sent,
            net_bytes_recv=net.bytes_recv - self._net_baseline.bytes_recv,
            process_count=len(psutil.pids()),
            top_processes=top,
        )

    def _check_thresholds(self, snap: SystemSnapshot):
        from configs.settings import Settings
        s = Settings()
        alerts = []
        if snap.cpu_percent > s.CPU_ALERT_THRESHOLD:
            alerts.append({"type": "CPU", "value": snap.cpu_percent, "msg": f"High CPU: {snap.cpu_percent:.1f}%"})
        if snap.memory_percent > s.MEMORY_ALERT_THRESHOLD:
            alerts.append({"type": "MEMORY", "value": snap.memory_percent, "msg": f"High memory: {snap.memory_percent:.1f}%"})
        for mount, info in snap.disk_usage.items():
            if info["percent"] > s.DISK_ALERT_THRESHOLD:
                alerts.append({"type": "DISK", "value": info["percent"], "msg": f"Disk {mount} at {info['percent']}%"})
        if alerts:
            with self._lock:
                self._alerts.extend(alerts)
            for a in alerts:
                self.logger.warning(a["msg"])

    @staticmethod
    def _fmt_bytes(b: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} PB"
