"""
PRIMERS OS — CLI Shell (Phase 1 Interface)
Primary human-computer interaction layer.
"""

import os
import sys
import time
try:
    import readline
except ImportError:
    # Windows doesn't have readline by default
    readline = None
from typing import Optional

from ai.command_interpreter.interpreter import CommandInterpreter, ParsedCommand
from core.system_monitor.monitor import SystemMonitor
from core.process_manager.manager import ProcessManager
from core.security_engine.engine import SecurityEngine
from services.math_engine.engine import MathEngine
from configs.settings import Settings
from utils.logger import PrimersLogger


# ─────────────────────────────────────────────
#  ANSI colour helpers
# ─────────────────────────────────────────────
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    # Palette
    CYAN    = "\033[96m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    RED     = "\033[91m"
    MAGENTA = "\033[95m"
    BLUE    = "\033[94m"
    WHITE   = "\033[97m"
    GREY    = "\033[90m"

    @classmethod
    def ok(cls, s):    return f"{cls.GREEN}{s}{cls.RESET}"
    @classmethod
    def warn(cls, s):  return f"{cls.YELLOW}{s}{cls.RESET}"
    @classmethod
    def err(cls, s):   return f"{cls.RED}{s}{cls.RESET}"
    @classmethod
    def info(cls, s):  return f"{cls.CYAN}{s}{cls.RESET}"
    @classmethod
    def dim(cls, s):   return f"{cls.GREY}{s}{cls.RESET}"
    @classmethod
    def hi(cls, s):    return f"{cls.BOLD}{cls.WHITE}{s}{cls.RESET}"
    @classmethod
    def accent(cls, s):return f"{cls.MAGENTA}{s}{cls.RESET}"


BANNER = f"""
{C.CYAN}{C.BOLD}
  ██████╗ ██████╗ ██╗███╗   ███╗███████╗██████╗ ███████╗     ██████╗ ███████╗
  ██╔══██╗██╔══██╗██║████╗ ████║██╔════╝██╔══██╗██╔════╝    ██╔═══██╗██╔════╝
  ██████╔╝██████╔╝██║██╔████╔██║█████╗  ██████╔╝███████╗    ██║   ██║███████╗
  ██╔═══╝ ██╔══██╗██║██║╚██╔╝██║██╔══╝  ██╔══██╗╚════██║    ██║   ██║╚════██║
  ██║     ██║  ██║██║██║ ╚═╝ ██║███████╗██║  ██║███████║    ╚██████╔╝███████║
  ╚═╝     ╚═╝  ╚═╝╚═╝╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝     ╚═════╝ ╚══════╝
{C.RESET}{C.GREY}  AI-Native Modular OS Platform  ·  Phase 1  ·  Type 'help' to begin
{C.RESET}"""

DIVIDER = C.dim("  " + "─" * 60)


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
        graph_ai=None
    ):
        self.logger = PrimersLogger.get_logger("cli")
        self.ci = command_interpreter
        self.command_interpreter = command_interpreter # Alias for plugin compatibility
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
        
        self.math = MathEngine()
        self._running = True
        self._history_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs", ".cli_history")
        
        self.voice = None # Set by main.py
        self.gui_active = False

        self._setup_readline()

    # ──────────────────────────────────────────
    #  Entrypoint
    # ──────────────────────────────────────────

    def run(self):
        print(BANNER)
        self._show_boot_summary()
        print()

        while self._running:
            try:
                raw = self._prompt()
                if raw is None:
                    continue
                
                # Log command to learning engine
                if self.le:
                    self.le.log_command(raw, "cli_input", raw.split())

                parsed = self.ci.parse(raw)
                if parsed:
                    self._dispatch(parsed)
            except KeyboardInterrupt:
                print(f"\n{C.dim('  (Use exit or quit to leave PRIMERS OS)')}")
            except EOFError:
                self._cmd_exit(None)

        try:
            readline.write_history_file(self._history_file)
        except Exception:
            pass

    # ──────────────────────────────────────────
    #  Prompt
    # ──────────────────────────────────────────

    def _prompt(self) -> Optional[str]:
        try:
            ts = time.strftime("%H:%M")
            prompt = (
                f"\n{C.GREY}  {ts}{C.RESET} "
                f"{C.CYAN}{C.BOLD}PRIMERS{C.RESET}"
                f"{C.GREY} ›{C.RESET} "
            )
            raw = input(prompt).strip()
            if raw:
                return raw
            return None
        except (EOFError, KeyboardInterrupt):
            raise

    # ──────────────────────────────────────────
    #  Dispatcher
    # ──────────────────────────────────────────

    def _dispatch(self, cmd: ParsedCommand):
        action = cmd.action
        dispatch_map = {
            "list_processes":  self._cmd_list_processes,
            "kill_process":    self._cmd_kill_process,
            "launch":          self._cmd_launch,
            "system_status":   self._cmd_system_status,
            "security_status": self._cmd_security_status,
            "list_threats":    self._cmd_list_threats,
            "list_alerts":     self._cmd_list_alerts,
            "list_connections":self._cmd_list_connections,
            "find_process":    self._cmd_find_process,
            "suspend_process": self._cmd_suspend,
            "resume_process":  self._cmd_resume,
            "set_priority":    self._cmd_set_priority,
            "math":            self._cmd_math,
            "help":            self._cmd_help,
            "clear":           self._cmd_clear,
            "version":         self._cmd_version,
            "exit":            self._cmd_exit,
            "gpa":             self._cmd_gpa,
            "graph":           self._cmd_graph,
            "learn":           self._cmd_learn,
            "task":            self._cmd_task,
            "cyber":           self._cmd_cyber,
            "kernel":          self._cmd_kernel,
            "gui":             self._cmd_gui,
            "voice":           self._cmd_voice,
            "unknown":         self._cmd_unknown,
        }
        
        # Check for plugin commands
        if action.startswith("plugin_"):
            print(f"\n  {C.accent('⚛')} {C.hi('PLUGIN COMMAND:')} {action}")
            if action == "plugin_hello":
                from services.sample_plugin.plugin import plugin_hello
                print(f"  {plugin_hello()}")
                return

        handler = dispatch_map.get(action, self._cmd_unknown)
        handler(cmd)

    # ──────────────────────────────────────────
    #  Command Handlers
    # ──────────────────────────────────────────

    def _cmd_list_processes(self, cmd: ParsedCommand):
        sort_by = cmd.flags.get("sort", "cpu")
        limit = int(cmd.flags.get("limit", "20"))
        procs = self.pm.list_processes(sort_by=sort_by, limit=limit)

        print(f"\n{DIVIDER}")
        print(f"  {C.hi('PROCESSES')}  {C.dim(f'(sorted by {sort_by}, top {limit})')}")
        print(DIVIDER)
        header = f"  {'PID':>7}  {'NAME':<22}  {'STATUS':<10}  {'CPU%':>6}  {'MEM%':>6}  COMMAND"
        print(C.dim(header))
        print(DIVIDER)

        for p in procs:
            cpu_str = f"{p.cpu:>5.1f}%"
            mem_str = f"{p.memory:>5.1f}%"
            cpu_col = C.err(cpu_str) if p.cpu > 80 else C.warn(cpu_str) if p.cpu > 40 else C.ok(cpu_str)
            status_col = C.ok(p.status) if p.status == "running" else C.dim(p.status)
            cmd_preview = " ".join(p.cmdline[:2])[:30] if p.cmdline else ""
            print(f"  {p.pid:>7}  {p.name:<22}  {status_col:<10}  {cpu_col}  {mem_str}  {C.dim(cmd_preview)}")

        print(DIVIDER)
        print(f"  {C.dim(f'Total: {len(procs)} shown · Use --sort=memory or --limit=50')}\n")

    def _cmd_kill_process(self, cmd: ParsedCommand):
        if not cmd.args:
            print(C.err("  ✗ Usage: kill <PID> [--force]"))
            return
        try:
            pid = int(cmd.args[0])
        except ValueError:
            print(C.err(f"  ✗ Invalid PID: {cmd.args[0]}"))
            return

        force = "force" in cmd.flags or "--force" in cmd.raw
        proc = self.pm.get_process(pid)
        if not proc:
            print(C.err(f"  ✗ No process with PID {pid}"))
            return

        confirm = input(f"\n  {C.warn(f'Terminate')} {C.hi(proc.name)} (PID {pid})? [y/N] ").strip().lower()
        if confirm != "y":
            print(C.dim("  Aborted."))
            return

        ok = self.pm.terminate(pid, force=force)
        if ok:
            print(C.ok(f"  ✓ Process {pid} ({proc.name}) terminated."))
        else:
            print(C.err(f"  ✗ Failed to terminate PID {pid}. (Permission denied?)"))

    def _cmd_launch(self, cmd: ParsedCommand):
        if not cmd.args:
            print(C.err("  ✗ Usage: launch <command>"))
            return
        command = " ".join(cmd.args)
        print(f"  {C.dim('Launching:')} {C.info(command)}")
        pid = self.pm.launch(command)
        if pid:
            print(C.ok(f"  ✓ Launched as PID {pid}"))
        else:
            print(C.err(f"  ✗ Failed to launch: '{command}'"))

    def _cmd_system_status(self, cmd: ParsedCommand):
        summary = self.sm.get_summary()
        alerts = self.sm.get_alerts()

        print(f"\n{DIVIDER}")
        print(f"  {C.hi('SYSTEM STATUS')}")
        print(DIVIDER)

        if summary.get("status") == "initialising":
            print(C.warn("  Monitor still initialising — try again in a moment."))
            return

        def bar(pct_str: str, width: int = 20) -> str:
            try:
                pct = float(pct_str.replace("%", "").split()[0])
            except Exception:
                return "?"
            filled = int(width * pct / 100)
            col = C.RED if pct > 80 else C.YELLOW if pct > 60 else C.GREEN
            return f"{col}{'█' * filled}{C.GREY}{'░' * (width - filled)}{C.RESET} {pct_str}"

        cpu = summary["cpu"]
        mem = summary["memory"]
        swap= summary["swap"]

        print(f"\n  {'CPU':<10}  {bar(cpu)}")
        mem_pct = mem.split()[0]
        print(f"  {'Memory':<10}  {bar(mem_pct)}  {C.dim(mem.split('(')[1].rstrip(')')  if '(' in mem else '')}")
        print(f"  {'Swap':<10}  {bar(swap)}")
        print(f"\n  {'Processes':<10}  {C.info(str(summary['processes']))}")
        print(f"  {'Net Sent':<10}  {C.dim(summary['net_sent'])}")
        print(f"  {'Net Recv':<10}  {C.dim(summary['net_recv'])}")

        if summary.get("disks"):
            print(f"\n  {C.dim('Disks:')}")
            for mount, info in summary["disks"].items():
                print(f"    {mount:<20}  {bar(str(info['percent']) + '%')}  {C.dim(info['used'] + ' / ' + info['total'])}")

        if summary.get("top_processes"):
            print(f"\n  {C.dim('Top processes:')}")
            for p in summary["top_processes"]:
                print(f"    {str(p.get('pid','?')):>7}  {str(p.get('name','?')):<20}  CPU: {p.get('cpu_percent',0):.1f}%")

        if alerts:
            print(f"\n  {C.warn('⚠ Alerts:')}")
            for a in alerts:
                print(f"    {C.warn('!')} {a['msg']}")

        print(f"\n{DIVIDER}\n")

    def _cmd_security_status(self, cmd: ParsedCommand):
        status = self.se.get_status()
        print(f"\n{DIVIDER}")
        print(f"  {C.hi('SECURITY ENGINE')}")
        print(DIVIDER)
        state = C.ok("ACTIVE") if status["active"] else C.err("INACTIVE")
        print(f"\n  Status:      {state}")
        print(f"  Events:      {status['total_events']}")
        by_level = status["by_level"]
        for level, count in by_level.items():
            col = C.err if level in ("CRITICAL","HIGH") else C.warn if level == "MEDIUM" else C.dim
            print(f"    {col(f'{level:<10}')}  {count}")
        print(f"\n{DIVIDER}\n")

    def _cmd_list_threats(self, cmd: ParsedCommand):
        level = cmd.flags.get("level", "LOW").upper()
        events = self.se.get_events(min_level=level)

        print(f"\n{DIVIDER}")
        print(f"  {C.hi('THREAT EVENTS')}  {C.dim(f'(min level: {level})')}")
        print(DIVIDER)

        if not events:
            print(C.ok("  ✓ No threat events at this level."))
        else:
            for e in events[-30:]:
                ts = time.strftime("%H:%M:%S", time.localtime(e.timestamp))
                col = C.err if e.level in ("CRITICAL","HIGH") else C.warn if e.level == "MEDIUM" else C.dim
                print(f"  {C.dim(ts)}  {col(f'[{e.level:<8}]')}  {e.description}")
                print(f"  {' '*10}  {C.dim('→')} {C.dim(e.recommendation)}")
                print()
        print(f"{DIVIDER}\n")

    def _cmd_list_alerts(self, cmd: ParsedCommand):
        alerts = self.sm.get_alerts(clear=False)
        print(f"\n{DIVIDER}")
        print(f"  {C.hi('SYSTEM ALERTS')}")
        print(DIVIDER)
        if not alerts:
            print(C.ok("  ✓ No active alerts."))
        else:
            for a in alerts:
                print(f"  {C.warn('⚠')} [{a['type']}]  {a['msg']}")
        print(f"\n{DIVIDER}\n")

    def _cmd_list_connections(self, cmd: ParsedCommand):
        conns = self.se.scan_connections()
        print(f"\n{DIVIDER}")
        print(f"  {C.hi('NETWORK CONNECTIONS')}  {C.dim(f'({len(conns)} total)')}")
        print(DIVIDER)
        header = f"  {'PID':>7}  {'NAME':<20}  {'STATUS':<12}  {'LOCAL':<22}  REMOTE"
        print(C.dim(header))
        print(DIVIDER)
        for c in conns[:40]:
            pid_s = str(c["pid"] or "-")
            name_s = (c["name"] or "-")[:20]
            status_col = C.ok(c["status"]) if c["status"] == "ESTABLISHED" else C.dim(c["status"])
            print(f"  {pid_s:>7}  {name_s:<20}  {status_col:<12}  {c['local']:<22}  {C.dim(c['remote'])}")
        if len(conns) > 40:
            print(C.dim(f"  ... {len(conns) - 40} more connections"))
        print(f"\n{DIVIDER}\n")

    def _cmd_find_process(self, cmd: ParsedCommand):
        if not cmd.args:
            print(C.err("  ✗ Usage: find <name>"))
            return
        name = cmd.args[-1]
        procs = self.pm.find_by_name(name)
        print(f"\n{DIVIDER}")
        print(f"  {C.hi('SEARCH:')} {C.info(name)}  {C.dim(f'({len(procs)} found)')}")
        print(DIVIDER)
        if not procs:
            print(C.warn(f"  No processes matching '{name}'."))
        else:
            for p in procs:
                print(f"  PID {C.info(str(p.pid))}  {C.hi(p.name)}  {C.dim(p.status)}  CPU:{p.cpu:.1f}%")
        print(f"\n{DIVIDER}\n")

    def _cmd_suspend(self, cmd: ParsedCommand):
        if not cmd.args:
            print(C.err("  ✗ Usage: suspend <PID>"))
            return
        try:
            pid = int(cmd.args[0])
        except ValueError:
            print(C.err(f"  ✗ Invalid PID: {cmd.args[0]}"))
            return
        ok = self.pm.suspend(pid)
        print(C.ok(f"  ✓ PID {pid} suspended.") if ok else C.err(f"  ✗ Could not suspend PID {pid}."))

    def _cmd_resume(self, cmd: ParsedCommand):
        if not cmd.args:
            print(C.err("  ✗ Usage: resume <PID>"))
            return
        try:
            pid = int(cmd.args[0])
        except ValueError:
            print(C.err(f"  ✗ Invalid PID: {cmd.args[0]}"))
            return
        ok = self.pm.resume(pid)
        print(C.ok(f"  ✓ PID {pid} resumed.") if ok else C.err(f"  ✗ Could not resume PID {pid}."))

    def _cmd_set_priority(self, cmd: ParsedCommand):
        if len(cmd.args) < 2:
            print(C.err("  ✗ Usage: priority <PID> <nice_value>  (nice: -20 to 19)"))
            return
        try:
            pid = int(cmd.args[0])
            nice = int(cmd.args[1])
        except ValueError:
            print(C.err("  ✗ PID and nice value must be integers."))
            return
        ok = self.pm.set_priority(pid, nice)
        print(C.ok(f"  ✓ PID {pid} nice set to {nice}.") if ok else C.err(f"  ✗ Could not set priority (root required for < 0)."))

    def _cmd_math(self, cmd: ParsedCommand):
        if not cmd.args:
            print(C.err("  ✗ Usage: math <expression>   e.g. math sqrt(144) + pi"))
            return
        expr = " ".join(cmd.args)
        result = self.math.evaluate(expr)
        formatted = self.math.format_result(result)
        print(f"\n  {C.dim(expr)}  {C.accent(formatted)}\n")

    # ──────────────────────────────────────────
    #  Phase 2 Handlers
    # ──────────────────────────────────────────

    def _cmd_gpa(self, cmd: ParsedCommand):
        if not self.gpa:
            print(C.err("  ✗ GPA Service not available."))
            return
        
        sub = cmd.args[0] if cmd.args else "report"
        if sub == "add":
            if len(cmd.args) < 5:
                print(C.err("  ✗ Usage: gpa add <name> <credits> <grade> <semester>"))
                return
            try:
                name, credits, grade, semester = cmd.args[1], float(cmd.args[2]), cmd.args[3], cmd.args[4]
                res = self.gpa.add_course(name, credits, grade, semester)
                if res["ok"]:
                    print(C.ok(f"  ✓ Added course: {name} ({semester})"))
                else:
                    print(C.err(f"  ✗ {res['error']}"))
            except ValueError:
                print(C.err("  ✗ Credits must be a number."))
        elif sub == "remove":
            if len(cmd.args) < 3:
                print(C.err("  ✗ Usage: gpa remove <name> <semester>"))
                return
            res = self.gpa.remove_course(cmd.args[1], cmd.args[2])
            if res["ok"]:
                print(C.ok(f"  ✓ Removed course: {cmd.args[1]} from {cmd.args[2]}"))
            else:
                print(C.warn(f"  ✗ Course not found: {cmd.args[1]} in {cmd.args[2]}"))
        elif sub == "clear":
            confirm = input(f"\n  {C.warn('CLEAR ALL GPA DATA')}? [y/N] ").strip().lower()
            if confirm == "y":
                self.gpa.clear()
                print(C.ok("  ✓ All courses cleared."))
        elif sub == "report":
            report = self.gpa.get_report()
            print(f"\n{DIVIDER}")
            print(f"  {C.hi('ACADEMIC REPORT')}")
            print(DIVIDER)
            print(f"  CGPA: {C.accent(f'{report['cgpa']:.2f}')} | Total Credits: {C.info(str(report['total_credits']))}")
            print(f"  Course Count: {report['course_count']}")
            print(f"  Highest GPA: {C.ok(report['highest_gpa_semester'])} | Lowest GPA: {C.err(report['lowest_gpa_semester'])}")
            
            for sem, data in report["semesters"].items():
                print(f"\n  {C.hi(f'Semester: {sem}')}  (GPA: {data['gpa']:.2f})")
                for c in data["courses"]:
                    print(f"    - {c['name']:<15} | {c['credit_hours']} hrs | {C.info(c['grade'])}")
            print(f"\n{DIVIDER}")
        else:
            print(C.err(f"  ✗ Unknown GPA subcommand: {sub}"))

    def _cmd_graph(self, cmd: ParsedCommand):
        if not self.graph:
            print(C.err("  ✗ Graph AI not available."))
            return
        
        sub = cmd.args[0] if cmd.args else "show"
        if sub == "scan":
            print(C.dim("  Scanning network topology..."))
            self.graph.scan()
            print(C.ok("  ✓ Network scan complete."))
        elif sub == "show":
            print(C.info(self.graph.render_ascii()))
        elif sub == "anomalies":
            anomalies = self.graph.detect_anomalies()
            if not anomalies:
                print(C.ok("  ✓ No network anomalies detected."))
            else:
                print(C.warn(f"  ⚠ {len(anomalies)} Anomaly(s) Detected:"))
                for a in anomalies:
                    print(f"    - {C.err(a['type'])}: {a['detail']} ({C.dim(a['severity'])})")
        elif sub == "export":
            print(self.graph.export_json())

    def _cmd_learn(self, cmd: ParsedCommand):
        if not self.le:
            print(C.err("  ✗ Learning Engine not available."))
            return
        
        sub = cmd.args[0] if cmd.args else "stats"
        if sub == "stats":
            stats = self.le.get_stats()
            print(f"\n  {C.hi('USAGE STATISTICS')}")
            print(f"  Total Commands: {C.info(str(stats['total_commands']))}")
            print(f"  Top Commands:")
            for cmd_name, count in stats["top_commands"]:
                print(f"    - {cmd_name:<10} {count} uses")
        elif sub == "suggest":
            suggestions = self.le.suggest()
            print(f"\n  {C.hi('AI SUGGESTIONS')}")
            for i, s in enumerate(suggestions, 1):
                print(f"    {i}. {C.accent(s)}")
        else:
            print(C.err(f"  ✗ Unknown learn subcommand: {sub}"))

    def _cmd_task(self, cmd: ParsedCommand):
        if not self.ae:
            print(C.err("  ✗ Automation Engine not available."))
            return
        
        sub = cmd.args[0] if cmd.args else "list"
        if sub == "add":
            if len(cmd.args) < 5:
                print(C.err("  ✗ Usage: task add <name> interval <seconds> <command>"))
                print(C.err("  ✗ Usage: task add <name> time <HH:MM> <command>"))
                return
            name, ttype, val = cmd.args[1:4]
            command = " ".join(cmd.args[4:])
            
            interval = int(val) if ttype == "interval" else None
            run_at = val if ttype == "time" else None
            
            res = self.ae.add_task(name, command, ttype, interval, run_at)
            if res["ok"]:
                print(C.ok(f"  ✓ Task '{name}' scheduled (ID: {res['id']})."))
            else:
                print(C.err(f"  ✗ {res['error']}"))
        elif sub == "list":
            tasks = self.ae.list_tasks()
            print(f"\n  {C.hi('SCHEDULED TASKS')}")
            for t in tasks:
                state = C.ok("ON") if t.get("enabled",True) else C.dim("OFF")
                sched = f"{t['interval_seconds']}s" if t['schedule_type'] == "interval" else t['run_at_time']
                print(f"  {C.info(t['id'])} [{state}] {C.hi(t['name']):<15} | {t['schedule_type']}:{sched} | {C.dim(t['command'])}")
        elif sub == "remove":
            if len(cmd.args) < 2:
                print(C.err("  ✗ Usage: task remove <id>"))
                return
            res = self.ae.remove_task(cmd.args[1])
            if res["ok"]:
                print(C.ok(f"  ✓ Task '{cmd.args[1]}' removed."))
            else:
                print(C.err(f"  ✗ {res['error']}"))
        elif sub == "run":
            if len(cmd.args) < 2:
                print(C.err("  ✗ Usage: task run <id>"))
                return
            print(C.dim(f"  Executing task '{cmd.args[1]}' now..."))
            res = self.ae.run_now(cmd.args[1])
            if res["ok"]:
                print(C.ok(f"  ✓ Success (Code {res['returncode']})"))
                print(f"  {C.dim(res['output'])}")
            else:
                print(C.err(f"  ✗ {res['error']}"))
        elif sub == "enable":
            if len(cmd.args) < 2: return
            res = self.ae.enable_task(cmd.args[1])
            print(C.ok(f"  ✓ Task {cmd.args[1]} enabled.") if res["ok"] else C.err(f"  ✗ {res['error']}"))
        elif sub == "disable":
            if len(cmd.args) < 2: return
            res = self.ae.disable_task(cmd.args[1])
            print(C.warn(f"  ✓ Task {cmd.args[1]} disabled.") if res["ok"] else C.err(f"  ✗ {res['error']}"))
        elif sub == "history":
            history = self.ae.get_history()
            print(f"\n  {C.hi('TASK EXECUTION HISTORY')}")
            for h in history:
                ts = time.strftime("%H:%M:%S", time.localtime(h["timestamp"]))
                res = C.ok("SUCCESS") if h["returncode"] == 0 else C.err(f"FAIL({h['returncode']})")
                print(f"  {C.dim(ts)} | {h['task_id']:<15} | {res}")

    def _cmd_cyber(self, cmd: ParsedCommand):
        if not self.cyber:
            print(C.err("  ✗ Cyber Intelligence module not available."))
            return
        
        sub = cmd.args[0] if cmd.args else "report"
        if sub == "scan":
            print(C.dim("  Running defensive localhost port scan (1-1024)..."))
            self.cyber.scan_ports()
            print(C.ok("  ✓ Port scan complete."))
        elif sub == "report":
            report = self.cyber.get_report()
            print(f"\n  {C.hi('CYBER INTELLIGENCE REPORT')}")
            print(f"  Risk Level: {C.err(report['risk_level']) if report['risk_score'] > 50 else C.ok(report['risk_level'])}")
            print(f"  Risk Score: {C.accent(str(report['risk_score']))}/100")
            print(f"  Hostname:   {report['hostname']}")
            print(DIVIDER)
            for f in report["open_ports"]:
                col = C.err if f["risk"] == "HIGH" else C.warn if f["risk"] == "MEDIUM" else C.ok
                print(f"  PORT {C.hi(str(f['port'])):<5} | {f['service']:<12} | {col(f['risk'])}")
            
            if report["recommendations"]:
                print(f"\n  {C.hi('RECOMMENDATIONS:')}")
                for rec in report["recommendations"]:
                    print(f"    - {rec}")
        elif sub == "score":
            score = self.cyber.get_risk_score()
            print(f"\n  Defensive Risk Score: {C.accent(str(score))}/100")

    def _cmd_kernel(self, cmd: ParsedCommand):
        if not self.kernel:
            print(C.err("  ✗ Kernel Interface not available."))
            return
        
        sub = cmd.args[0] if cmd.args else "info"
        if sub == "info":
            info = self.kernel.get_all()
            cpu = info["cpu"]
            mem = info["memory"]
            print(f"\n  {C.hi('KERNEL INTERFACE - SYSTEM INFO')}")
            print(f"  Kernel:  {C.info(info['kernel'])}")
            print(f"  CPU:     {C.hi(cpu['model'])} ({cpu['cores']} Cores @ {cpu['mhz']}MHz)")
            print(f"  Memory:  {mem['MemFree']}/{mem['MemTotal']} MB Free")
            print(f"  Swap:    {mem['SwapFree']}/{mem['SwapTotal']} MB Free")
        elif sub == "load":
            load = self.kernel.get_load()
            uptime = self.kernel.get_uptime()
            print(f"\n  {C.hi('SYSTEM LOAD & UPTIME')}")
            print(f"  Load 1m:  {C.accent(str(load['load_1min']))}")
            print(f"  Load 5m:  {C.accent(str(load['load_5min']))}")
            print(f"  Load 15m: {C.accent(str(load['load_15min']))}")
            print(f"  Procs:    {load['running_processes']}/{load['total_processes']} running")
            print(f"  Uptime:   {C.ok(uptime['formatted'])}")
        elif sub == "uptime":
            uptime = self.kernel.get_uptime()
            print(f"\n  System Uptime: {C.ok(uptime['formatted'])}")

    # ──────────────────────────────────────────
    #  Phase 3 Handlers
    # ──────────────────────────────────────────

    def _cmd_gui(self, cmd: ParsedCommand):
        sub = cmd.args[0] if cmd.args else "status"
        if sub == "start":
            if self.gui_active:
                print(C.warn("  GUI Dashboard is already running."))
            else:
                from interface.gui.dashboard import start_gui
                self._gui_thread = start_gui(self.sm, self.pm, self.se)
                self.gui_active = True
                print(C.ok("  ✓ GUI Dashboard started at http://localhost:5000"))
        elif sub == "stop":
            if not self.gui_active:
                print(C.warn("  GUI Dashboard is not running."))
            else:
                # Flask doesn't provide a clean shutdown easily from thread without Werkzeug shutdown.
                # Since we started it as a daemon thread, it will die with the main process.
                # For Phase 3, we'll just mark it as inactive.
                self.gui_active = False
                print(C.warn("  ✓ GUI Dashboard marked as INACTIVE. (Full shutdown on OS exit)"))
        else:
            state = C.ok("RUNNING") if self.gui_active else C.dim("OFFLINE")
            print(f"\n  GUI Dashboard Status: {state}")
            if self.gui_active:
                print(f"  URL: {C.info('http://localhost:5000')}")

    def _cmd_voice(self, cmd: ParsedCommand):
        sub = cmd.args[0] if cmd.args else "status"
        if not self.voice:
            print(C.err("  ✗ Voice Engine not available."))
            return
        
        if sub == "start":
            self.voice.start_listening()
            print(C.ok("  ✓ Voice engine activated. Listening..."))
        elif sub == "stop":
            self.voice.stop_listening()
            print(C.warn("  ✓ Voice engine deactivated."))
        else:
            state = C.ok("LISTENING") if self.voice.is_active() else C.dim("OFFLINE")
            print(f"\n  Voice Engine Status: {state}")

    # ──────────────────────────────────────────
    #  General Handlers
    # ──────────────────────────────────────────

    def _cmd_help(self, cmd: ParsedCommand):
        print(self.ci.get_help_text())

    def _cmd_clear(self, cmd: ParsedCommand):
        os.system("clear" if os.name != "nt" else "cls")

    def _cmd_version(self, cmd: ParsedCommand):
        print(f"\n  {C.hi('PRIMERS OS')}  {C.accent('v' + self.settings.version)}")
        print(f"  {C.dim('Build: Phase 4 · AI-Native Modular Platform')}\n")

    def _cmd_exit(self, cmd):
        print(f"\n  {C.dim('PRIMERS OS shutting down...')}\n")
        self.sm.stop()
        self.se.stop()
        if self.ae:
            self.ae.stop()
        if self.voice:
            self.voice.stop_listening()
        self._running = False
        sys.exit(0)

    def _cmd_unknown(self, cmd: ParsedCommand):
        raw = cmd.raw if cmd else "?"
        print(f"\n  {C.err('✗ Unknown command:')} {C.hi(raw)}")
        print(f"  {C.dim('Type')} {C.info('help')} {C.dim('to see available commands.')}\n")

    # ──────────────────────────────────────────
    #  Boot summary
    # ──────────────────────────────────────────

    def _show_boot_summary(self):
        print(f"  {C.dim('Version:')}    {C.info(self.settings.version)}")
        print(f"  {C.dim('Monitor:')}    {C.ok('Online')}")
        print(f"  {C.dim('Security:')}   {C.ok('Online')}")
        print(f"  {C.dim('AI Engine:')}  {C.ok('Online')}")
        print(f"  {C.dim('Intelligence:')}{C.ok('Active')}")
        print(f"  {C.dim('Services:')}   {C.ok('math, gpa, graph')}")
        alerts = self.sm.get_alerts()
        if alerts:
            print(f"\n  {C.warn(f'⚠ {len(alerts)} startup alert(s) — type alerts to view')}")

    # ──────────────────────────────────────────
    #  Readline setup
    # ──────────────────────────────────────────

    def _setup_readline(self):
        try:
            readline.set_history_length(1000)
            if os.path.exists(self._history_file):
                readline.read_history_file(self._history_file)
            
            commands = list(self.ci.COMMAND_MAP.keys())
            def completer(text, state):
                options = [c for c in commands if c.startswith(text)]
                return options[state] if state < len(options) else None
            readline.set_completer(completer)
            readline.parse_and_bind("tab: complete")
        except Exception:
            pass

