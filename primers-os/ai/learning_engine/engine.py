import json
import os
import time
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from utils.logger import PrimersLogger

class LearningEngine:
    """
    Behavioural learning engine.
    Tracks command history and suggests future commands based on usage patterns.
    """

    def __init__(self):
        self.logger = PrimersLogger.get_logger("learning_engine")
        # Ensure path is absolute
        self.history_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs", "usage.jsonl")
        self.usage_data: List[dict] = []
        self.load()

    def log_command(self, raw: str, action: str, args: list) -> None:
        """Appends one line to logs/usage.jsonl."""
        entry = {
            "timestamp": time.time(),
            "command": raw,
            "action": action,
            "hour": datetime.now().hour,
            "args": args
        }
        
        self.usage_data.append(entry)
        
        try:
            os.makedirs(os.path.dirname(self.history_path), exist_ok=True)
            with open(self.history_path, 'a') as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            self.logger.error(f"Failed to log usage: {e}")

    def get_stats(self) -> dict:
        """Return detailed usage statistics."""
        if not self.usage_data:
            return {
                "total_commands": 0,
                "most_used": [],
                "least_used": [],
                "busiest_hour": 0,
                "command_sequences": [],
                "session_count": 0
            }
        
        total_commands = len(self.usage_data)
        
        # 1. Frequency mapping
        cmd_counts = {}
        hour_counts = {}
        for entry in self.usage_data:
            cmd = entry["command"].split()[0] if entry["command"].split() else "unknown"
            cmd_counts[cmd] = cmd_counts.get(cmd, 0) + 1
            hour = entry.get("hour", 0)
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
            
        sorted_cmds = sorted(cmd_counts.items(), key=lambda x: x[1], reverse=True)
        most_used = [{"command": k, "count": v} for k, v in sorted_cmds[:5]]
        least_used = [{"command": k, "count": v} for k, v in sorted_cmds[-5:]]
        
        # 2. Busiest hour
        busiest_hour = max(hour_counts.items(), key=lambda x: x[1])[0] if hour_counts else 0
        
        # 3. Command sequences (top 3)
        sequences = {}
        for i in range(len(self.usage_data) - 1):
            cmd1 = self.usage_data[i]["command"].split()[0] if self.usage_data[i]["command"].split() else "unknown"
            cmd2 = self.usage_data[i+1]["command"].split()[0] if self.usage_data[i+1]["command"].split() else "unknown"
            seq = f"{cmd1}→{cmd2}"
            sequences[seq] = sequences.get(seq, 0) + 1
            
        sorted_seqs = sorted(sequences.items(), key=lambda x: x[1], reverse=True)
        command_sequences = [{"sequence": k, "count": v} for k, v in sorted_seqs[:3]]
        
        # 4. Session count (gaps > 30min)
        session_count = 1
        for i in range(len(self.usage_data) - 1):
            gap = self.usage_data[i+1]["timestamp"] - self.usage_data[i]["timestamp"]
            if gap > 1800: # 30 mins
                session_count += 1
                
        return {
            "total_commands": total_commands,
            "most_used": most_used,
            "least_used": least_used,
            "busiest_hour": busiest_hour,
            "command_sequences": command_sequences,
            "session_count": session_count
        }

    def suggest(self, recent_commands: list[str]) -> list[str]:
        """Suggest top 3 next commands based on history."""
        if not self.usage_data:
            return ["status", "processes", "help"]

        suggestions = []
        
        # 1. Sequence matching
        if recent_commands:
            last_cmd = recent_commands[-1].split()[0] if recent_commands[-1].split() else ""
            seq_candidates = {}
            for i in range(len(self.usage_data) - 1):
                curr = self.usage_data[i]["command"].split()[0] if self.usage_data[i]["command"].split() else ""
                if curr == last_cmd:
                    next_cmd = self.usage_data[i+1]["command"].split()[0] if self.usage_data[i+1]["command"].split() else ""
                    if next_cmd:
                        seq_candidates[next_cmd] = seq_candidates.get(next_cmd, 0) + 1
            
            sorted_next = sorted(seq_candidates.items(), key=lambda x: x[1], reverse=True)
            suggestions.extend([cmd for cmd, count in sorted_next if cmd not in suggestions])

        # 2. Hour of day matching
        current_hour = datetime.now().hour
        hour_candidates = {}
        for entry in self.usage_data:
            if entry.get("hour") == current_hour:
                cmd = entry["command"].split()[0] if entry["command"].split() else ""
                if cmd:
                    hour_candidates[cmd] = hour_candidates.get(cmd, 0) + 1
        
        sorted_hour = sorted(hour_candidates.items(), key=lambda x: x[1], reverse=True)
        for cmd, count in sorted_hour:
            if cmd not in suggestions:
                suggestions.append(cmd)
            if len(suggestions) >= 3:
                break
        
        # 3. Overall frequency fallback
        if len(suggestions) < 3:
            stats = self.get_stats()
            for item in stats["most_used"]:
                if item["command"] not in suggestions:
                    suggestions.append(item["command"])
                if len(suggestions) >= 3:
                    break
        
        return suggestions[:3]

    def load(self) -> list[dict]:
        """Reads all log entries."""
        data = []
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, 'r') as f:
                    for line in f:
                        if line.strip():
                            data.append(json.loads(line))
            except Exception as e:
                self.logger.error(f"Failed to load usage history: {e}")
        self.usage_data = data
        return data
