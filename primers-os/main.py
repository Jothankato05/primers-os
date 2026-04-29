#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════╗
║           PRIMERS OS — SYSTEM CONTROLLER              ║
║           AI-Native Modular OS Platform               ║
╚═══════════════════════════════════════════════════════╝
"""

import sys
import os
import signal

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.system_monitor.monitor import SystemMonitor
from core.process_manager.manager import ProcessManager
from core.security_engine.engine import SecurityEngine
from core.kernel_interface.interface import KernelInterface
from ai.command_interpreter.interpreter import CommandInterpreter
from ai.decision_engine.engine import DecisionEngine
from ai.learning_engine.engine import LearningEngine
from ai.automation_engine.engine import AutomationEngine
from ai.cyber_intelligence.module import CyberIntelligence
from interface.cli.shell import PrimersShell
from services.gpa_service.service import GPAService
from configs.settings import Settings
from utils.logger import PrimersLogger


def shutdown_handler(signum, frame):
    print("\n\n[PRIMERS OS] Shutdown signal received. Terminating gracefully...")
    sys.exit(0)


def boot():
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logger = PrimersLogger.get_logger("boot")
    settings = Settings()

    logger.info("PRIMERS OS booting...")

    # Initialise core subsystems
    system_monitor = SystemMonitor()
    process_manager = ProcessManager()
    security_engine = SecurityEngine()
    kernel_interface = KernelInterface()

    # Initialise AI & Intelligence layer
    learning_engine = LearningEngine()
    automation_engine = AutomationEngine()
    automation_engine.start() # Start scheduler
    cyber_intelligence = CyberIntelligence()
    
    # Services
    gpa_service = GPAService()
    from services.graph_ai.engine import GraphAIEngine
    graph_ai = GraphAIEngine()

    # Initialise AI layer with learning integration
    decision_engine = DecisionEngine(
        system_monitor=system_monitor,
        process_manager=process_manager,
        security_engine=security_engine,
        learning_engine=learning_engine
    )
    command_interpreter = CommandInterpreter(
        process_manager=process_manager,
        decision_engine=decision_engine,
        settings=settings
    )

    # Phase 3 — Voice
    from interface.voice.listener import VoiceListener
    voice_listener = VoiceListener(command_interpreter)

    # Start background monitoring
    system_monitor.start()
    security_engine.start()

    logger.info("All subsystems online.")

    print(f"\n  ⚛  PRIMERS OS {settings.VERSION} · {getattr(settings, 'OS_EDITION', 'Genesis')}")
    print(f"  Type 'help' · 'primers-install' adds modules · 'gui start' opens dashboard\n")

    # Launch CLI
    shell = PrimersShell(
        command_interpreter=command_interpreter,
        system_monitor=system_monitor,
        process_manager=process_manager,
        security_engine=security_engine,
        settings=settings,
        learning_engine=learning_engine,
        automation_engine=automation_engine,
        cyber_intelligence=cyber_intelligence,
        kernel_interface=kernel_interface,
        gpa_service=gpa_service,
        graph_ai=graph_ai
    )
    # Add voice listener to shell if needed (optional, but good for control)
    shell.voice = voice_listener
    
    # Load Plugins
    try:
        from services.plugin_loader.loader import PluginLoader
        plugin_loader = PluginLoader(shell)
        plugin_loader.load_all()
    except ImportError:
        logger.warn("PluginLoader not found, skipping plugins.")

    shell.run()


if __name__ == "__main__":
    boot()

