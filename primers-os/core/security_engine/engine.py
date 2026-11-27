"""
PRIMERS OS - Security Engine
Defensive monitoring: threat detection, anomaly analysis, connection auditing.
This module is STRICTLY defensive. No offensive capabilities.
"""

import threading
import time
import psutil
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from configs.settings import Settings
from utils.logger import PrimersLogger


THREAT_LEVELS = {
    "INFO": 0,
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


@dataclass
class ThreatEvent:
    timestamp: float
    level: str               # INFO / LOW / MEDIUM / HIGH / CRITICAL
    category: str            # PROCESS / NETWORK / RESOURCE / BEHAVIOUR
    pid: Optional[int]
    name: Optional[str]
    description: str
    recommendation: str


class SecurityEngine:
    """
    Runs in background. Analyses running processes and connections.
    Raises ThreatEvents when anomalies are detected.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.logger = PrimersLogger.get_logger("security_engine")
        self.settings = settings or Settings()
        self._running = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._events: List[ThreatEvent] = []
        self._process_history: Dict[int, dict] = {}
        self._baseline_done = False
        self._scan_interval = self.settings.SECURITY_SCAN_INTERVAL
        self._max_events = self.settings.MAX_THREAT_LOGS

        # Thresholds
        self._cpu_spike_threshold = 90.0    # single process %
        self._conn_count_threshold = 50     # open connections per process
        self._known_suspicious_ports = {4444, 1337, 31337, 6666, 9999}

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._scan_loop,
            daemon=True,
            name="SecurityEngine"
        )
        self._thread.start()
        self.logger.info("Security engine started.")

    def stop(self):
        self._running = False
        self._stop.set()

    @property
    def running(self) -> bool:
        return self._running

    def scan_once(self):
        """Run one full process + network scan synchronously."""
        self._scan_processes()
        self._scan_network()

    def unseen_count(self, since: float, min_level: str = "HIGH") -> int:
        """Number of events at or above min_level raised after `since`."""
        min_val = THREAT_LEVELS.get(min_level, 3)
        with self._lock:
            return sum(1 for e in self._events
                       if e.timestamp > since and THREAT_LEVELS.get(e.level, 0) >= min_val)

    def get_events(self, min_level: str = "LOW", clear: bool = False) -> List[ThreatEvent]:
        min_val = THREAT_LEVELS.get(str(min_level).upper(), 1)
        with self._lock:
            filtered = [e for e in self._events if THREAT_LEVELS.get(e.level, 0) >= min_val]
            if clear:
                self._events = [e for e in self._events if THREAT_LEVELS.get(e.level, 0) < min_val]
        return filtered

    def get_status(self) -> dict:
        with self._lock:
            counts = {level: 0 for level in THREAT_LEVELS}
            for e in self._events:
                counts[e.level] = counts.get(e.level, 0) + 1
        return {
            "active": self._running,
            "total_events": sum(counts.values()),
            "by_level": counts,
        }

    def scan_connections(self) -> List[dict]:
        """Return all active network connections with process info."""
        results = []
        try:
            conns = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, OSError) as e:
            self.logger.warning(f"Cannot list connections: {e}")
            return results
        for conn in conns:
            entry = {
                "pid": conn.pid,
                "status": conn.status,
                "local": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "-",
                "remote": f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "-",
                "name": None,
            }
            if conn.pid:
                try:
                    entry["name"] = psutil.Process(conn.pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            results.append(entry)
        return results

    # ------------------------------------------------------------------ #
    #  Internal scanning
    # ------------------------------------------------------------------ #

    def _scan_loop(self):
        while self._running:
            try:
                self.scan_once()
            except Exception as e:
                self.logger.error(f"Security scan error: {e}")
            self._stop.wait(self._scan_interval)

    def _scan_processes(self):
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "status"]):
            try:
                info = proc.info
                pid = info["pid"]
                cpu = info["cpu_percent"] or 0.0
                name = info["name"] or "unknown"

                # Detect CPU spike
                if cpu > self._cpu_spike_threshold:
                    self._raise_event(ThreatEvent(
                        timestamp=time.time(),
                        level="HIGH",
                        category="PROCESS",
                        pid=pid,
                        name=name,
                        description=f"Process '{name}' (PID {pid}) consuming {cpu:.1f}% CPU",
                        recommendation="Investigate or terminate if unexpected."
                    ))

                # Track new processes. The first scan only records a baseline:
                # everything already running at boot is not "new".
                if pid not in self._process_history:
                    self._process_history[pid] = {"name": name}
                    if not self._baseline_done:
                        continue
                    self._raise_event(ThreatEvent(
                        timestamp=time.time(),
                        level="INFO",
                        category="PROCESS",
                        pid=pid,
                        name=name,
                        description=f"New process detected: '{name}' (PID {pid})",
                        recommendation="No action required unless unexpected."
                    ))

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Clean up exited processes from history
        current_pids = set(psutil.pids())
        self._process_history = {pid: info for pid, info in self._process_history.items()
                                  if pid in current_pids}
        self._baseline_done = True

    def _scan_network(self):
        try:
            conn_by_pid: Dict[int, int] = {}
            for conn in psutil.net_connections(kind="inet"):
                if conn.pid:
                    conn_by_pid[conn.pid] = conn_by_pid.get(conn.pid, 0) + 1

                # Check for known suspicious ports
                if conn.raddr and conn.raddr.port in self._known_suspicious_ports:
                    name = None
                    try:
                        name = psutil.Process(conn.pid).name() if conn.pid else None
                    except Exception:
                        pass
                    self._raise_event(ThreatEvent(
                        timestamp=time.time(),
                        level="CRITICAL",
                        category="NETWORK",
                        pid=conn.pid,
                        name=name,
                        description=f"Connection to suspicious port {conn.raddr.port} from PID {conn.pid} ({name})",
                        recommendation="Terminate process immediately and investigate."
                    ))

            # Check for processes with too many connections
            for pid, count in conn_by_pid.items():
                if count > self._conn_count_threshold:
                    try:
                        name = psutil.Process(pid).name()
                    except Exception:
                        name = "unknown"
                    self._raise_event(ThreatEvent(
                        timestamp=time.time(),
                        level="MEDIUM",
                        category="NETWORK",
                        pid=pid,
                        name=name,
                        description=f"Process '{name}' (PID {pid}) has {count} open connections",
                        recommendation="Review if this is expected behaviour."
                    ))
        except (psutil.AccessDenied, OSError):
            pass

    def _raise_event(self, event: ThreatEvent):
        # Deduplicate: don't spam the same event within 60 seconds
        with self._lock:
            for existing in self._events[-20:]:
                if (existing.pid == event.pid and
                        existing.description == event.description and
                        (event.timestamp - existing.timestamp) < 60):
                    return
            self._events.append(event)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]

        if event.level in ("HIGH", "CRITICAL"):
            self.logger.warning(f"[{event.level}] {event.description}")
