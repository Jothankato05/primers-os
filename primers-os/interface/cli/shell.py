"""
PRIMERS OS — CLI Shell
Primary human-computer interaction layer.
"""

import inspect
import json
import os
import subprocess
import sys
import time
from typing import Callable, Dict, List, Optional

try:
    import readline
except ImportError:  # Windows has no readline
    readline = None

from ai.command_interpreter.interpreter import CommandInterpreter, ParsedCommand
from configs.settings import Settings
from core.process_manager.manager import ProcessManager, ProtectedProcessError
from core.security_engine.engine import SecurityEngine
from core.system_monitor.monitor import SystemMonitor
from services.math_engine.engine import MathEngine
from utils import paths
from utils.logger import PrimersLogger

# Voice may only trigger read-only actions: no kill/launch/task/gpa changes.
VOICE_SAFE_ACTIONS = {
    "list_processes", "system_status", "security_status", "list_threats",
    "list_alerts", "list_connections", "find_process", "math", "help",
    "version", "advise", "kernel", "ask", "datasaver", "lab", "benchmark",
}


# ─────────────────────────────────────────────
#  ANSI colour helpers (disabled when not a TTY or NO_COLOR is set)
# ─────────────────────────────────────────────
def _colour_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("PRIMERS_FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


class C:
    RESET = BOLD = DIM = CYAN = GREEN = YELLOW = RED = MAGENTA = BLUE = WHITE = GREY = ""

    @classmethod
    def configure(cls, enabled: Optional[bool] = None):
        on = _colour_enabled() if enabled is None else enabled
        codes = {
            "RESET": "\033[0m", "BOLD": "\033[1m", "DIM": "\033[2m",
            "CYAN": "\033[96m", "GREEN": "\033[92m", "YELLOW": "\033[93m",
            "RED": "\033[91m", "MAGENTA": "\033[95m", "BLUE": "\033[94m",
            "WHITE": "\033[97m", "GREY": "\033[90m",
        }
        for name, code in codes.items():
            setattr(cls, name, code if on else "")

    @classmethod
    def ok(cls, s):     return f"{cls.GREEN}{s}{cls.RESET}"
    @classmethod
    def warn(cls, s):   return f"{cls.YELLOW}{s}{cls.RESET}"
    @classmethod
    def err(cls, s):    return f"{cls.RED}{s}{cls.RESET}"
    @classmethod
    def info(cls, s):   return f"{cls.CYAN}{s}{cls.RESET}"
    @classmethod
    def dim(cls, s):    return f"{cls.GREY}{s}{cls.RESET}"
    @classmethod
    def hi(cls, s):     return f"{cls.BOLD}{cls.WHITE}{s}{cls.RESET}"
    @classmethod
    def accent(cls, s): return f"{cls.MAGENTA}{s}{cls.RESET}"


C.configure()


def banner() -> str:
    return f"""
{C.CYAN}{C.BOLD}
  ██████╗ ██████╗ ██╗███╗   ███╗███████╗██████╗ ███████╗     ██████╗ ███████╗
  ██╔══██╗██╔══██╗██║████╗ ████║██╔════╝██╔══██╗██╔════╝    ██╔═══██╗██╔════╝
  ██████╔╝██████╔╝██║██╔████╔██║█████╗  ██████╔╝███████╗    ██║   ██║███████╗
  ██╔═══╝ ██╔══██╗██║██║╚██╔╝██║██╔══╝  ██╔══██╗╚════██║    ██║   ██║╚════██║
  ██║     ██║  ██║██║██║ ╚═╝ ██║███████╗██║  ██║███████║    ╚██████╔╝███████║
  ╚═╝     ╚═╝  ╚═╝╚═╝╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝     ╚═════╝ ╚══════╝
{C.RESET}{C.GREY}  AI-Native Modular OS Platform  ·  Genesis  ·  Type 'help' to begin
{C.RESET}"""


def divider() -> str:
    return C.dim("  " + "─" * 60)


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class PrimersShell:
    def __init__(
        self,
        command_interpreter: CommandInterpreter,
        system_monitor: SystemMonitor,
        process_manager: ProcessManager,
        security_engine: SecurityEngine,
        settings: Settings,
        learning_engine=None,
        automation_engine=None,
        cyber_intelligence=None,
        kernel_interface=None,
        gpa_service=None,
        graph_ai=None,
        decision_engine=None,
        knowledge=None,
        interactive: bool = True,
    ):
        self.logger = PrimersLogger.get_logger("cli")
        self.ci = command_interpreter
        self.command_interpreter = command_interpreter  # alias for plugins
        self.sm = system_monitor
        self.pm = process_manager
        self.se = security_engine
        self.settings = settings
        self.le = learning_engine
        self.ae = automation_engine
        self.cyber = cyber_intelligence
        self.kernel = kernel_interface
        self.gpa = gpa_service
        self.graph = graph_ai
        self.de = decision_engine or getattr(command_interpreter, "decision_engine", None)
        self.kb = knowledge
        self.interactive = interactive

        self.math = MathEngine()
        self._running = True
        self._history_file = os.path.join(paths.data_dir(), ".cli_history")
        self._threats_seen_at = time.time()
        self._alerts_seen = 0
        self._recent: List[str] = []

        self.show_banner = True
        self.voice = None          # set by main.py
        self.dashboard = None      # DashboardServer when running
        self.plugins: List[dict] = []
        self._plugin_handlers: Dict[str, Callable] = {}

        if interactive:
            self._setup_readline()

    @property
    def gui_active(self) -> bool:
        return bool(self.dashboard and self.dashboard.running)

    # ──────────────────────────────────────────
    #  Plugin API
    # ──────────────────────────────────────────

    def register_command(self, word: str, handler: Callable, description: str = "") -> None:
        """Add a command. handler(cmd, shell) / handler(cmd) / handler() → optional str."""
        action = f"plugin_{word.strip().lower()}"
        self.ci.register_command(word, action, description)
        self._plugin_handlers[action] = handler

    def _call_plugin(self, handler: Callable, cmd: ParsedCommand):
        try:
            n = len(inspect.signature(handler).parameters)
        except (TypeError, ValueError):
            n = 1
        result = handler(*([cmd, self][:n]))
        if result is not None:
            print(f"  {result}")

    # ──────────────────────────────────────────
    #  Execution
    # ──────────────────────────────────────────

    def execute(self, raw: str, source: str = "cli") -> bool:
        """Parse and run one command line. Returns False on error/refusal."""
        parsed = self.ci.parse(raw)
        if not parsed:
            return True

        if source == "voice" and parsed.action not in VOICE_SAFE_ACTIONS:
            print(C.warn(f"\n  🎙 Voice can't run '{parsed.raw}' — type it instead (voice is read-only)."))
            return False

        if self.le and parsed.action not in ("unknown", "exit"):
            self.le.log_command(self.ci.canonical(parsed), parsed.action, parsed.args)
        self._recent.append(raw)
        self._recent = self._recent[-20:]

        try:
            self._dispatch(parsed)
            return parsed.action != "unknown"
        except (SystemExit, KeyboardInterrupt):
            raise
        except ProtectedProcessError as e:
            print(C.err(f"  ✗ {e}"))
        except Exception as e:  # never let one command take the shell down
            self.logger.exception(f"Command failed: {raw}")
            print(C.err(f"  ✗ '{parsed.raw}' failed: {e}"))
            print(C.dim(f"    Details: {PrimersLogger.log_path()}"))
        return False

    def execute_voice(self, text: str) -> None:
        print(f"\n  {C.accent('🎙')} {C.dim('heard:')} {text}")
        self.execute(text, source="voice")

    def run(self):
        if self.show_banner:
            print(banner())
        self._show_boot_summary()
        self._show_lab_notice()
        print()

        while self._running:
            try:
                raw = self._prompt()
                if raw is None:
                    continue
                self.execute(raw)
            except KeyboardInterrupt:
                print(f"\n{C.dim('  (Use exit or quit to leave PRIMERS OS)')}")
            except EOFError:
                print()
                self._cmd_exit(None)

        self.shutdown()

    def shutdown(self):
        self._running = False
        for component in (self.sm, self.se, self.ae):
            try:
                if component:
                    component.stop()
            except Exception:
                pass
        if self.voice:
            try:
                self.voice.stop_listening()
            except Exception:
                pass
        if self.dashboard:
            try:
                self.dashboard.stop()
            except Exception:
                pass
        if readline is not None and self.interactive:
            try:
                readline.write_history_file(self._history_file)
                os.chmod(self._history_file, 0o600)
            except OSError:
                pass

    # ──────────────────────────────────────────
    #  Prompt
    # ──────────────────────────────────────────

    def _badge(self) -> str:
        threats = self.se.unseen_count(self._threats_seen_at, "HIGH") if self.se else 0
        alerts = max(0, len(self.sm.get_alerts()) - self._alerts_seen) if self.sm else 0
        n = threats + alerts
        return f" {C.err(f'⚠{n}')}" if n else ""

    def _prompt(self) -> Optional[str]:
        ts = time.strftime("%H:%M")
        prompt = (f"\n{C.GREY}  {ts}{C.RESET} {C.CYAN}{C.BOLD}PRIMERS{C.RESET}"
                  f"{self._badge()}{C.GREY} ›{C.RESET} ")
        raw = input(prompt).strip()
        return raw or None

    def _confirm(self, question: str, cmd: Optional[ParsedCommand]) -> bool:
        if cmd is not None and cmd.flags.get("yes"):
            return True
        if not self.interactive:
            print(C.warn(f"  {question} — re-run with --yes to confirm."))
            return False
        try:
            answer = input(f"\n  {question} [y/N] ").strip().lower()
        except EOFError:
            return False
        return answer in ("y", "yes")

    # ──────────────────────────────────────────
    #  Dispatcher
    # ──────────────────────────────────────────

    def _dispatch(self, cmd: ParsedCommand):
        if cmd.action in self._plugin_handlers:
            self._call_plugin(self._plugin_handlers[cmd.action], cmd)
            return
        handler = getattr(self, f"_cmd_{cmd.action}", None) or self._cmd_unknown
        handler(cmd)

    # ──────────────────────────────────────────
    #  Process commands
    # ──────────────────────────────────────────

    def _cmd_list_processes(self, cmd: ParsedCommand):
        sort_by = cmd.flags.get("sort", "cpu").lower()
        sort_by = {"mem": "memory", "ram": "memory"}.get(sort_by, sort_by)
        if sort_by not in ("cpu", "memory", "pid", "name"):
            print(C.err("  ✗ --sort must be one of: cpu, memory, pid, name"))
            return
        limit = max(1, min(_int(cmd.flags.get("limit"), 20), 500))
        procs = self.pm.list_processes(sort_by=sort_by, limit=limit)

        print(f"\n{divider()}")
        print(f"  {C.hi('PROCESSES')}  {C.dim(f'(sorted by {sort_by}, top {limit})')}")
        print(divider())
        print(C.dim(f"  {'PID':>7}  {'NAME':<22}  {'STATUS':<10}  {'CPU%':>6}  {'MEM%':>6}  COMMAND"))
        print(divider())
        for p in procs:
            cpu_str = f"{p.cpu:>5.1f}%"
            cpu_col = C.err(cpu_str) if p.cpu > 80 else C.warn(cpu_str) if p.cpu > 40 else C.ok(cpu_str)
            status = f"{p.status:<10}"
            status_col = C.ok(status) if p.status == "running" else C.dim(status)
            preview = " ".join(p.cmdline[:2])[:30] if p.cmdline else ""
            print(f"  {p.pid:>7}  {p.name[:22]:<22}  {status_col}  {cpu_col}  {p.memory:>5.1f}%  {C.dim(preview)}")
        print(divider())
        print(f"  {C.dim(f'Total: {len(procs)} shown · Use --sort=memory or --limit=50')}\n")

    def _pid_arg(self, cmd: ParsedCommand, usage: str) -> Optional[int]:
        if not cmd.args:
            print(C.err(f"  ✗ Usage: {usage}"))
            return None
        try:
            return int(cmd.args[0])
        except ValueError:
            print(C.err(f"  ✗ Invalid PID: {cmd.args[0]}"))
            return None

    def _cmd_kill_process(self, cmd: ParsedCommand):
        pid = self._pid_arg(cmd, "kill <PID> [--force] [--yes]")
        if pid is None:
            return
        if self.pm.is_protected(pid):
            print(C.err(f"  ✗ PID {pid} is protected (init or PRIMERS itself)."))
            return
        proc = self.pm.get_process(pid)
        if not proc:
            print(C.err(f"  ✗ No process with PID {pid}"))
            return
        force = "force" in cmd.flags
        if not self._confirm(f"{C.warn('Terminate')} {C.hi(proc.name)} (PID {pid})?", cmd):
            print(C.dim("  Aborted."))
            return
        if self.pm.terminate(pid, force=force):
            print(C.ok(f"  ✓ Process {pid} ({proc.name}) {'killed' if force else 'terminated'}."))
        else:
            print(C.err(f"  ✗ Failed to terminate PID {pid}. (Permission denied?)"))

    def _cmd_launch(self, cmd: ParsedCommand):
        command = cmd.rest if cmd.confidence == 1.0 else " ".join(cmd.args)
        command = command.strip()
        if not command:
            print(C.err("  ✗ Usage: launch <command>"))
            return
        print(f"  {C.dim('Launching:')} {C.info(command)}")
        pid = self.pm.launch(command)
        if pid:
            print(C.ok(f"  ✓ Launched as PID {pid}"))
        else:
            print(C.err(f"  ✗ Failed to launch: '{command}'"))

    def _cmd_find_process(self, cmd: ParsedCommand):
        if not cmd.args:
            print(C.err("  ✗ Usage: find <name>"))
            return
        name = cmd.args[-1]
        procs = self.pm.find_by_name(name)
        print(f"\n{divider()}")
        print(f"  {C.hi('SEARCH:')} {C.info(name)}  {C.dim(f'({len(procs)} found)')}")
        print(divider())
        if not procs:
            print(C.warn(f"  No processes matching '{name}'."))
        for p in procs:
            print(f"  PID {C.info(str(p.pid))}  {C.hi(p.name)}  {C.dim(p.status)}  CPU:{p.cpu:.1f}%")
        print(f"\n{divider()}\n")

    def _cmd_suspend_process(self, cmd: ParsedCommand):
        pid = self._pid_arg(cmd, "suspend <PID>")
        if pid is not None:
            ok = self.pm.suspend(pid)
            print(C.ok(f"  ✓ PID {pid} suspended.") if ok else C.err(f"  ✗ Could not suspend PID {pid}."))

    def _cmd_resume_process(self, cmd: ParsedCommand):
        pid = self._pid_arg(cmd, "resume <PID>")
        if pid is not None:
            ok = self.pm.resume(pid)
            print(C.ok(f"  ✓ PID {pid} resumed.") if ok else C.err(f"  ✗ Could not resume PID {pid}."))

    def _cmd_set_priority(self, cmd: ParsedCommand):
        if len(cmd.args) < 2:
            print(C.err("  ✗ Usage: priority <PID> <nice_value>  (nice: -20 to 19)"))
            return
        try:
            pid, nice = int(cmd.args[0]), int(cmd.args[1])
        except ValueError:
            print(C.err("  ✗ PID and nice value must be integers."))
            return
        if not -20 <= nice <= 19:
            print(C.err("  ✗ Nice value must be between -20 and 19."))
            return
        ok = self.pm.set_priority(pid, nice)
        print(C.ok(f"  ✓ PID {pid} nice set to {nice}.") if ok
              else C.err("  ✗ Could not set priority (root required for values < 0)."))

    # ──────────────────────────────────────────
    #  System / security commands
    # ──────────────────────────────────────────

    def _cmd_system_status(self, cmd: ParsedCommand):
        if not self.sm.get_snapshot():
            self.sm.refresh(interval=0.3)
        summary = self.sm.get_summary()
        alerts = self.sm.get_alerts()
        self._alerts_seen = len(alerts)

        print(f"\n{divider()}")
        print(f"  {C.hi('SYSTEM STATUS')}")
        print(divider())

        def bar(pct, width: int = 20) -> str:
            try:
                value = float(str(pct).replace("%", "").split()[0])
            except (ValueError, IndexError):
                return "?"
            filled = max(0, min(width, int(width * value / 100)))
            col = C.RED if value > 80 else C.YELLOW if value > 60 else C.GREEN
            return f"{col}{'█' * filled}{C.GREY}{'░' * (width - filled)}{C.RESET} {value:.1f}%"

        mem = summary["memory"]
        mem_detail = mem.split("(", 1)[1].rstrip(")") if "(" in mem else ""
        print(f"\n  {'CPU':<10}  {bar(summary['cpu'])}")
        print(f"  {'Memory':<10}  {bar(mem)}  {C.dim(mem_detail)}")
        print(f"  {'Swap':<10}  {bar(summary['swap'])}")
        print(f"\n  {'Processes':<10}  {C.info(str(summary['processes']))}")
        print(f"  {'Net Sent':<10}  {C.dim(summary['net_sent'])}")
        print(f"  {'Net Recv':<10}  {C.dim(summary['net_recv'])}")

        if summary.get("disks"):
            print(f"\n  {C.dim('Disks:')}")
            for mount, info in summary["disks"].items():
                print(f"    {mount[:20]:<20}  {bar(info['percent'])}  {C.dim(info['used'] + ' / ' + info['total'])}")

        if summary.get("top_processes"):
            print(f"\n  {C.dim('Top processes:')}")
            for p in summary["top_processes"]:
                print(f"    {str(p.get('pid', '?')):>7}  {str(p.get('name', '?'))[:20]:<20}  "
                      f"CPU: {p.get('cpu_percent') or 0:.1f}%")

        if alerts:
            print(f"\n  {C.warn('⚠ Alerts:')}")
            for a in alerts[-5:]:
                print(f"    {C.warn('!')} {a['msg']}")
        print(f"\n{divider()}\n")

    def _cmd_security_status(self, cmd: ParsedCommand):
        status = self.se.get_status()
        print(f"\n{divider()}")
        print(f"  {C.hi('SECURITY ENGINE')}")
        print(divider())
        state = C.ok("ACTIVE") if status["active"] else C.warn("ON DEMAND")
        print(f"\n  Status:      {state}")
        print(f"  Events:      {status['total_events']}")
        for level, count in status["by_level"].items():
            col = C.err if level in ("CRITICAL", "HIGH") else C.warn if level == "MEDIUM" else C.dim
            print(f"    {col(f'{level:<10}')}  {count}")
        print(f"\n{divider()}\n")

    def _cmd_list_threats(self, cmd: ParsedCommand):
        level = cmd.flags.get("level", "LOW").upper()
        if not self.se.running:
            self.se.scan_once()
        events = self.se.get_events(min_level=level)
        self._threats_seen_at = time.time()

        print(f"\n{divider()}")
        print(f"  {C.hi('THREAT EVENTS')}  {C.dim(f'(min level: {level})')}")
        print(divider())
        if not events:
            print(C.ok("  ✓ No threat events at this level."))
        for e in events[-30:]:
            ts = time.strftime("%H:%M:%S", time.localtime(e.timestamp))
            col = C.err if e.level in ("CRITICAL", "HIGH") else C.warn if e.level == "MEDIUM" else C.dim
            print(f"  {C.dim(ts)}  {col(f'[{e.level:<8}]')}  {e.description}")
            print(f"  {' ' * 10}  {C.dim('→')} {C.dim(e.recommendation)}\n")
        print(f"{divider()}\n")

    def _cmd_list_alerts(self, cmd: ParsedCommand):
        alerts = self.sm.get_alerts(clear=False)
        self._alerts_seen = len(alerts)
        print(f"\n{divider()}")
        print(f"  {C.hi('SYSTEM ALERTS')}")
        print(divider())
        if not alerts:
            print(C.ok("  ✓ No active alerts."))
        for a in alerts[-30:]:
            ts = time.strftime("%H:%M:%S", time.localtime(a.get("timestamp", time.time())))
            print(f"  {C.dim(ts)}  {C.warn('⚠')} [{a['type']}]  {a['msg']}")
        print(f"\n{divider()}\n")

    def _cmd_datasaver(self, cmd: ParsedCommand):
        from core import network_status
        st = network_status.read_status()
        print(f"\n{divider()}")
        print(f"  {C.hi('DATA SAVER')}")
        print(divider())
        if not st.available:
            print(C.warn("  NetworkManager is not available — can't tell whether this connection is metered."))
            print(f"\n{divider()}\n")
            return
        print(f"\n  Connection:    {C.info(st.connection_text)}  {C.dim('(internet: ' + st.connectivity_text + ')')}")
        print(f"  Metered:       {C.warn(st.metered_text) if st.metered else C.ok(st.metered_text)}")
        if st.background_downloads_paused:
            print(f"  Background:    {C.warn('paused')} — package lists, upgrades and firmware refresh wait for Wi-Fi/Ethernet")
        elif st.metered and st.override:
            print(f"  Background:    {C.warn('allowed on metered')} {C.dim('(override: ' + network_status.OVERRIDE_FILE + ')')}")
        else:
            print(f"  Background:    {C.ok('normal')} — updates download as usual")
        print(f"\n  {C.dim('Browsing data is saved separately by Primers Lite Bee (Lite/Ultra modes).')}")
        if st.metered and not st.override:
            print(C.dim("  Allow updates on metered links: sudo mkdir -p /etc/primers && "
                        "sudo touch " + network_status.OVERRIDE_FILE))
        print(f"\n{divider()}\n")

    def _cmd_lab(self, cmd: ParsedCommand):
        from core import lab_mode
        lab = lab_mode.LabMode()
        st = lab.status()
        print(f"\n{divider()}")
        print(f"  {C.hi('LAB MODE')}")
        print(divider())
        if st["enabled"] is None:
            print(C.err(f"  ✗ Lab Mode settings are damaged: {st['error']}"))
        elif not st["enabled"]:
            print("\n  Lab Mode is off: this computer keeps each person's files.")
            print(C.dim("  For a shared lab PC: sudo primers-lab enable  (a 'lab' account, wiped at sign-out)"))
        else:
            if lab.is_lab_session():
                print(C.warn("\n  ⚠ You are using the shared lab account."))
                print("    Everything you save here is deleted when you sign out.")
                print("    Save your work to a USB stick or online before you leave.")
            else:
                print(f"\n  Lab Mode is {C.ok('on')}: the '{st['user']}' account signs in without a password")
                print("  and is wiped at every sign-in, sign-out and boot.")
            print(f"\n  Fresh home from:  {st['template']}")
            print(f"  Last reset:       {st['last_reset'] or 'never'}")
            if not st["login_hooks"] or not st["account_exists"]:
                print(C.err("  ✗ Lab Mode is not fully set up: run sudo primers-lab enable again."))
            elif not st.get("sign_in_ready"):
                print(C.warn("  Restart the computer to finish: the lab account can sign in after that."))
        print(f"\n{divider()}\n")

    def _cmd_benchmark(self, cmd: ParsedCommand):
        from core import benchmark
        from utils.paths import data_dir
        report = benchmark.collect()
        if cmd.flags.get("json"):
            print(json.dumps(dict(report, results=[dict(zip(("check", "measured", "target", "result"), r))
                                                   for r in benchmark.evaluate(report)]), indent=2))
            return
        hw = report["hardware"]
        print(f"\n{divider()}")
        print(f"  {C.hi('BENCHMARK')}  {C.dim(report['os'] + ' · kernel ' + report['kernel'])}")
        print(divider())
        print(f"  {C.dim('Machine:')}  {' '.join(x for x in (hw.get('vendor'), hw.get('model')) if x) or 'unknown'}")
        print(f"  {C.dim('CPU:')}      {hw['cpu']} ({hw['cores']} threads)")
        disk = report["disk"]
        kind = {True: "hard disk", False: "SSD"}.get(disk.get("rotational"), "unknown type")
        print(f"  {C.dim('Disk:')}     {kind}")
        boot = report.get("boot", {})
        if boot:
            parts = " + ".join(f"{k} {boot[k]:.1f}s" for k in ("firmware", "loader", "kernel", "initrd", "graphical")
                               if k in boot)
            print(f"  {C.dim('Boot:')}     {parts}")
        print()
        marks = {"pass": C.ok("✓ pass"), "fail": C.err("✗ over"), "n/a": C.dim("–")}
        for check, measured, target, result in benchmark.evaluate(report):
            print(f"  {check:<16} {C.info(f'{measured:>10}')}   {C.dim(f'{target:<34}')} {marks[result]}")
        if report["uptime_s"] < 120:
            print(C.dim("\n  Tip: wait two minutes after boot for a true idle RAM reading."))
        if report["live_session"]:
            print(C.dim("  Live USB session: boot and disk figures only mean something once installed."))
        path = benchmark.save(report, os.path.join(data_dir(), "benchmarks"))
        print(f"\n  {C.dim('Saved:')} {path}")
        print(C.dim("  The report has hardware facts and timings only: no names, files or addresses."))
        print(f"\n{divider()}\n")

    def _cmd_study_start(self, cmd: ParsedCommand):
        self._cmd_study(ParsedCommand(action="study", args=["start"], flags={}, raw=cmd.raw))

    def _cmd_study(self, cmd: ParsedCommand):
        from core import study_mode
        arg = (cmd.args[0].lower() if cmd.args else "")
        if arg == "start":
            arg = cmd.args[1] if len(cmd.args) > 1 else str(study_mode.DEFAULT_MINUTES)
        if arg in ("stop", "end", "quit", "finish", "off"):
            session = study_mode.stop()
            print(C.ok("  ✓ Study Mode ended. Paused sites are open again.") if session
                  else C.dim("  Study Mode is not running."))
            return
        if arg.isdigit():
            try:
                session = study_mode.start(int(arg))
            except ValueError as e:
                print(C.err(f"  ✗ {e}"))
                return
            try:
                import primers_study
                primers_study.spawn_end_notice()
            except Exception:
                self.logger.exception("could not start the Study Mode end notice")
            end = time.strftime("%H:%M", time.localtime(session.until))
            print(C.ok(f"  ✓ Study Mode on for {session.minutes} min (until {end})."))
            print(C.dim("    Primers Lite Bee pauses social media, video, games and betting sites;"))
            print(C.dim("    the panel shows the time left. End early with: study stop"))
            return
        if arg:
            print(C.err(f"  ✗ Unknown option '{arg}'. Try: study 25 · study stop · study"))
            return
        session = study_mode.current()
        if session:
            print(f"  {C.hi('STUDY MODE')}  {C.ok(study_mode.format_left(session.remaining()) + ' left')}"
                  f" {C.dim('of ' + str(session.minutes) + ' min')}")
        else:
            print(f"  {C.hi('STUDY MODE')}  {C.dim('off')}  "
                  f"Start a focus session: {C.accent('study 25')} (minutes)")

    def _cmd_list_connections(self, cmd: ParsedCommand):
        conns = self.se.scan_connections()
        print(f"\n{divider()}")
        print(f"  {C.hi('NETWORK CONNECTIONS')}  {C.dim(f'({len(conns)} total)')}")
        print(divider())
        print(C.dim(f"  {'PID':>7}  {'NAME':<20}  {'STATUS':<12}  {'LOCAL':<22}  REMOTE"))
        print(divider())
        for c in conns[:40]:
            status = f"{c['status']:<12}"
            status_col = C.ok(status) if c["status"] == "ESTABLISHED" else C.dim(status)
            print(f"  {str(c['pid'] or '-'):>7}  {(c['name'] or '-')[:20]:<20}  {status_col}  "
                  f"{c['local']:<22}  {C.dim(c['remote'])}")
        if len(conns) > 40:
            print(C.dim(f"  ... {len(conns) - 40} more connections"))
        print(f"\n{divider()}\n")

    def _cmd_math(self, cmd: ParsedCommand):
        expr = cmd.rest if cmd.confidence == 1.0 else " ".join(cmd.args)
        expr = expr.strip()
        if not expr:
            print(C.err("  ✗ Usage: math <expression>   e.g. math sqrt(144) + pi"))
            return
        result = self.math.evaluate(expr)
        formatted = self.math.format_result(result)
        out = C.err(formatted) if isinstance(result, str) else C.accent(formatted)
        print(f"\n  {C.dim(expr)}  {out}\n")

    # ──────────────────────────────────────────
    #  Intelligence
    # ──────────────────────────────────────────

    def _cmd_advise(self, cmd: ParsedCommand):
        if not self.de:
            print(C.err("  ✗ Decision engine not available."))
            return
        if not self.sm.get_snapshot():
            self.sm.refresh(interval=0.3)
        if not self.se.running:
            self.se.scan_once()
        recs = self.de.analyse()
        print(f"\n{divider()}")
        print(f"  {C.hi('PRIMERS ADVICE')}")
        print(divider())
        if not recs:
            print(C.ok("  ✓ All clear — nothing needs your attention right now."))
        for r in recs[:10]:
            col = C.err if r.severity == "CRITICAL" else C.warn if r.severity in ("WARNING", "MEDIUM") else C.dim
            print(f"\n  {col(f'[{r.severity}]')} {r.reason}")
            print(f"    {C.dim('Suggested:')} {C.info(r.action)}  {C.dim(f'(confidence {r.confidence:.0%})')}")
            if r.explanation:
                print(f"    {C.dim(r.explanation.strip())}")
        if self.le:
            nxt = self.le.suggest(self._recent[-3:] or None)
            print(f"\n  {C.dim('You might want next:')} {', '.join(C.accent(s) for s in nxt)}")
        print(f"\n{divider()}\n")

    def _cmd_ask(self, cmd: ParsedCommand):
        question = cmd.rest.strip() if cmd.rest else " ".join(cmd.args)
        if not self.kb:
            print(C.err("  ✗ Knowledge base not available."))
            return
        if not question:
            print(f"\n  {C.hi('ASK PRIMERS')}  {C.dim('— e.g. ask what is Veltis One?')}")
            print(f"  {C.dim('Topics:')} " + ", ".join(t.split(". ", 1)[-1].split(" (")[0] for t in self.kb.topics()[:12]))
            return
        ans = self.kb.answer(question)
        print(f"\n  {C.accent('⚛ Ask Primers')}  {C.dim(question)}")
        print(divider())
        for i, line in enumerate(ans.text.splitlines()):
            if ans.emergency and i < 2:
                print(f"  {C.err(line)}")
            else:
                print(f"  {line}")
        if ans.sources:
            print(f"\n  {C.dim('Source: ' + ans.sources[0])}")
        print()

    def _cmd_browse(self, cmd: ParsedCommand):
        target = cmd.rest.strip() if cmd.confidence == 1.0 else " ".join(cmd.args)
        args = ["lite-bee"] + ([target] if target else [])
        pid = self.pm.launch(" ".join(__import__("shlex").quote(a) for a in args))
        if pid:
            print(C.ok(f"  ✓ Primers Lite Bee opened{(' → ' + target) if target else ''}"))
        else:
            print(C.err("  ✗ Primers Lite Bee is not installed on this system."))

    def _cmd_learn(self, cmd: ParsedCommand):
        if not self.le:
            print(C.err("  ✗ Learning Engine not available."))
            return
        sub = cmd.args[0].lower() if cmd.args else "stats"
        if sub == "stats":
            stats = self.le.get_stats()
            print(f"\n  {C.hi('USAGE STATISTICS')}")
            print(f"  Total commands: {C.info(str(stats['total_commands']))}"
                  f"   Sessions: {C.info(str(stats['session_count']))}")
            if stats["busiest_hour"] is not None:
                busiest = "%02d:00" % stats["busiest_hour"]
                print(f"  Busiest hour:   {C.info(busiest)}")
            if stats["most_used"]:
                print("  Top commands:")
                for item in stats["most_used"]:
                    print(f"    - {item['command']:<12} {item['count']} uses")
            if stats["command_sequences"]:
                print("  Common sequences:")
                for item in stats["command_sequences"]:
                    print(f"    - {item['sequence']:<20} {item['count']}×")
            if not stats["total_commands"]:
                print(C.dim("  No history yet — PRIMERS learns as you use it."))
        elif sub == "suggest":
            suggestions = self.le.suggest(self._recent[-3:] or None)
            print(f"\n  {C.hi('AI SUGGESTIONS')}")
            for i, s in enumerate(suggestions, 1):
                print(f"    {i}. {C.accent(s)}")
        elif sub in ("clear", "forget"):
            if self._confirm("Delete all learned command history?", cmd):
                self.le.clear()
                print(C.ok("  ✓ Usage history cleared."))
        else:
            print(C.err(f"  ✗ Unknown learn subcommand: {sub}  (stats | suggest | clear)"))

    def _cmd_task(self, cmd: ParsedCommand):
        if not self.ae:
            print(C.err("  ✗ Automation Engine not available."))
            return
        sub = cmd.args[0].lower() if cmd.args else "list"
        args = cmd.args

        if sub == "add":
            if len(args) < 5 or args[2] not in ("interval", "time"):
                print(C.err("  ✗ Usage: task add <name> interval <seconds> <command>"))
                print(C.err("          task add <name> time <HH:MM> <command>"))
                return
            name, ttype, val = args[1], args[2], args[3]
            # keep the command exactly as typed (quotes, pipes…)
            parts = cmd.rest.split(None, 4)
            command = parts[4] if len(parts) == 5 else " ".join(args[4:])
            res = self.ae.add_task(name, command, ttype,
                                   interval_seconds=val if ttype == "interval" else None,
                                   run_at_time=val if ttype == "time" else None)
            if res["ok"]:
                print(C.ok(f"  ✓ Task '{name}' scheduled (ID: {res['id']})."))
                if not self.ae.running:
                    print(C.dim("    It runs while the PRIMERS shell is open."))
            else:
                print(C.err(f"  ✗ {res['error']}"))
        elif sub == "list":
            tasks = self.ae.list_tasks()
            print(f"\n  {C.hi('SCHEDULED TASKS')}")
            if not tasks:
                print(C.dim("  No tasks. Add one: task add backup interval 3600 \"tar czf ~/b.tgz ~/Documents\""))
            for t in tasks:
                state = C.ok("ON ") if t.get("enabled", True) else C.dim("OFF")
                sched = f"every {t['interval_seconds']}s" if t["schedule_type"] == "interval" else f"at {t['run_at_time']}"
                print(f"  {C.info(t['id'])} [{state}] {C.hi(t['name'][:15]):<15} {sched:<14} {C.dim(t['command'])}")
        elif sub in ("remove", "run", "enable", "disable"):
            if len(args) < 2:
                print(C.err(f"  ✗ Usage: task {sub} <id>"))
                return
            task_id = args[1]
            if sub == "remove":
                res = self.ae.remove_task(task_id)
                print(C.ok(f"  ✓ Task '{task_id}' removed.") if res["ok"] else C.err(f"  ✗ {res['error']}"))
            elif sub == "run":
                print(C.dim(f"  Executing task '{task_id}' now..."))
                res = self.ae.run_now(task_id)
                if res["ok"]:
                    print(C.ok(f"  ✓ Finished (exit code {res['returncode']})"))
                    if res["output"]:
                        print(f"  {C.dim(res['output'])}")
                else:
                    print(C.err(f"  ✗ {res['error']}"))
            else:
                fn = self.ae.enable_task if sub == "enable" else self.ae.disable_task
                res = fn(task_id)
                print(C.ok(f"  ✓ Task {task_id} {sub}d.") if res["ok"] else C.err(f"  ✗ {res['error']}"))
        elif sub == "history":
            history = self.ae.get_history(args[1] if len(args) > 1 else None)
            print(f"\n  {C.hi('TASK EXECUTION HISTORY')}")
            if not history:
                print(C.dim("  No task runs yet."))
            for h in history:
                ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(h["timestamp"]))
                res = C.ok("OK  ") if h["returncode"] == 0 else C.err(f"FAIL({h['returncode']})")
                print(f"  {C.dim(ts)} | {h['task_id']:<10} | {res}")
        else:
            print(C.err(f"  ✗ Unknown task subcommand: {sub}  (add | list | remove | run | enable | disable | history)"))

    def _cmd_cyber(self, cmd: ParsedCommand):
        if not self.cyber:
            print(C.err("  ✗ Cyber Intelligence module not available."))
            return
        sub = cmd.args[0].lower() if cmd.args else "report"
        if sub == "scan":
            rng = (1, 1024)
            if len(cmd.args) > 1 and "-" in cmd.args[1]:
                lo, _, hi = cmd.args[1].partition("-")
                rng = (_int(lo, 1), _int(hi, 1024))
            print(C.dim(f"  Running defensive localhost port scan ({rng[0]}-{rng[1]})..."))
            try:
                found = self.cyber.scan_ports(port_range=rng)
            except ValueError as e:
                print(C.err(f"  ✗ {e}"))
                return
            print(C.ok(f"  ✓ Port scan complete — {len(found)} open port(s). Type 'cyber report'."))
        elif sub == "report":
            report = self.cyber.get_report()
            level_col = C.err if report["risk_score"] > 50 else C.warn if report["risk_score"] > 25 else C.ok
            print(f"\n  {C.hi('CYBER INTELLIGENCE REPORT')}")
            print(f"  Risk Level: {level_col(report['risk_level'])}")
            print(f"  Risk Score: {C.accent(str(report['risk_score']))}/100")
            print(f"  Hostname:   {report['hostname']}")
            print(divider())
            if not report["open_ports"]:
                print(C.ok("  ✓ No open ports found in the scanned range."))
            for f in report["open_ports"]:
                col = C.err if f["risk"] == "HIGH" else C.warn if f["risk"] == "MEDIUM" else C.ok
                exposure = f.get("exposure", "unknown")
                exp_col = C.warn if exposure == "network" else C.dim
                proc = f.get("process") or ""
                print(f"  PORT {str(f['port']):<6} {f['service']:<12} {col(f['risk']):<6}  {exp_col(exposure):<8}  {C.dim(proc)}")
            if report["recommendations"]:
                print(f"\n  {C.hi('RECOMMENDATIONS:')}")
                for rec in report["recommendations"]:
                    print(f"    - {rec}")
        elif sub == "score":
            print(f"\n  Defensive Risk Score: {C.accent(str(self.cyber.get_risk_score()))}/100")
        else:
            print(C.err(f"  ✗ Unknown cyber subcommand: {sub}  (scan [from-to] | report | score)"))

    def _cmd_kernel(self, cmd: ParsedCommand):
        if not self.kernel:
            print(C.err("  ✗ Kernel Interface not available."))
            return
        sub = cmd.args[0].lower() if cmd.args else "info"
        if sub == "info":
            info = self.kernel.get_all()
            cpu, mem = info["cpu"], info["memory"]
            print(f"\n  {C.hi('KERNEL INTERFACE — SYSTEM INFO')}")
            print(f"  Kernel:  {C.info(info['kernel'][:100])}")
            print(f"  CPU:     {C.hi(cpu['model'])} ({cpu['cores']} threads @ {cpu['mhz']} MHz)")
            print(f"  Memory:  {mem['MemAvailable']} / {mem['MemTotal']} MB available")
            print(f"  Swap:    {mem['SwapFree']} / {mem['SwapTotal']} MB free")
            print(f"  Uptime:  {C.ok(info['uptime']['formatted'])}")
        elif sub == "load":
            load = self.kernel.get_load()
            print(f"\n  {C.hi('SYSTEM LOAD')}")
            print(f"  Load 1m:  {C.accent(str(load['load_1min']))}")
            print(f"  Load 5m:  {C.accent(str(load['load_5min']))}")
            print(f"  Load 15m: {C.accent(str(load['load_15min']))}")
            print(f"  Procs:    {load['running_processes']}/{load['total_processes']} running")
        elif sub == "uptime":
            print(f"\n  System Uptime: {C.ok(self.kernel.get_uptime()['formatted'])}")
        elif sub in ("net", "network"):
            ifaces = self.kernel.get_net_stats()["interfaces"]
            print(f"\n  {C.hi('NETWORK INTERFACES')}")
            for name, st in ifaces.items():
                print(f"  {name:<12} rx {SystemMonitor._fmt_bytes(st['bytes_recv']):>10}   "
                      f"tx {SystemMonitor._fmt_bytes(st['bytes_sent']):>10}")
        else:
            print(C.err(f"  ✗ Unknown kernel subcommand: {sub}  (info | load | uptime | net)"))

    # ──────────────────────────────────────────
    #  Services
    # ──────────────────────────────────────────

    def _cmd_gpa(self, cmd: ParsedCommand):
        if not self.gpa:
            print(C.err("  ✗ GPA Service not available."))
            return
        sub = cmd.args[0].lower() if cmd.args else "report"
        if sub == "add":
            if len(cmd.args) < 5:
                print(C.err("  ✗ Usage: gpa add <name> <credits> <grade> <semester>"))
                print(C.dim('    e.g. gpa add "Linear Algebra" 3 A- 2025-Fall'))
                return
            name, credits, grade, semester = cmd.args[1], cmd.args[2], cmd.args[3], cmd.args[4]
            res = self.gpa.add_course(name, credits, grade, semester)
            print(C.ok(f"  ✓ Added course: {name} ({semester})") if res["ok"] else C.err(f"  ✗ {res['error']}"))
        elif sub == "remove":
            if len(cmd.args) < 3:
                print(C.err("  ✗ Usage: gpa remove <name> <semester>"))
                return
            res = self.gpa.remove_course(cmd.args[1], cmd.args[2])
            print(C.ok(f"  ✓ Removed course: {cmd.args[1]} from {cmd.args[2]}") if res["ok"]
                  else C.warn(f"  ✗ Course not found: {cmd.args[1]} in {cmd.args[2]}"))
        elif sub == "clear":
            if self._confirm(C.warn("Clear ALL GPA data?"), cmd):
                self.gpa.clear()
                print(C.ok("  ✓ All courses cleared."))
        elif sub == "report":
            report = self.gpa.get_report()
            cgpa = "%.2f" % report["cgpa"]
            print(f"\n{divider()}")
            print(f"  {C.hi('ACADEMIC REPORT')}")
            print(divider())
            print(f"  CGPA: {C.accent(cgpa)} | Total Credits: {C.info(str(report['total_credits']))}")
            print(f"  Course Count: {report['course_count']}")
            print(f"  Highest GPA: {C.ok(report['highest_gpa_semester'])} | "
                  f"Lowest GPA: {C.err(report['lowest_gpa_semester'])}")
            for sem, data in report["semesters"].items():
                sem_gpa = "%.2f" % data["gpa"]
                print(f"\n  {C.hi('Semester: ' + str(sem))}  (GPA: {sem_gpa})")
                for c in data["courses"]:
                    print(f"    - {c['name'][:24]:<24} | {c['credit_hours']:g} hrs | {C.info(c['grade'])}")
            if not report["course_count"]:
                print(C.dim('\n  No courses yet. Add one: gpa add "Calculus I" 3 A 2025-Fall'))
            print(f"\n{divider()}")
        else:
            print(C.err(f"  ✗ Unknown GPA subcommand: {sub}  (add | remove | report | clear)"))

    def _cmd_graph(self, cmd: ParsedCommand):
        if not self.graph:
            print(C.err("  ✗ Graph AI not available."))
            return
        sub = cmd.args[0].lower() if cmd.args else "show"
        if sub in ("show", "anomalies", "export", "stats") and not self.graph._graph["nodes"]:
            self.graph.scan()
        if sub == "scan":
            print(C.dim("  Scanning network topology..."))
            self.graph.scan()
            st = self.graph.get_stats()
            print(C.ok(f"  ✓ Network scan complete — {st['node_count']} nodes, {st['edge_count']} connections."))
        elif sub == "show":
            print(C.info(self.graph.render_ascii()))
        elif sub == "anomalies":
            anomalies = self.graph.detect_anomalies()
            if not anomalies:
                print(C.ok("  ✓ No network anomalies detected."))
            else:
                print(C.warn(f"  ⚠ {len(anomalies)} anomaly(s) detected:"))
                for a in anomalies:
                    print(f"    - {C.err(a['type'])}: {a['detail']} ({C.dim(a['severity'])})")
        elif sub == "export":
            print(self.graph.export_json())
        elif sub == "stats":
            st = self.graph.get_stats()
            print(f"\n  Nodes: {st['node_count']}  Edges: {st['edge_count']}  Anomalies: {st['anomaly_count']}")
            for ip in st["top_remote_ips"]:
                print(f"    - {ip}")
        else:
            print(C.err(f"  ✗ Unknown graph subcommand: {sub}  (scan | show | anomalies | stats | export)"))

    def _cmd_modules(self, cmd: ParsedCommand):
        registry = self.settings.MODULES_REGISTRY
        if not os.path.exists(registry):
            print(C.warn(f"  Module registry not found ({registry}) — modules are available on PRIMERS OS installs."))
            return
        with open(registry, encoding="utf-8") as f:
            modules = json.load(f).get("modules", [])
        if len(cmd.args) >= 2 and cmd.args[0] == "install":
            name = cmd.args[1]
            if not any(m["name"] == name for m in modules):
                print(C.err(f"  ✗ Unknown module: {name}"))
                return
            if not self.interactive:
                print(C.warn(f"  Run: {self.settings.PRIMERS_INSTALL_CMD} {name}"))
                return
            subprocess.call([self.settings.PRIMERS_INSTALL_CMD, name])
            return
        print(f"\n  {C.hi('SOFTWARE MODULES')}  {C.dim('install with: modules install <name>')}")
        for m in modules:
            warn = C.warn(" ⚠") if m.get("warning") else ""
            print(f"    {C.info(m['name']):<16} {m['description'][:52]}  {C.dim(str(m.get('size_mb', '?')) + 'MB')}{warn}")

    def _cmd_plugins(self, cmd: ParsedCommand):
        print(f"\n  {C.hi('PLUGINS')}  {C.dim('user plugins: ' + paths.user_plugin_dir())}")
        if not self.plugins:
            print(C.dim("  No plugins loaded."))
        for p in self.plugins:
            cmds = ", ".join(p.get("commands", {}).keys()) or "-"
            print(f"    {C.info(p['name'])}  {C.dim(p.get('desc', ''))}  [{cmds}]")

    # ──────────────────────────────────────────
    #  Interfaces
    # ──────────────────────────────────────────

    def _cmd_gui(self, cmd: ParsedCommand):
        sub = cmd.args[0].lower() if cmd.args else "status"
        url = self.settings.gui_url
        if sub == "start":
            if self.gui_active:
                print(C.warn(f"  GUI Dashboard is already running at {url}"))
                return
            try:
                from interface.gui.dashboard import start_gui
                self.dashboard = start_gui(self.sm, self.pm, self.se, self.kernel, self.gpa, self.settings)
            except (RuntimeError, OSError) as e:
                print(C.err(f"  ✗ Could not start the dashboard: {e}"))
                return
            if not self.sm.running:
                self.sm.start()
            print(C.ok(f"  ✓ GUI Dashboard started at {url}"))
        elif sub == "stop":
            if not self.gui_active:
                print(C.warn("  GUI Dashboard is not running."))
                return
            self.dashboard.stop()
            print(C.ok("  ✓ GUI Dashboard stopped."))
        elif sub == "open":
            if not self.gui_active:
                self._cmd_gui(ParsedCommand("gui", ["start"], {}, "gui start"))
            if self.gui_active:
                self.pm.launch(f"xdg-open {url}")
        else:
            state = C.ok("RUNNING") if self.gui_active else C.dim("OFFLINE")
            print(f"\n  GUI Dashboard Status: {state}")
            if self.gui_active:
                print(f"  URL: {C.info(url)}")
            else:
                print(C.dim("  Start it with: gui start   (or 'gui open' to open the browser)"))

    def _cmd_voice(self, cmd: ParsedCommand):
        sub = cmd.args[0].lower() if cmd.args else "status"
        if not self.voice:
            print(C.err("  ✗ Voice Engine not available."))
            return
        if sub == "start":
            reason = self.voice.availability()
            if reason:
                print(C.err(f"  ✗ Voice unavailable: {reason}"))
                return
            if self.voice.start_listening():
                print(C.ok("  ✓ Voice engine on. Say \"primers <command>\" — e.g. \"primers system status\"."))
                print(C.warn("    Speech is sent to Google's speech service for transcription while voice is on."))
        elif sub == "stop":
            self.voice.stop_listening()
            print(C.warn("  ✓ Voice engine deactivated."))
        else:
            state = C.ok("LISTENING") if self.voice.is_active() else C.dim("OFFLINE")
            print(f"\n  Voice Engine Status: {state}")
            reason = self.voice.availability()
            if reason:
                print(C.dim(f"  {reason}"))

    # ──────────────────────────────────────────
    #  General
    # ──────────────────────────────────────────

    def _cmd_help(self, cmd: ParsedCommand):
        print(self.ci.get_help_text())

    def _cmd_clear(self, cmd: ParsedCommand):
        if sys.stdout.isatty():
            print("\033[2J\033[H", end="", flush=True)

    def _cmd_version(self, cmd: ParsedCommand):
        print(f"\n  {C.hi('PRIMERS OS')}  {C.accent('v' + self.settings.VERSION)}  {C.dim(self.settings.OS_EDITION)}")
        print(f"  {C.dim('Python ' + sys.version.split()[0] + ' · data: ' + paths.data_dir())}\n")

    def _cmd_exit(self, cmd):
        print(f"\n  {C.dim('PRIMERS OS shutting down...')}\n")
        self._running = False

    def _cmd_unknown(self, cmd: ParsedCommand):
        raw = cmd.raw if cmd else "?"
        print(f"\n  {C.err('✗ Unknown command:')} {C.hi(raw)}")
        if cmd and cmd.suggestions:
            print(f"  {C.dim('Did you mean:')} {', '.join(C.info(s) for s in cmd.suggestions)}?")
        print(f"  {C.dim('Type')} {C.info('help')} {C.dim('to see available commands.')}\n")

    # ──────────────────────────────────────────
    #  Boot summary
    # ──────────────────────────────────────────

    def _show_lab_notice(self):
        try:
            from core import lab_mode
            if lab_mode.LabMode().is_lab_session():
                print(C.warn("\n  ⚠ Shared lab account: your files are deleted when you sign out. "
                             "Save to USB or online."))
        except Exception:
            pass

    def _show_boot_summary(self):
        def state(component, on="Online", off="On demand"):
            return C.ok(on) if component is not None and getattr(component, "running", True) else C.warn(off)

        print(f"  {C.dim('Version:')}      {C.info(self.settings.VERSION)}")
        print(f"  {C.dim('Monitor:')}      {state(self.sm)}")
        print(f"  {C.dim('Security:')}     {state(self.se)}")
        print(f"  {C.dim('Automation:')}   {state(self.ae)}")
        print(f"  {C.dim('AI Engine:')}    {C.ok('Online') if self.de else C.warn('Offline')}")
        print(f"  {C.dim('Services:')}     {C.ok('math, gpa, graph, cyber')}")
        if self.plugins:
            print(f"  {C.dim('Plugins:')}      {C.ok(str(len(self.plugins)) + ' loaded')}")
        if self.le:
            print(f"  {C.dim('Try:')}          {', '.join(C.accent(s) for s in self.le.suggest())}")

    # ──────────────────────────────────────────
    #  Readline
    # ──────────────────────────────────────────

    def _setup_readline(self):
        if readline is None:
            return
        try:
            readline.set_history_length(1000)
            if os.path.exists(self._history_file):
                readline.read_history_file(self._history_file)

            def completer(text, state):
                options = [c for c in self.ci.command_words() if c.startswith(text.lower())]
                return options[state] if state < len(options) else None

            readline.set_completer(completer)
            readline.parse_and_bind("tab: complete")
        except (OSError, AttributeError):
            pass
