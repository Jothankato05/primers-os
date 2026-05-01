#  PRIMERS OS — Phase 1

AI-Native Modular OS Platform · Python-based system controller built on Linux.

---

## Quick Start (WSL / Ubuntu)

```bash
# 1. Install dependency
pip install psutil

# 2. Run
cd primers-os
python main.py
```

---

## Phase 1 — What's Built

| Module | Location | Status |
|---|---|---|
| System Monitor | `core/system_monitor/` | ✅ Live |
| Process Manager | `core/process_manager/` | ✅ Live |
| Security Engine | `core/security_engine/` | ✅ Live |
| Command Interpreter | `ai/command_interpreter/` | ✅ Live |
| Decision Engine | `ai/decision_engine/` | ✅ Live |
| Math Engine | `services/math_engine/` | ✅ Live |
| CLI Shell | `interface/cli/` | ✅ Live |

---

## CLI Commands

```
ps / processes / top      — List running processes
kill <PID>                — Terminate a process (--force for SIGKILL)
launch <command>          — Launch a new process
status / sysinfo          — System health: CPU, memory, disk, network
security                  — Security engine status
threats                   — Show security threat events (--level=HIGH)
alerts                    — Show system resource alerts
connections / netstat     — Live network connections
find <name>               — Search processes by name
suspend <PID>             — Suspend a process
resume <PID>              — Resume a suspended process
priority <PID> <nice>     — Set process nice value (-20 to 19)
math <expression>         — Evaluate maths (e.g. math sqrt(144) + pi)
version                   — Show OS version
clear                     — Clear terminal
help                      — Show all commands
exit / quit               — Exit PRIMERS OS
```

Natural language also works:
```
"show me processes"
"what's running"
"kill process 1234"
"system status"
"any threats detected"
```

---

## Architecture

```
primers-os/
├── main.py                     ← Boot + wiring
├── core/
│   ├── system_monitor/         ← CPU, mem, disk, net (background thread)
│   ├── process_manager/        ← List, launch, kill, prioritise
│   ├── security_engine/        ← Threat detection, connection audit
│   └── kernel_interface/       ← Reserved (Phase 2)
├── ai/
│   ├── command_interpreter/    ← Text → ParsedCommand
│   └── decision_engine/        ← Rule-based analysis → Recommendations
├── services/
│   ├── math_engine/            ← Safe expression evaluator
│   ├── gpa_service/            ← Reserved (Phase 2)
│   └── graph_ai/               ← Reserved (Phase 2)
├── interface/
│   └── cli/                    ← Shell, prompt, ANSI rendering
├── configs/
│   └── settings.py             ← All tunable config
├── utils/
│   └── logger.py               ← Centralised rotating log
└── logs/
    └── primers.log             ← Runtime log
```

---

## Phase Roadmap

- **Phase 1** (current) — CLI, core monitoring, security, AI command layer
- **Phase 2** — ML decision engine, GPA service, graph AI, kernel interface
- **Phase 3** — GUI (Electron/Qt), gesture control, voice interface
- **Phase 4** — Self-learning, predictive automation, cyber defence system

---

## Security Note

The Security Engine is **strictly defensive**:
- Monitors processes and network connections
- Raises alerts on anomalous behaviour
- Never executes offensive actions
- All process termination requires explicit confirmation
