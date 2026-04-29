"""
PRIMERS OS — Command Interpreter
Translates user text input into structured system commands.
"""

import re
import shlex
from typing import Optional, Callable, Dict, List, Tuple
from dataclasses import dataclass
from utils.logger import PrimersLogger


@dataclass
class ParsedCommand:
    action: str               # e.g. "list_processes", "launch", "status"
    args: List[str]
    flags: Dict[str, str]     # e.g. {"sort": "cpu", "limit": "20"}
    raw: str
    confidence: float = 1.0   # 0.0–1.0 for future NLP layer


# ------------------------------------------------------------------ #
#  Command Registry
# ------------------------------------------------------------------ #

COMMAND_MAP: Dict[str, Tuple[str, str]] = {
    # CLI command             → (action, description)
    "ps":                      ("list_processes",  "List running processes"),
    "processes":               ("list_processes",  "List running processes"),
    "top":                     ("list_processes",  "List processes sorted by CPU"),
    "kill":                    ("kill_process",    "Terminate a process by PID"),
    "terminate":               ("kill_process",    "Terminate a process by PID"),
    "launch":                  ("launch",          "Launch a new process"),
    "run":                     ("launch",          "Launch a new process"),
    "exec":                    ("launch",          "Launch a new process"),
    "status":                  ("system_status",   "Show system health summary"),
    "sysinfo":                 ("system_status",   "Show system health summary"),
    "health":                  ("system_status",   "Show system health summary"),
    "security":                ("security_status", "Show security engine status"),
    "threats":                 ("list_threats",    "Show security threat events"),
    "alerts":                  ("list_alerts",     "Show system alerts"),
    "connections":             ("list_connections","Show active network connections"),
    "netstat":                 ("list_connections","Show active network connections"),
    "find":                    ("find_process",    "Find process by name"),
    "search":                  ("find_process",    "Find process by name"),
    "suspend":                 ("suspend_process", "Suspend a process"),
    "resume":                  ("resume_process",  "Resume a suspended process"),
    "priority":                ("set_priority",    "Set process priority (nice value)"),
    "math":                    ("math",            "Evaluate a mathematical expression"),
    "calc":                    ("math",            "Evaluate a mathematical expression"),
    "help":                    ("help",            "Show available commands"),
    "?":                       ("help",            "Show available commands"),
    "clear":                   ("clear",           "Clear the terminal"),
    "cls":                     ("clear",           "Clear the terminal"),
    "version":                 ("version",         "Show PRIMERS OS version"),
    "exit":                    ("exit",            "Exit PRIMERS OS"),
    "quit":                    ("exit",            "Exit PRIMERS OS"),
    "bye":                     ("exit",            "Exit PRIMERS OS"),
    
    # Phase 2 — Services
    "gpa":                     ("gpa",             "GPA calculator and tracker"),
    "graph":                   ("graph",           "Network topology mapper"),
    
    # Phase 2 — Intelligence
    "learn":                   ("learn",           "Behavioural learning engine"),
    "task":                    ("task",            "Task scheduler & automation"),
    "cyber":                   ("cyber",           "Defensive cyber intelligence"),
    "kernel":                  ("kernel",          "Linux kernel interface info"),
    
    # Phase 3 — Interface
    "gui":                     ("gui",             "Web-based dashboard controller"),
    "voice":                   ("voice",           "Voice command engine"),
}


# Natural language pattern → (action, extraction_fn)
NL_PATTERNS = [
    (r"show\s+(me\s+)?processes?",         "list_processes"),
    (r"what('s| is) running",              "list_processes"),
    (r"kill\s+process\s+(\d+)",            "kill_process"),
    (r"terminate\s+(\d+)",                 "kill_process"),
    (r"(open|start|launch|run)\s+(.+)",    "launch"),
    (r"system\s+status",                   "system_status"),
    (r"(any\s+)?threats?(\s+detected)?",   "list_threats"),
    (r"network\s+connections?",            "list_connections"),
    (r"find\s+(.+)",                       "find_process"),
    (r"calculate\s+(.+)",                  "math"),
    (r"what('s|\s+is)\s+(\d[\d\s+\-*/().]+)", "math"),
]


class CommandInterpreter:
    def __init__(self, process_manager, decision_engine, settings):
        self.logger = PrimersLogger.get_logger("command_interpreter")
        self.process_manager = process_manager
        self.decision_engine = decision_engine
        self.settings = settings

    def parse(self, raw_input: str) -> Optional[ParsedCommand]:
        raw = raw_input.strip()
        if not raw:
            return None

        # Try direct command match first
        try:
            tokens = shlex.split(raw)
        except ValueError:
            tokens = raw.split()

        if not tokens:
            return None

        cmd_word = tokens[0].lower()
        args = tokens[1:]
        flags = self._extract_flags(args)
        clean_args = [a for a in args if not a.startswith("--")]

        if cmd_word in COMMAND_MAP:
            action, _ = COMMAND_MAP[cmd_word]
            return ParsedCommand(
                action=action,
                args=clean_args,
                flags=flags,
                raw=raw,
                confidence=1.0
            )

        # Try natural language patterns
        for pattern, action in NL_PATTERNS:
            match = re.search(pattern, raw.lower())
            if match:
                extracted_args = [g for g in match.groups() if g and not g.startswith((" ", "me", "any", "detected"))]
                return ParsedCommand(
                    action=action,
                    args=extracted_args,
                    flags=flags,
                    raw=raw,
                    confidence=0.85
                )

        # Unknown — return with action "unknown"
        return ParsedCommand(
            action="unknown",
            args=tokens,
            flags=flags,
            raw=raw,
            confidence=0.0
        )

    def get_help_text(self) -> str:
        lines = ["\n  PRIMERS OS — Available Commands\n  " + "─" * 38]
        groups = {
            "System":   ["status", "alerts", "version"],
            "Process":  ["ps", "kill", "launch", "find", "suspend", "resume", "priority"],
            "Security": ["security", "threats", "connections"],
            "Utility":  ["math", "clear", "help", "exit"],
            "Phase 2":  ["gpa", "graph", "learn", "task", "cyber", "kernel"],
            "Phase 3":  ["gui", "voice"],
        }
        for group, cmds in groups.items():
            lines.append(f"\n  [{group}]")
            for c in cmds:
                if c in COMMAND_MAP:
                    _, desc = COMMAND_MAP[c]
                    lines.append(f"    {c:<14} {desc}")
        lines.append("\n  Tip: Natural language also works — e.g. 'show me processes'\n")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_flags(args: List[str]) -> Dict[str, str]:
        flags = {}
        for arg in args:
            if arg.startswith("--"):
                parts = arg[2:].split("=", 1)
                key = parts[0]
                val = parts[1] if len(parts) > 1 else "true"
                flags[key] = val
        return flags
