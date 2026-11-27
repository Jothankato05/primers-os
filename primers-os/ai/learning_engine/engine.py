"""
PRIMERS OS - Learning Engine
Tracks command history and suggests future commands based on usage patterns.
History is stored privately (0600) in the user's data directory.
"""

import json
import os
import threading
import time
from collections import Counter
from datetime import datetime
from typing import Dict, List, Optional

from utils import paths
from utils.logger import PrimersLogger

MAX_HISTORY = 5000            # entries kept in memory / considered for stats
SESSION_GAP_SECONDS = 1800    # 30 minutes of inactivity starts a new session
DEFAULT_SUGGESTIONS = ["status", "ps", "help"]


def _first_word(command: str) -> str:
    parts = (command or "").split()
    return parts[0].lower() if parts else ""


class LearningEngine:
    """
    Behavioural learning engine.
    Learns which commands the user runs, when, and in what order.
    """

    def __init__(self, history_path: Optional[str] = None):
        self.logger = PrimersLogger.get_logger("learning_engine")
        self.history_path = history_path or paths.data_file("usage.jsonl")
        self.usage_data: List[dict] = []
        self._lock = threading.Lock()
        self.load()

    # ------------------------------------------------------------------ #
    #  Recording
    # ------------------------------------------------------------------ #

    def log_command(self, raw: str, action: str, args: Optional[list] = None) -> None:
        if not raw or not raw.strip():
            return
        entry = {
            "timestamp": time.time(),
            "command": raw.strip(),
            "action": action,
            "hour": datetime.now().hour,
            "args": list(args or []),
        }
        with self._lock:
            self.usage_data.append(entry)
            if len(self.usage_data) > MAX_HISTORY:
                del self.usage_data[:-MAX_HISTORY]
        try:
            paths.append_private(self.history_path, json.dumps(entry) + "\n")
        except OSError as e:
            self.logger.error(f"Failed to log usage: {e}")

    def clear(self) -> None:
        with self._lock:
            self.usage_data = []
        try:
            if os.path.exists(self.history_path):
                os.remove(self.history_path)
        except OSError as e:
            self.logger.error(f"Failed to clear usage history: {e}")

    # ------------------------------------------------------------------ #
    #  Analysis
    # ------------------------------------------------------------------ #

    def get_stats(self) -> dict:
        with self._lock:
            data = list(self.usage_data)

        if not data:
            return {
                "total_commands": 0,
                "most_used": [],
                "least_used": [],
                "top_commands": [],
                "busiest_hour": None,
                "command_sequences": [],
                "session_count": 0,
            }

        cmd_counts = Counter(_first_word(e["command"]) or "unknown" for e in data)
        hour_counts = Counter(e.get("hour", 0) for e in data)
        ranked = cmd_counts.most_common()

        sequences = Counter(
            f"{_first_word(a['command'])}→{_first_word(b['command'])}"
            for a, b in zip(data, data[1:])
        )

        session_count = 1 + sum(
            1 for a, b in zip(data, data[1:])
            if b["timestamp"] - a["timestamp"] > SESSION_GAP_SECONDS
        )

        return {
            "total_commands": len(data),
            "most_used": [{"command": k, "count": v} for k, v in ranked[:5]],
            "least_used": [{"command": k, "count": v} for k, v in ranked[-5:]],
            "top_commands": ranked[:5],  # [(command, count), ...]
            "busiest_hour": hour_counts.most_common(1)[0][0],
            "command_sequences": [{"sequence": k, "count": v} for k, v in sequences.most_common(3)],
            "session_count": session_count,
        }

    def suggest(self, recent_commands: Optional[List[str]] = None, limit: int = 3) -> List[str]:
        """Suggest the next commands, from sequences, time of day and frequency."""
        with self._lock:
            data = list(self.usage_data)
        if not data:
            return DEFAULT_SUGGESTIONS[:limit]

        if recent_commands is None:
            recent_commands = [data[-1]["command"]]

        suggestions: List[str] = []

        def add(cmds):
            for c in cmds:
                if c and c not in suggestions:
                    suggestions.append(c)

        # 1. What usually follows the last command
        if recent_commands:
            last = _first_word(recent_commands[-1])
            followers = Counter(
                _first_word(b["command"]) for a, b in zip(data, data[1:])
                if _first_word(a["command"]) == last
            )
            add(c for c, _ in followers.most_common())

        # 2. What the user runs at this hour
        hour = datetime.now().hour
        add(c for c, _ in Counter(_first_word(e["command"]) for e in data
                                  if e.get("hour") == hour).most_common())

        # 3. Overall favourites, then sensible defaults
        add(c for c, _ in Counter(_first_word(e["command"]) for e in data).most_common())
        add(DEFAULT_SUGGESTIONS)
        return suggestions[:limit]

    def known_commands(self) -> Dict[str, int]:
        with self._lock:
            return dict(Counter(_first_word(e["command"]) for e in self.usage_data))

    # ------------------------------------------------------------------ #
    #  Persistence
    # ------------------------------------------------------------------ #

    def load(self) -> List[dict]:
        data = []
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue  # skip a corrupt line, keep the rest
                        if isinstance(entry, dict) and "command" in entry and "timestamp" in entry:
                            data.append(entry)
            except OSError as e:
                self.logger.error(f"Failed to load usage history: {e}")
        with self._lock:
            self.usage_data = data[-MAX_HISTORY:]
        return self.usage_data
