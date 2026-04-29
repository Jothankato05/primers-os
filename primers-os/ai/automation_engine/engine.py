import json
import os
import time
import threading
import subprocess
import uuid
from datetime import datetime
from typing import List, Dict, Optional
from utils.logger import PrimersLogger

class AutomationEngine:
    """
    Task scheduler and system automation engine.
    Schedules shell commands at intervals or specific times.
    """

    def __init__(self):
        self.logger = PrimersLogger.get_logger("automation_engine")
        self.tasks_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs", "tasks.json")
        self.history_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs", "task_history.jsonl")
        self.tasks: List[dict] = []
        self._running = False
        self._thread = None
        self.load()

    def add_task(self, name: str, command: str, schedule_type: str, interval_seconds: Optional[int] = None, run_at_time: Optional[str] = None) -> dict:
        """
        Validates and adds a new task.
        """
        if schedule_type not in ["interval", "time"]:
            return {"ok": False, "error": "schedule_type must be 'interval' or 'time'"}
        
        if schedule_type == "interval":
            if interval_seconds is None or interval_seconds <= 0:
                return {"ok": False, "error": "interval_seconds must be > 0"}
        
        if schedule_type == "time":
            if not run_at_time:
                return {"ok": False, "error": "run_at_time is required for 'time' schedule"}
            try:
                datetime.strptime(run_at_time, "%H:%M")
            except ValueError:
                return {"ok": False, "error": "run_at_time must match HH:MM format"}

        task_id = str(uuid.uuid4())[:8]
        task = {
            "id": task_id,
            "name": name,
            "command": command,
            "schedule_type": schedule_type,
            "interval_seconds": interval_seconds,
            "run_at_time": run_at_time,
            "enabled": True,
            "created": time.time(),
            "last_run": None,
            "run_count": 0
        }
        
        self.tasks.append(task)
        self.save()
        return {"ok": True, "id": task_id}

    def remove_task(self, task_id: str) -> dict:
        initial_count = len(self.tasks)
        self.tasks = [t for t in self.tasks if t["id"] != task_id]
        if len(self.tasks) < initial_count:
            self.save()
            return {"ok": True}
        return {"ok": False, "error": "not found"}

    def list_tasks(self) -> List[dict]:
        return self.tasks

    def enable_task(self, task_id: str) -> dict:
        for t in self.tasks:
            if t["id"] == task_id:
                t["enabled"] = True
                self.save()
                return {"ok": True}
        return {"ok": False, "error": "not found"}

    def disable_task(self, task_id: str) -> dict:
        for t in self.tasks:
            if t["id"] == task_id:
                t["enabled"] = False
                self.save()
                return {"ok": True}
        return {"ok": False, "error": "not found"}

    def run_now(self, task_id: str) -> dict:
        for t in self.tasks:
            if t["id"] == task_id:
                return self._execute_task(t)
        return {"ok": False, "error": "not found"}

    def get_history(self, task_id: Optional[str] = None, limit: int = 20) -> List[dict]:
        history = []
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, 'r') as f:
                    for line in f:
                        if line.strip():
                            entry = json.loads(line)
                            if task_id is None or entry.get("task_id") == task_id:
                                history.append(entry)
            except Exception as e:
                self.logger.error(f"Failed to load task history: {e}")
        return history[-limit:]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()
        self.logger.info("AutomationEngine background thread started.")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        self.logger.info("AutomationEngine background thread stopped.")

    def _scheduler_loop(self):
        while self._running:
            now = time.time()
            now_dt = datetime.fromtimestamp(now)
            now_str = now_dt.strftime("%H:%M")
            
            for task in self.tasks:
                if not task.get("enabled", True):
                    continue
                
                should_run = False
                if task["schedule_type"] == "interval":
                    interval = task["interval_seconds"]
                    last_run = task.get("last_run") or 0
                    if now - last_run >= interval:
                        should_run = True
                elif task["schedule_type"] == "time":
                    if task["run_at_time"] == now_str:
                        # Ensure we don't run more than once per day/minute
                        last_run_ts = task.get("last_run")
                        if last_run_ts:
                            last_run_dt = datetime.fromtimestamp(last_run_ts)
                            if last_run_dt.date() != now_dt.date() or (now - last_run_ts) > 60:
                                should_run = True
                        else:
                            should_run = True
                
                if should_run:
                    # Run in a separate thread to avoid blocking the scheduler
                    threading.Thread(target=self._execute_task, args=(task,), daemon=True).start()
            
            time.sleep(10)

    def _execute_task(self, task: dict) -> dict:
        self.logger.info(f"Executing task: {task['name']} (ID: {task['id']})")
        
        try:
            # Update last_run immediately to prevent double-trigger
            task["last_run"] = time.time()
            task["run_count"] = task.get("run_count", 0) + 1
            self.save()

            result = subprocess.run(task["command"], shell=True, capture_output=True, text=True, timeout=30)
            
            history_entry = {
                "task_id": task["id"],
                "timestamp": time.time(),
                "command": task["command"],
                "returncode": result.returncode,
                "output": (result.stdout + result.stderr).strip()
            }
            self._log_history(history_entry)
            return {"ok": True, "output": history_entry["output"], "returncode": result.returncode}
        except subprocess.TimeoutExpired:
            self.logger.error(f"Task {task['id']} timed out after 30s")
            return {"ok": False, "error": "Timeout expired"}
        except Exception as e:
            self.logger.error(f"Task execution failed ({task['id']}): {e}")
            return {"ok": False, "error": str(e)}

    def _log_history(self, entry: dict):
        try:
            os.makedirs(os.path.dirname(self.history_path), exist_ok=True)
            with open(self.history_path, 'a') as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            self.logger.error(f"Failed to log task history: {e}")

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.tasks_path), exist_ok=True)
            with open(self.tasks_path, 'w') as f:
                json.dump(self.tasks, f, indent=4)
        except Exception as e:
            self.logger.error(f"Failed to save tasks: {e}")

    def load(self) -> None:
        if os.path.exists(self.tasks_path):
            try:
                with open(self.tasks_path, 'r') as f:
                    self.tasks = json.load(f)
            except Exception as e:
                self.logger.error(f"Failed to load tasks: {e}")
                self.tasks = []
