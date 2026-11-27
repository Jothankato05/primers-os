"""
PRIMERS OS - Automation Engine
Schedules shell commands at intervals or at a time of day.

Tasks run as the current user. The task file is private (0600) inside the
user's data directory so other users cannot read or inject commands.
"""

import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime
from typing import List, Optional

from utils import paths
from utils.logger import PrimersLogger

TASK_TIMEOUT_SECONDS = 30
MIN_INTERVAL_SECONDS = 10
MAX_OUTPUT_CHARS = 4000


class AutomationEngine:
    """Task scheduler and system automation engine."""

    def __init__(self, tasks_path: Optional[str] = None, history_path: Optional[str] = None,
                 tick_seconds: float = 10.0):
        self.logger = PrimersLogger.get_logger("automation_engine")
        self.tasks_path = tasks_path or paths.data_file("tasks.json")
        self.history_path = history_path or paths.data_file("task_history.jsonl")
        self.tasks: List[dict] = []
        self._lock = threading.RLock()
        self._running = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._in_flight = set()
        self._tick = tick_seconds
        self.load()

    # ------------------------------------------------------------------ #
    #  Task management
    # ------------------------------------------------------------------ #

    def add_task(self, name: str, command: str, schedule_type: str,
                 interval_seconds: Optional[int] = None, run_at_time: Optional[str] = None) -> dict:
        if not name or not name.strip():
            return {"ok": False, "error": "task name is required"}
        if not command or not command.strip():
            return {"ok": False, "error": "command is required"}
        if schedule_type not in ("interval", "time"):
            return {"ok": False, "error": "schedule_type must be 'interval' or 'time'"}

        if schedule_type == "interval":
            try:
                interval_seconds = int(interval_seconds)
            except (TypeError, ValueError):
                return {"ok": False, "error": "interval_seconds must be a whole number"}
            if interval_seconds < MIN_INTERVAL_SECONDS:
                return {"ok": False, "error": f"interval_seconds must be ≥ {MIN_INTERVAL_SECONDS}"}
            run_at_time = None
        else:
            if not run_at_time:
                return {"ok": False, "error": "run_at_time is required for 'time' schedule"}
            try:
                datetime.strptime(run_at_time, "%H:%M")
            except ValueError:
                return {"ok": False, "error": "run_at_time must match HH:MM format"}
            interval_seconds = None

        task = {
            "id": uuid.uuid4().hex[:8],
            "name": name.strip(),
            "command": command.strip(),
            "schedule_type": schedule_type,
            "interval_seconds": interval_seconds,
            "run_at_time": run_at_time,
            "enabled": True,
            "created": time.time(),
            "last_run": None,
            "run_count": 0,
        }
        with self._lock:
            self.tasks.append(task)
            self.save()
        return {"ok": True, "id": task["id"]}

    def _find(self, task_id: str) -> Optional[dict]:
        for t in self.tasks:
            if t["id"] == task_id:
                return t
        return None

    def remove_task(self, task_id: str) -> dict:
        with self._lock:
            before = len(self.tasks)
            self.tasks = [t for t in self.tasks if t["id"] != task_id]
            if len(self.tasks) < before:
                self.save()
                return {"ok": True}
        return {"ok": False, "error": "not found"}

    def list_tasks(self) -> List[dict]:
        with self._lock:
            return [dict(t) for t in self.tasks]

    def _set_enabled(self, task_id: str, enabled: bool) -> dict:
        with self._lock:
            t = self._find(task_id)
            if not t:
                return {"ok": False, "error": "not found"}
            t["enabled"] = enabled
            self.save()
        return {"ok": True}

    def enable_task(self, task_id: str) -> dict:
        return self._set_enabled(task_id, True)

    def disable_task(self, task_id: str) -> dict:
        return self._set_enabled(task_id, False)

    def run_now(self, task_id: str) -> dict:
        with self._lock:
            t = self._find(task_id)
        if not t:
            return {"ok": False, "error": "not found"}
        return self._execute_task(t)

    def get_history(self, task_id: Optional[str] = None, limit: int = 20) -> List[dict]:
        history = []
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if task_id is None or entry.get("task_id") == task_id:
                            history.append(entry)
            except OSError as e:
                self.logger.error(f"Failed to load task history: {e}")
        return history[-limit:]

    # ------------------------------------------------------------------ #
    #  Scheduler
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True, name="AutomationEngine")
        self._thread.start()
        self.logger.info("AutomationEngine background thread started.")

    def stop(self) -> None:
        self._running = False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self.logger.info("AutomationEngine background thread stopped.")

    @property
    def running(self) -> bool:
        return self._running

    def due_tasks(self, now: Optional[float] = None) -> List[dict]:
        """Tasks that should run at `now` (exposed for testing)."""
        now = time.time() if now is None else now
        now_dt = datetime.fromtimestamp(now)
        due = []
        with self._lock:
            for task in self.tasks:
                if not task.get("enabled", True) or task["id"] in self._in_flight:
                    continue
                last_run = task.get("last_run")
                if task["schedule_type"] == "interval":
                    if now - (last_run or 0) >= task["interval_seconds"]:
                        due.append(task)
                elif task["schedule_type"] == "time":
                    if task["run_at_time"] != now_dt.strftime("%H:%M"):
                        continue
                    if last_run and datetime.fromtimestamp(last_run).date() == now_dt.date() \
                            and now - last_run < 120:
                        continue  # already ran in this minute window today
                    due.append(task)
        return due

    def _scheduler_loop(self):
        while self._running:
            try:
                for task in self.due_tasks():
                    threading.Thread(target=self._execute_task, args=(task,), daemon=True).start()
            except Exception as e:
                self.logger.error(f"Scheduler error: {e}")
            self._stop.wait(self._tick)

    def _execute_task(self, task: dict) -> dict:
        with self._lock:
            if task["id"] in self._in_flight:
                return {"ok": False, "error": "task is already running"}
            self._in_flight.add(task["id"])
            task["last_run"] = time.time()
            task["run_count"] = task.get("run_count", 0) + 1
            self.save()
        self.logger.info(f"Executing task: {task['name']} (ID: {task['id']})")
        try:
            result = subprocess.run(task["command"], shell=True, capture_output=True,
                                    text=True, timeout=TASK_TIMEOUT_SECONDS)
            output = (result.stdout + result.stderr).strip()[:MAX_OUTPUT_CHARS]
            self._log_history({
                "task_id": task["id"],
                "timestamp": time.time(),
                "command": task["command"],
                "returncode": result.returncode,
                "output": output,
            })
            return {"ok": True, "output": output, "returncode": result.returncode}
        except subprocess.TimeoutExpired:
            self.logger.error(f"Task {task['id']} timed out after {TASK_TIMEOUT_SECONDS}s")
            self._log_history({"task_id": task["id"], "timestamp": time.time(),
                               "command": task["command"], "returncode": -1,
                               "output": f"timed out after {TASK_TIMEOUT_SECONDS}s"})
            return {"ok": False, "error": "Timeout expired"}
        except Exception as e:
            self.logger.error(f"Task execution failed ({task['id']}): {e}")
            return {"ok": False, "error": str(e)}
        finally:
            with self._lock:
                self._in_flight.discard(task["id"])

    # ------------------------------------------------------------------ #
    #  Persistence
    # ------------------------------------------------------------------ #

    def _log_history(self, entry: dict):
        try:
            paths.append_private(self.history_path, json.dumps(entry) + "\n")
        except OSError as e:
            self.logger.error(f"Failed to log task history: {e}")

    def save(self) -> None:
        with self._lock:
            try:
                paths.write_private(self.tasks_path, json.dumps(self.tasks, indent=4))
            except OSError as e:
                self.logger.error(f"Failed to save tasks: {e}")

    def load(self) -> None:
        if not os.path.exists(self.tasks_path):
            return
        try:
            with open(self.tasks_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.tasks = [t for t in data if isinstance(t, dict) and "id" in t and "command" in t]
        except (OSError, json.JSONDecodeError) as e:
            self.logger.error(f"Failed to load tasks: {e}")
            self.tasks = []
