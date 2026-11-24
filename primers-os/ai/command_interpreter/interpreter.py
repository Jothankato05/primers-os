"""
PRIMERS OS — Command Interpreter
Translates user text input into structured system commands.
"""

import difflib
import re
import shlex
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import PrimersLogger


@dataclass
class ParsedCommand:
    action: str               # e.g. "list_processes", "launch", "status"
    args: List[str]
    flags: Dict[str, str]     # e.g. {"sort": "cpu", "limit": "20"}
    raw: str
    confidence: float = 1.0   # 1.0 = exact command, <1.0 = natural language
    word: str = ""            # the command word that matched
    rest: str = ""            # raw text after the command word
    suggestions: List[str] = field(default_factory=list)


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
    "datasaver":               ("datasaver",       "Data Saver: metered network & paused downloads"),
    "lab":                     ("lab",             "Lab Mode: shared account wiped at sign-out"),
    "exam":                    ("exam",            "Exam Mode: is a computer-based test running here?"),
    "benchmark":               ("benchmark",       "Measure boot time, RAM and disk against PRIMERS targets (--json)"),
    "study":                   ("study",           "Study Mode: focus timer, pauses distracting sites (study 25 | stop)"),
    "focus":                   ("study",           "Study Mode: focus timer, pauses distracting sites (study 25 | stop)"),
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

    # Intelligence
    "ask":                     ("ask",             "Ask Primers anything (offline knowledge)"),
    "advise":                  ("advise",          "AI recommendations for this system"),
    "insights":                ("advise",          "AI recommendations for this system"),
    "learn":                   ("learn",           "Behavioural learning engine"),
    "task":                    ("task",            "Task scheduler & automation"),
    "cyber":                   ("cyber",           "Defensive cyber intelligence"),
    "kernel":                  ("kernel",          "Linux kernel interface info"),

    # Services
    "gpa":                     ("gpa",             "GPA calculator and tracker"),
    "graph":                   ("graph",           "Network topology mapper"),
    "modules":                 ("modules",         "List installable software modules"),
    "browse":                  ("browse",          "Open Primers Lite Bee (URL or search)"),
    "plugins":                 ("plugins",         "List loaded plugins"),

    # Interfaces
    "gui":                     ("gui",             "Web-based dashboard controller"),
    "voice":                   ("voice",           "Voice command engine"),
}

HELP_GROUPS = {
    "System":       ["status", "alerts", "datasaver", "lab", "exam", "benchmark", "kernel", "version"],
    "Process":      ["ps", "kill", "launch", "find", "suspend", "resume", "priority"],
    "Security":     ["security", "threats", "connections", "cyber"],
    "Intelligence": ["ask", "advise", "learn", "task"],
    "Services":     ["browse", "math", "gpa", "graph", "modules", "plugins"],
    "Interface":    ["gui", "voice", "clear", "help", "exit"],
}

