import os
import socket
import subprocess
import sys
import time

import psutil
import pytest

from configs.settings import Settings
from core.kernel_interface.interface import KernelInterface
from core.process_manager.manager import ProcessManager, ProtectedProcessError
from core.security_engine.engine import SecurityEngine, ThreatEvent
from core.system_monitor.monitor import MAX_ALERTS, SystemMonitor


def test_monitor_refresh_and_metrics():
    sm = SystemMonitor()
    assert sm.get_metrics() == {"ready": False}
    assert sm.get_summary() == {"status": "initialising"}
    snap = sm.refresh(interval=0.05)
    assert 0 <= snap.cpu_percent
    m = sm.get_metrics()
    assert m["ready"] and isinstance(m["cpu_percent"], float)
    assert sm.get_summary()["cpu"].endswith("%")


def test_monitor_alerts_fire_once_per_window(monkeypatch):
    monkeypatch.setenv("PRIMERS_MEMORY_ALERT_THRESHOLD", "-1")
    sm = SystemMonitor(Settings())
    sm.refresh(interval=0.01)
    sm.refresh(interval=0.01)
    alerts = [a for a in sm.get_alerts() if a["type"] == "MEMORY"]
    assert len(alerts) == 1            # deduplicated within the window
    assert len(sm.get_alerts(clear=True)) >= 1
    assert sm.get_alerts() == []


def test_monitor_alert_list_is_bounded(monkeypatch):
    monkeypatch.setenv("PRIMERS_MEMORY_ALERT_THRESHOLD", "-1")
    sm = SystemMonitor(Settings())
    snap = sm.refresh(interval=0.01)
    for i in range(MAX_ALERTS + 50):
        snap.timestamp += 3600
        sm._check_thresholds(snap)
    assert len(sm.get_alerts()) == MAX_ALERTS


def test_monitor_thread_start_stop():
    sm = SystemMonitor()
    sm.start()
    assert sm.running
    sm.stop()
    assert not sm.running


def test_process_manager_launch_and_terminate():
    pm = ProcessManager()
    pid = pm.launch('sleep 30')
    assert pid and psutil.pid_exists(pid)
    assert pm.get_process(pid).name.startswith("sleep")
    assert pm.find_by_name("sleep")
    assert pm.suspend(pid) and pm.resume(pid)
    assert pm.terminate(pid)
    psutil.Process(pid).wait(timeout=5) if psutil.pid_exists(pid) else None
    assert pm.launch("definitely-not-a-real-binary-xyz") is None
    assert pm.launch('echo "unterminated') is None


def test_process_manager_protects_init_and_self():
    pm = ProcessManager()
    for pid in (1, os.getpid()):
        assert pm.is_protected(pid)
        with pytest.raises(ProtectedProcessError):
            pm.terminate(pid)
        with pytest.raises(ProtectedProcessError):
            pm.suspend(pid)


def test_process_manager_sorting():
    pm = ProcessManager()
    by_name = pm.list_processes(sort_by="name", limit=50)
    names = [p.name.lower() for p in by_name]
    assert names == sorted(names)
    assert len(pm.list_processes(limit=3)) <= 3


def test_security_baseline_does_not_flood():
    se = SecurityEngine()
    se.scan_once()
    assert [e for e in se.get_events(min_level="INFO") if "New process" in e.description] == []
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
    try:
        se.scan_once()
        new = [e for e in se.get_events(min_level="INFO") if e.pid == proc.pid]
        assert new and new[0].level == "INFO"
    finally:
        proc.kill()


def test_security_event_filters_and_dedupe():
    se = SecurityEngine()
    now = time.time()
    ev = ThreatEvent(now, "HIGH", "PROCESS", 99, "x", "spike", "look")
    se._raise_event(ev)
    se._raise_event(ThreatEvent(now + 1, "HIGH", "PROCESS", 99, "x", "spike", "look"))
    assert len(se.get_events(min_level="HIGH")) == 1
    assert se.get_events(min_level="critical") == []
    assert se.unseen_count(now - 1) == 1
    assert se.unseen_count(now + 5) == 0
    status = se.get_status()
    assert status["by_level"]["HIGH"] == 1 and status["total_events"] == 1


def test_scan_connections_shape():
    se = SecurityEngine()
    for c in se.scan_connections():
        assert set(c) == {"pid", "status", "local", "remote", "name"}


def test_kernel_interface():
    k = KernelInterface()
    info = k.get_all()
    assert set(info) == {"cpu", "memory", "load", "uptime", "kernel", "network"}
    assert info["memory"]["MemTotal"] > 0
    assert info["uptime"]["uptime_seconds"] > 0


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("PRIMERS_GUI_PORT", "8123")
    monkeypatch.setenv("PRIMERS_CPU_ALERT_THRESHOLD", "not-a-number")
    s = Settings()
    assert s.GUI_PORT == 8123
    assert s.CPU_ALERT_THRESHOLD == 90.0
    assert s.GUI_HOST == "127.0.0.1"
    assert s.gui_url == "http://localhost:8123"
