#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════╗
║           PRIMERS OS — SYSTEM CONTROLLER              ║
║           AI-Native Modular OS Platform               ║
╚═══════════════════════════════════════════════════════╝

Usage:
  primers                       interactive shell
  primers status                run one command and exit
  primers -c "ps --limit=5" -c threats
  primers --gui                 shell with the web dashboard started
  primers --version
"""

import argparse
import os
import signal
import sys

# Ensure project root is importable however we are started
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.version_info < (3, 8):  # pragma: no cover
    sys.exit("PRIMERS OS needs Python 3.8 or newer.")

from configs.settings import Settings  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="primers",
        description="PRIMERS OS — AI-native system controller",
    )
    p.add_argument("command", nargs="*", help="run this command and exit (e.g. 'primers status')")
    p.add_argument("-c", "--command", dest="commands", action="append", default=[],
                   metavar="CMD", help="run CMD and exit (repeatable)")
    p.add_argument("--gui", action="store_true", help="start the web dashboard")
    p.add_argument("--no-banner", action="store_true", help="skip the banner in interactive mode")
    p.add_argument("--version", action="store_true", help="print the version and exit")
    return p.parse_args(argv)


def build_shell(settings: Settings, interactive: bool):
    """Create every subsystem and wire it into a shell (no threads started)."""
    from ai.automation_engine.engine import AutomationEngine
    from ai.command_interpreter.interpreter import CommandInterpreter
    from ai.cyber_intelligence.module import CyberIntelligence
    from ai.decision_engine.engine import DecisionEngine
    from ai.learning_engine.engine import LearningEngine
    from core.kernel_interface.interface import KernelInterface
    from core.process_manager.manager import ProcessManager
    from core.security_engine.engine import SecurityEngine
    from core.system_monitor.monitor import SystemMonitor
    from interface.cli.shell import PrimersShell
    from interface.voice.listener import VoiceListener
    from services.gpa_service.service import GPAService
    from services.graph_ai.engine import GraphAIEngine
    from services.knowledge.engine import KnowledgeBase
    from services.plugin_loader.loader import PluginLoader

    system_monitor = SystemMonitor(settings)
    process_manager = ProcessManager()
    security_engine = SecurityEngine(settings)
    learning_engine = LearningEngine()
    decision_engine = DecisionEngine(
        system_monitor=system_monitor,
        process_manager=process_manager,
        security_engine=security_engine,
        learning_engine=learning_engine,
    )
    command_interpreter = CommandInterpreter(
        process_manager=process_manager,
        decision_engine=decision_engine,
        settings=settings,
    )
    shell = PrimersShell(
        command_interpreter=command_interpreter,
        system_monitor=system_monitor,
        process_manager=process_manager,
        security_engine=security_engine,
        settings=settings,
        learning_engine=learning_engine,
        automation_engine=AutomationEngine(tick_seconds=settings.AUTOMATION_INTERVAL),
        cyber_intelligence=CyberIntelligence(),
        kernel_interface=KernelInterface(),
        gpa_service=GPAService(),
        graph_ai=GraphAIEngine(),
        decision_engine=decision_engine,
        knowledge=KnowledgeBase(),
        interactive=interactive,
    )
    shell.voice = VoiceListener(command_interpreter, on_command=shell.execute_voice)

    loader = PluginLoader(shell)
    loader.load_all()
    shell.plugins = loader.plugins
    return shell


def boot(argv=None) -> int:
    args = parse_args(argv)
    settings = Settings()

    if args.version:
        print(f"PRIMERS OS {settings.VERSION} ({settings.OS_EDITION})")
        return 0

    from utils.logger import PrimersLogger
    logger = PrimersLogger.get_logger("boot")

    commands = list(args.commands)
    if args.command:
        commands.append(" ".join(args.command))
    one_shot = bool(commands)

    shell = build_shell(settings, interactive=not one_shot)

    def shutdown_handler(signum, frame):
        print("\n\n[PRIMERS OS] Shutdown signal received. Terminating gracefully...")
        shell.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)

    if one_shot:
        ok = True
        for line in commands:
            ok = shell.execute(line) and ok
        shell.shutdown()
        return 0 if ok else 1

    logger.info("PRIMERS OS booting...")
    shell.sm.start()
    shell.se.start()
    shell.ae.start()
    logger.info("All subsystems online.")

    if args.gui:
        shell.execute("gui start")
    shell.show_banner = not args.no_banner

    shell.run()
    return 0


if __name__ == "__main__":
    sys.exit(boot())