# Natural language patterns. Anchored so that ordinary sentences don't
# trigger actions by accident; the optional named group "arg" is the argument.
NL_PATTERNS: List[Tuple[str, str]] = [
    # Study Mode comes before the generic "start <program>" pattern
    (r"^(?:start\s+|begin\s+)?(?:a\s+)?(?:study(?:ing)?|focus(?:ing)?)(?:\s+(?:session|mode))?"
     r"\s+(?:for\s+)?(?P<arg>\d{1,3})(?:\s*(?:minutes?|mins?|m))?$", "study"),
    (r"^(?:start|begin)\s+(?:a\s+)?(?:study(?:ing)?|focus(?:ing)?)(?:\s+(?:session|mode))?$", "study_start"),
    (r"^(?P<arg>stop|end|quit|finish)\s+(?:the\s+)?(?:studying|focusing|(?:study|focus)(?:\s+(?:session|mode))?)$", "study"),
    (r"^(?:please\s+)?(?:show|list)\s+(?:me\s+)?(?:all\s+)?(?:the\s+)?(?:running\s+)?process(?:es)?$", "list_processes"),
    (r"^what(?:'s|\s+is)\s+running\??$",                                                              "list_processes"),
    (r"^(?:please\s+)?(?:kill|terminate|stop)\s+(?:process\s+|pid\s+)?(?P<arg>\d+)$",               "kill_process"),
    (r"^(?:please\s+)?(?:open|start|launch)\s+(?P<arg>[\w./+-][\w ./+-]*)$",                          "launch"),
    (r"^(?:show\s+)?(?:the\s+)?system\s+(?:status|health)\??$|^how\s+is\s+(?:the\s+|my\s+)?system\??$", "system_status"),
    (r"^(?:show\s+)?(?:any\s+|all\s+)?(?:security\s+)?threats?(?:\s+detected)?\??$|^am\s+i\s+safe\??$",  "list_threats"),
    (r"^(?:show\s+)?(?:any\s+|all\s+)?alerts?\??$",                                                   "list_alerts"),
    (r"^(?:show\s+)?(?:the\s+)?network\s+connections?$",                                              "list_connections"),
    (r"^(?:am\s+i\s+on\s+(?:a\s+)?metered(?:\s+(?:network|connection))?|data\s+saver(?:\s+status)?)\??$", "datasaver"),
    (r"^(?:lab\s+mode(?:\s+status)?|is\s+this\s+a\s+(?:shared\s+|lab\s+)*(?:computer|machine|pc|account)|"
     r"(?:will|are|do)\s+my\s+files\s+(?:be\s+|get\s+)?(?:deleted|wiped|erased|kept|saved))\??$", "lab"),
    (r"^(?:run\s+(?:a\s+)?)?benchmark(?:\s+(?:this|my)\s+(?:pc|computer|machine|laptop))?$|"
     r"^how\s+fast\s+(?:is\s+)?(?:this|my)\s+(?:pc|computer|machine|laptop)(?:\s+boot(?:ing)?)?\??$|"
     r"^how\s+(?:long|fast)\s+does\s+(?:this|my)\s+(?:pc|computer|machine|laptop)\s+(?:take\s+to\s+)?boot\??$", "benchmark"),
    (r"^(?:is\s+)?exam\s+mode(?:\s+(?:on|off|running|status))?\??$|^is\s+(?:an\s+|the\s+)?exam\s+running\??$", "exam"),
    (r"^find\s+(?:process\s+)?(?P<arg>\S+)$",                                                         "find_process"),
    (r"^(?:calculate|compute|solve)\s+(?P<arg>.+)$",                                                  "math"),
    (r"^what(?:'s|\s+is)\s+(?P<arg>[\d\s+\-*/^%().,]+?)\s*\??$",                                     "math"),
    (r"^(?:give\s+me\s+)?(?:any\s+)?(?:advice|recommendations?|suggestions?)\??$",                    "advise"),
    (r"^(?:what\s+should\s+i\s+do|any\s+advice)\??$",                                                 "advise"),
]


def _is_emergency(text: str) -> bool:
    from services.knowledge.engine import KnowledgeBase
    return KnowledgeBase.is_emergency(text)


_QUESTION = re.compile(
    r"^(who|what|whats|what's|where|when|why|how|which|is|are|does|do|can|could|should|"
    r"tell me|explain|i'?m in danger|help me)\b", re.IGNORECASE)


