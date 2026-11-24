import socket
from types import SimpleNamespace

import pytest

from ai.cyber_intelligence.module import CyberIntelligence
from ai.decision_engine.engine import DecisionEngine
from core.process_manager.manager import ProcessManager, ProcessRecord
from services.graph_ai.engine import GraphAIEngine


class FakeMonitor:
    def __init__(self, cpu=10.0, mem=10.0, disks=None):
        self.snap = SimpleNamespace(cpu_percent=cpu, memory_percent=mem, disk_usage=disks or {})

    def get_snapshot(self):
        return self.snap


class FakeSecurity:
    def __init__(self, events=()):
        self.events = list(events)

    def get_events(self, min_level="LOW"):
        return self.events


class FakeProcs(ProcessManager):
    def __init__(self, procs):
        super().__init__()
        self.procs = procs

    def list_processes(self, sort_by="cpu", limit=20):
        return self.procs[:limit]


def test_decision_engine_all_clear():
    de = DecisionEngine(FakeMonitor(), FakeProcs([]), FakeSecurity())
    assert de.analyse() == []


def test_decision_engine_sorts_and_dedupes():
    hog = ProcessRecord(4242, "miner", "running", 99.0, 1.0, [])
    ev = SimpleNamespace(level="CRITICAL", pid=4242, name="miner", description="bad port")
    de = DecisionEngine(FakeMonitor(cpu=95, disks={"/": {"percent": 97}}),
                        FakeProcs([hog, hog]), FakeSecurity([ev, ev]))
    recs = de.analyse()
    assert recs[0].severity == "CRITICAL"
    keys = [(r.action, r.reason) for r in recs]
    assert len(keys) == len(set(keys))
    assert any(r.action == "kill 4242" for r in recs)


def test_decision_engine_never_targets_protected_pids():
    import os
    me = ProcessRecord(os.getpid(), "python", "running", 300.0, 1.0, [])
    de = DecisionEngine(FakeMonitor(), FakeProcs([me]), FakeSecurity())
    assert not any(str(os.getpid()) in r.action for r in de.analyse())


def test_cyber_scan_finds_local_listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    port = srv.getsockname()[1]
    try:
        ci = CyberIntelligence()
        found = ci.scan_ports(port_range=(port, port), timeout=0.2)
        assert [f["port"] for f in found] == [port]
        assert found[0]["exposure"] in ("local", "unknown")
        report = ci.get_report()
        assert report["open_ports"] == found
        assert 0 <= report["risk_score"] <= 100
    finally:
        srv.close()


def test_cyber_rejects_bad_range():
    with pytest.raises(ValueError):
        CyberIntelligence().scan_ports(port_range=(0, 70000))


def test_graph_engine_scan_and_anomalies():
    g = GraphAIEngine()
    graph = g.scan()
    assert g.hostname in graph["nodes"]
    assert isinstance(g.render_ascii(), str)
    assert g.get_stats()["node_count"] >= 1

    g._graph = {
        "nodes": {"h": {"id": "h", "type": "local_host", "connections": 30},
                  "1.2.3.4": {"id": "1.2.3.4", "type": "remote_host", "connections": 7}},
        "edges": [{"from": "h", "to": "1.2.3.4", "port": p, "status": "ESTABLISHED", "pid": 5000}
                  for p in (22, 80, 443, 8080, 8443, 9000, 9100)],
    }
    types = {a["type"] for a in g.detect_anomalies()}
    assert {"High Degree Anomaly", "Port Sweep Detection", "Privileged Port Usage"} <= types
