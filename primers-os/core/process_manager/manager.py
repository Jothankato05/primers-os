"""
PRIMERS OS — Process Manager
Manages system processes: list, launch, terminate, prioritise, isolate.
"""

import psutil
import subprocess
import os
import signal
from typing import List, Optional, Dict
from utils.logger import PrimersLogger


class ProcessRecord:
    def __init__(self, pid: int, name: str, status: str,
                 cpu: float, memory: float, cmdline: List[str]):
        self.pid = pid
        self.name = name
        self.status = status
        self.cpu = cpu
        self.memory = memory
        self.cmdline = cmdline

    def to_dict(self) -> dict:
        return {
            "pid": self.pid,
            "name": self.name,
            "status": self.status,
            "cpu%": f"{self.cpu:.1f}",
            "mem%": f"{self.memory:.1f}",
            "cmdline": " ".join(self.cmdline[:3]),
        }


class ProcessManager:
    def __init__(self):
        self.logger = PrimersLogger.get_logger("process_manager")
        self._launched: Dict[int, subprocess.Popen] = {}  # PID → Popen (our own processes)

    # ------------------------------------------------------------------ #
    #  Query
    # ------------------------------------------------------------------ #

    def list_processes(self, sort_by: str = "cpu", limit: int = 20) -> List[ProcessRecord]:
        records = []
        for proc in psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_percent", "cmdline"]):
            try:
                info = proc.info
                records.append(ProcessRecord(
                    pid=info["pid"],
                    name=info["name"] or "unknown",
                    status=info["status"] or "unknown",
                    cpu=info["cpu_percent"] or 0.0,
                    memory=info["memory_percent"] or 0.0,
                    cmdline=info["cmdline"] or [],
                ))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        key_map = {
            "cpu": lambda r: r.cpu,
            "memory": lambda r: r.memory,
            "pid": lambda r: r.pid,
            "name": lambda r: r.name.lower(),
        }
        records.sort(key=key_map.get(sort_by, key_map["cpu"]), reverse=(sort_by != "name"))
        return records[:limit]

    def get_process(self, pid: int) -> Optional[ProcessRecord]:
        try:
            proc = psutil.Process(pid)
            info = proc.as_dict(attrs=["pid", "name", "status", "cpu_percent", "memory_percent", "cmdline"])
            return ProcessRecord(
                pid=info["pid"],
                name=info["name"] or "unknown",
                status=info["status"],
                cpu=info["cpu_percent"] or 0.0,
                memory=info["memory_percent"] or 0.0,
                cmdline=info["cmdline"] or [],
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def find_by_name(self, name: str) -> List[ProcessRecord]:
        return [p for p in self.list_processes(limit=1000) if name.lower() in p.name.lower()]

    # ------------------------------------------------------------------ #
    #  Control
    # ------------------------------------------------------------------ #

    def launch(self, command: str, shell: bool = False) -> Optional[int]:
        """Launch a new process. Returns PID or None on failure."""
        try:
            args = command.split() if not shell else command
            proc = subprocess.Popen(
                args,
                shell=shell,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            self._launched[proc.pid] = proc
            self.logger.info(f"Launched: '{command}' → PID {proc.pid}")
            return proc.pid
        except (FileNotFoundError, PermissionError, OSError) as e:
            self.logger.error(f"Launch failed for '{command}': {e}")
            return None

    def terminate(self, pid: int, force: bool = False) -> bool:
        """Terminate a process gracefully (SIGTERM) or forcefully (SIGKILL)."""
        try:
            proc = psutil.Process(pid)
            if force:
                proc.kill()
                self.logger.info(f"Killed PID {pid} (SIGKILL)")
            else:
                proc.terminate()
                self.logger.info(f"Terminated PID {pid} (SIGTERM)")
            if pid in self._launched:
                del self._launched[pid]
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.logger.warning(f"Could not terminate PID {pid}: {e}")
            return False

    def set_priority(self, pid: int, nice: int) -> bool:
        """
        Set process nice value.
        nice: -20 (highest priority) to 19 (lowest)
        Note: lowering nice (increasing priority) requires root on Linux.
        """
        try:
            proc = psutil.Process(pid)
            proc.nice(nice)
            self.logger.info(f"Set PID {pid} nice={nice}")
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError) as e:
            self.logger.warning(f"Could not set priority for PID {pid}: {e}")
            return False

    def suspend(self, pid: int) -> bool:
        try:
            psutil.Process(pid).suspend()
            self.logger.info(f"Suspended PID {pid}")
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.logger.warning(f"Could not suspend PID {pid}: {e}")
            return False

    def resume(self, pid: int) -> bool:
        try:
            psutil.Process(pid).resume()
            self.logger.info(f"Resumed PID {pid}")
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.logger.warning(f"Could not resume PID {pid}: {e}")
            return False

    def get_launched(self) -> List[dict]:
        """Return processes we launched in this session."""
        result = []
        for pid, proc in list(self._launched.items()):
            if proc.poll() is None:
                result.append({"pid": pid, "returncode": None, "running": True})
            else:
                result.append({"pid": pid, "returncode": proc.returncode, "running": False})
                del self._launched[pid]
        return result