class CommandInterpreter:
    def __init__(self, process_manager=None, decision_engine=None, settings=None):
        self.logger = PrimersLogger.get_logger("command_interpreter")
        self.process_manager = process_manager
        self.decision_engine = decision_engine
        self.settings = settings
        # Per-instance registry so plugins never mutate the module default
        self.COMMAND_MAP: Dict[str, Tuple[str, str]] = dict(COMMAND_MAP)
        self._nl_patterns = [(re.compile(p, re.IGNORECASE), a) for p, a in NL_PATTERNS]

    # ------------------------------------------------------------------ #
    #  Registry
    # ------------------------------------------------------------------ #

    def register_command(self, word: str, action: str, description: str = "") -> None:
        word = word.strip().lower()
        if not word or " " in word:
            raise ValueError(f"Invalid command word: {word!r}")
        self.COMMAND_MAP[word] = (action, description)

    def command_words(self) -> List[str]:
        return sorted(self.COMMAND_MAP)

    def word_for_action(self, action: str) -> str:
        """The primary command word for an action (first registered)."""
        for word, (act, _) in self.COMMAND_MAP.items():
            if act == action:
                return word
        return action

    def canonical(self, parsed: "ParsedCommand") -> str:
        """Command line in canonical form, for learning from natural language."""
        if parsed.confidence == 1.0:
            return parsed.raw
        return " ".join([self.word_for_action(parsed.action)] + list(parsed.args)).strip()

    # ------------------------------------------------------------------ #
    #  Parsing
    # ------------------------------------------------------------------ #

    def parse(self, raw_input: str) -> Optional[ParsedCommand]:
        raw = (raw_input or "").strip()
        if not raw:
            return None

        try:
            tokens = shlex.split(raw)
        except ValueError:
            tokens = raw.split()
        if not tokens:
            return None

        cmd_word = tokens[0].lower()
        args = tokens[1:]

        # Emergencies first: "help me, I'm in danger" must never run 'help'
        if _is_emergency(raw):
            return ParsedCommand(action="ask", args=[raw], flags={}, raw=raw,
                                 confidence=0.9, word=cmd_word, rest=raw)
        flags = self._extract_flags(args)
        clean_args = [a for a in args if not self._is_flag(a)]
        rest = raw.split(None, 1)[1] if len(raw.split(None, 1)) > 1 else ""

        # Natural language first: the patterns are anchored to the whole input,
        # so they only win for phrasings like "kill process 42" that the
        # plain command ("kill") would misread. Flags always mean a command.
        if not flags:
            text = re.sub(r"\s+", " ", raw).strip().rstrip(".!")
            for pattern, action in self._nl_patterns:
                match = pattern.match(text)
                if match:
                    arg = match.groupdict().get("arg")
                    return ParsedCommand(action=action, args=[arg.strip()] if arg else [],
                                         flags=flags, raw=raw, confidence=0.85,
                                         word=cmd_word, rest=arg.strip() if arg else "")

        if cmd_word in self.COMMAND_MAP:
            action, _ = self.COMMAND_MAP[cmd_word]
            return ParsedCommand(action=action, args=clean_args, flags=flags, raw=raw,
                                 confidence=1.0, word=cmd_word, rest=rest)

        # Anything phrased as a question goes to Ask Primers
        if _QUESTION.match(raw) or raw.endswith("?"):
            return ParsedCommand(action="ask", args=[raw], flags={}, raw=raw,
                                 confidence=0.5, word=cmd_word, rest=raw)

        return ParsedCommand(action="unknown", args=tokens, flags=flags, raw=raw,
                             confidence=0.0, word=cmd_word, rest=rest,
                             suggestions=self.suggest_commands(cmd_word))

    def suggest_commands(self, word: str, n: int = 3) -> List[str]:
        return difflib.get_close_matches(word.lower(), self.command_words(), n=n, cutoff=0.6)

    def get_help_text(self) -> str:
        lines = ["\n  PRIMERS OS — Available Commands\n  " + "─" * 38]
        listed = set()
        for group, cmds in HELP_GROUPS.items():
            lines.append(f"\n  [{group}]")
            for c in cmds:
                if c in self.COMMAND_MAP:
                    _, desc = self.COMMAND_MAP[c]
                    lines.append(f"    {c:<14} {desc}")
                    listed.add(self.COMMAND_MAP[c][0])
        extra = sorted(w for w, (action, _) in self.COMMAND_MAP.items()
                       if w not in COMMAND_MAP and action not in listed)
        if extra:
            lines.append("\n  [Plugins]")
            for w in extra:
                lines.append(f"    {w:<14} {self.COMMAND_MAP[w][1]}")
        lines.append("\n  Tip: natural language works too — 'show me processes', 'am i safe?',")
        lines.append("       'what is 2^10', 'any advice?', 'who founded Primers?'\n")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_flag(arg: str) -> bool:
        return arg.startswith("--") or arg in ("-y", "-f")

    @staticmethod
    def _extract_flags(args: List[str]) -> Dict[str, str]:
        flags = {}
        for arg in args:
            if arg == "-y":
                flags["yes"] = "true"
            elif arg == "-f":
                flags["force"] = "true"
            elif arg.startswith("--") and len(arg) > 2:
                key, _, val = arg[2:].partition("=")
                flags[key] = val if val else "true"
        return flags
