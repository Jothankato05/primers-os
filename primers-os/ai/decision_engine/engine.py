"""
PRIMERS OS — Decision Engine
Analyses system state and makes intelligent recommendations.
Phase 1: rule-based logic. Phase 2+: ML model integration.
"""

import time
from typing import List, Dict, Optional
from utils.logger import PrimersLogger


class Recommendation:
    def __init__(self, action: str, reason: str, severity: str, confidence: float = 1.0, explanation: str = "", auto_execute: bool = False):
        self.action = action
        self.reason = reason
        self.severity = severity       # INFO / WARNING / CRITICAL
        self.confidence = confidence
        self.explanation = explanation
        self.auto_execute = auto_execute
        self.timestamp = time.time()

    def __repr__(self):
        return f"[{self.severity}] (Conf: {self.confidence:.2f}) {self.reason} → {self.action}"


class DecisionEngine:
    """
    Upgraded Decision Engine.
    Uses historical usage patterns to weight recommendations.
    """

    def __init__(self, system_monitor, process_manager, security_engine, learning_engine=None):
        self.logger = PrimersLogger.get_logger("decision_engine")
        self.system_monitor = system_monitor
        self.process_manager = process_manager
        self.security_engine = security_engine
        self.learning_engine = learning_engine
        self._decision_log: List[Recommendation] = []

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def analyse(self) -> List[Recommendation]:
        """Run a full analysis cycle. Returns list of recommendations."""
        recs = []
        recs.extend(self._analyse_resources())
        recs.extend(self._analyse_threats())
        recs.extend(self._analyse_processes())

        # Weight recommendations by user behaviour if learning engine is available
        if self.learning_engine:
            stats = self.learning_engine.get_stats()
            top_cmds = [cmd for cmd, count in stats.get("top_commands", [])]
            for r in recs:
                # If recommendation action matches a frequently used command, boost confidence
                action_base = r.action.split()[0]
                if action_base in top_cmds:
                    r.confidence = min(1.0, r.confidence + 0.1)
                    r.explanation += f" Boosted confidence due to high historical usage of '{action_base}'."

        for r in recs:
            self._decision_log.append(r)
            if r.severity == "CRITICAL":
                self.logger.warning(f"DECISION: {r}")

        return recs

    def explain(self, recommendation: Recommendation) -> str:
        """Returns human-readable reasoning for a recommendation."""
        return f"Reason: {recommendation.reason}\nConfidence: {recommendation.confidence:.2f}\nDetailed Explanation: {recommendation.explanation}"

    def get_decision_log(self, limit: int = 20) -> List[Recommendation]:
        return self._decision_log[-limit:]

    def evaluate_process(self, pid: int) -> Optional[Recommendation]:
        """Evaluate a specific process and return a recommendation."""
        proc = self.process_manager.get_process(pid)
        if not proc:
            return None
        
        if proc.cpu > 90.0:
            return Recommendation(
                action=f"kill {pid}",
                reason=f"Process '{proc.name}' (PID {pid}) using extreme CPU ({proc.cpu:.1f}%)",
                severity="WARNING",
                confidence=0.9,
                explanation="Process exceeds safety thresholds for CPU usage."
            )
        
        # Check against learning engine for anomalous behaviour
        if self.learning_engine:
            stats = self.learning_engine.get_stats()
            # If the process name is not among the top 10 most used commands/processes, 
            # and it has high resources, flag it as anomalous
            most_used_names = [item["command"].split()[0] for item in stats.get("most_used", [])]
            if proc.name not in most_used_names and (proc.cpu > 50.0 or proc.memory > 20.0):
                return Recommendation(
                    action=f"suspend {pid}",
                    reason=f"Anomalous resource usage by unknown process '{proc.name}'",
                    severity="MEDIUM",
                    confidence=0.7,
                    explanation=f"Process '{proc.name}' is not in history of commonly used apps but is consuming significant resources."
                )

        return Recommendation(
            action="none",
            reason=f"Process '{proc.name}' (PID {pid}) appears healthy",
            severity="INFO",
            confidence=1.0,
            explanation="Resource usage is within normal bounds or aligns with historical patterns."
        )

    # ------------------------------------------------------------------ #
    #  Analysis sub-routines
    # ------------------------------------------------------------------ #

    def _analyse_resources(self) -> List[Recommendation]:
        recs = []
        snap = self.system_monitor.get_snapshot()
        if not snap:
            return recs

        if snap.cpu_percent > 90:
            recs.append(Recommendation(
                action="ps --sort=cpu",
                reason=f"System CPU at {snap.cpu_percent:.1f}%.",
                severity="WARNING",
                confidence=0.8,
                explanation="High system-wide CPU usage detected. Recommend reviewing top processes."
            ))
        if snap.memory_percent > 85:
            recs.append(Recommendation(
                action="ps --sort=mem",
                reason=f"Memory at {snap.memory_percent:.1f}%.",
                severity="WARNING",
                confidence=0.7,
                explanation="Low available memory. Identifying memory-hungry processes is advised."
            ))
        for mount, info in snap.disk_usage.items():
            if info["percent"] > 90:
                recs.append(Recommendation(
                    action=f"clear_disk {mount}",
                    reason=f"Disk {mount} at {info['percent']}%.",
                    severity="CRITICAL",
                    confidence=0.95,
                    explanation="Critical disk space shortage. Risk of system instability."
                ))
        return recs

    def _analyse_threats(self) -> List[Recommendation]:
        recs = []
        events = self.security_engine.get_events(min_level="MEDIUM")
        for event in events:
            if event.level == "CRITICAL":
                recs.append(Recommendation(
                    action=f"kill {event.pid}" if event.pid else "security",
                    reason=event.description,
                    severity="CRITICAL",
                    confidence=0.9,
                    explanation="Security threat detected with critical severity. Immediate action required.",
                    auto_execute=False
                ))
            elif event.level == "HIGH":
                recs.append(Recommendation(
                    action=f"status --pid={event.pid}" if event.pid else "threats",
                    reason=event.description,
                    severity="WARNING",
                    confidence=0.75,
                    explanation="High-level security event. Suspicious activity noted."
                ))
        return recs

    def _analyse_processes(self) -> List[Recommendation]:
        recs = []
        procs = self.process_manager.list_processes(sort_by="cpu", limit=5)
        for p in procs:
            if p.cpu > 90:
                recs.append(Recommendation(
                    action=f"kill {p.pid}",
                    reason=f"'{p.name}' (PID {p.pid}) CPU={p.cpu:.1f}%",
                    severity="WARNING",
                    confidence=0.85,
                    explanation="Single process is monopolizing CPU resources."
                ))
        return recs

