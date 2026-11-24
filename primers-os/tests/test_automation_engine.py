import os
import stat
import time
from datetime import datetime

from ai.automation_engine.engine import AutomationEngine


def make(tmp_path):
    return AutomationEngine(str(tmp_path / "tasks.json"), str(tmp_path / "hist.jsonl"))


def test_validation(tmp_path):
    ae = make(tmp_path)
    assert not ae.add_task("", "echo", "interval", 60)["ok"]
    assert not ae.add_task("n", "", "interval", 60)["ok"]
    assert not ae.add_task("n", "echo", "cron", 60)["ok"]
    assert not ae.add_task("n", "echo", "interval", "abc")["ok"]
    assert not ae.add_task("n", "echo", "interval", 1)["ok"]
    assert not ae.add_task("n", "echo", "time", run_at_time="25:99")["ok"]
    assert ae.add_task("n", "echo hi", "interval", "60")["ok"]
    assert ae.add_task("n", "echo hi", "time", run_at_time="07:30")["ok"]


def test_persistence_and_permissions(tmp_path):
    ae = make(tmp_path)
    tid = ae.add_task("backup", "echo hi", "interval", 60)["id"]
    assert stat.S_IMODE(os.stat(tmp_path / "tasks.json").st_mode) == 0o600
    again = make(tmp_path)
    assert [t["id"] for t in again.list_tasks()] == [tid]
    assert again.disable_task(tid)["ok"]
    assert make(tmp_path).list_tasks()[0]["enabled"] is False
    assert again.remove_task(tid)["ok"]
    assert not again.remove_task(tid)["ok"]


def test_run_now_records_output(tmp_path):
    ae = make(tmp_path)
    tid = ae.add_task("say", "echo primers-test", "interval", 60)["id"]
    res = ae.run_now(tid)
    assert res == {"ok": True, "output": "primers-test", "returncode": 0}
    hist = ae.get_history(tid)
    assert hist[-1]["returncode"] == 0
    assert ae.list_tasks()[0]["run_count"] == 1


def test_due_interval_tasks(tmp_path):
    ae = make(tmp_path)
    tid = ae.add_task("t", "true", "interval", 60)["id"]
    now = time.time()
    assert [t["id"] for t in ae.due_tasks(now)] == [tid]          # never ran
    ae.tasks[0]["last_run"] = now - 30
    assert ae.due_tasks(now) == []                                # too soon
    ae.tasks[0]["last_run"] = now - 61
    assert len(ae.due_tasks(now)) == 1
    ae.disable_task(tid)
    assert ae.due_tasks(now) == []


def test_due_time_tasks_run_once_per_day(tmp_path):
    ae = make(tmp_path)
    ae.add_task("t", "true", "time", run_at_time="09:15")
    at = datetime(2026, 1, 5, 9, 15, 20).timestamp()
    assert len(ae.due_tasks(at)) == 1
    ae.tasks[0]["last_run"] = at
    assert ae.due_tasks(at + 20) == []                            # same minute
    assert ae.due_tasks(datetime(2026, 1, 5, 9, 16).timestamp()) == []
    assert len(ae.due_tasks(datetime(2026, 1, 6, 9, 15, 5).timestamp())) == 1


def test_corrupt_task_file(tmp_path):
    (tmp_path / "tasks.json").write_text("{not json")
    assert make(tmp_path).list_tasks() == []
