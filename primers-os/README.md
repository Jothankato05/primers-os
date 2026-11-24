# ⚛ PRIMERS Brain

The AI-native system controller at the heart of PRIMERS OS: a shell you can
talk to, background engines that watch your system, and a web dashboard.
Pure Python 3.10+, runs on any Linux (and mostly on macOS/WSL).

## Run it

```bash
python3 -m pip install -r requirements.txt   # psutil, flask
python3 main.py                              # interactive shell
python3 main.py status                       # one command, then exit
python3 main.py -c "ps --limit=5" -c advise  # several commands
python3 main.py --gui                        # shell + web dashboard
python3 main.py --version
```

On PRIMERS OS it's simply `primers` (or `Super+Enter`). Exit code is `0` when
every one-shot command succeeded, `1` otherwise — handy for scripts.

## Commands

| Area | Commands |
|---|---|
| System | `status` · `alerts` · `datasaver` (metered network, paused downloads) · `lab` (shared-computer Lab Mode) · `study 25` / `study stop` (focus timer) · `kernel [info\|load\|uptime\|net]` · `version` |
| Processes | `ps [--sort=cpu\|memory\|pid\|name] [--limit=N]` · `find <name>` · `launch <cmd>` · `kill <pid> [--force] [--yes]` · `suspend` / `resume <pid>` · `priority <pid> <nice>` |
| Security | `security` · `threats [--level=HIGH]` · `connections` · `cyber scan [1-1024]` · `cyber report` |
| Intelligence | `ask <question>` — Ask Primers (offline knowledge base) · `advise` — prioritised recommendations · `learn stats\|suggest\|clear` · `task add\|list\|run\|enable\|disable\|remove\|history` |
| Services | `browse <site or search>` (Primers Lite Bee) · `math <expr>` · `gpa add\|remove\|report\|clear` · `graph scan\|show\|anomalies\|stats\|export` · `modules [install <name>]` · `plugins` |
| Interface | `gui start\|stop\|open` · `voice start\|stop` · `help` · `clear` · `exit` |

Natural language works too — anchored phrases, so ordinary sentences never
trigger actions by accident:

```
show me processes        what's running?          kill process 4242
how is my system?        am I safe?               any advice?
what is 2^10             calculate sqrt(2)        open firefox
```

Mistype a command and it suggests the closest ones (`staus` → *status*).
Anything else phrased as a question goes to **Ask Primers**.

## Ask Primers (knowledge layer)

`knowledge/PRIMERS_KNOWLEDGE.md` is loaded at boot and split by heading.
Questions are answered offline, in this order:

1. **Emergencies first** — anything that sounds like danger shows Nigeria's
   emergency number (112) and SecureLink before anything else, and is
   checked before any other command (so *"help me, I'm in danger"* never
   just prints the help text).
2. **Glossary** terms (*"what is Lab Mode?"*), then the **Ready answers** FAQ.
3. The best-matching **section**, quoted from the file (BM25 retrieval with
   heading boost). Table rows are shown as `Field: value`.
4. Nothing relevant → it says so and gives the contact route; it never
   invents. Items marked `[VERIFY]` are shown as *(unconfirmed)*.

Update the file and the next start picks it up. Override the location with
`PRIMERS_KNOWLEDGE=/path/to/file.md`.

### Examples

```text
task add backup interval 3600 tar czf ~/backup.tgz ~/Documents
task add morning time 08:30 notify-send "Good morning"
gpa add "Linear Algebra" 3 A- 2025-Fall
math factorial(20) / 2^10
cyber scan 1-10000
kill 4242 --yes          # skip the confirmation (needed in one-shot mode)
```

## Safety

- `kill`, `learn clear` and `gpa clear` ask for confirmation; in one-shot
  mode pass `--yes`. PID 1 and the Brain itself can never be signalled.
- Voice commands can only run read-only actions (status, ps, threats…).
- `math` uses an AST-based evaluator (no `eval`) with limits on exponent and
  result size.
- The dashboard is read-only, listens on `127.0.0.1`, rejects non-local
  `Host` headers (DNS rebinding), and sends a strict CSP.
- One failing command never takes down the shell; details go to the log.

## Where data lives

| | Installed (`/usr/share/primers/brain`) | Git checkout |
|---|---|---|
| Data dir | `~/.local/share/primers` (`$XDG_DATA_HOME`) | `./logs` |
| Files | `usage.jsonl` (learning), `tasks.json`, `task_history.jsonl`, `gpa_data.json`, `primers.log`, `.cli_history`, `plugins/` | same |

The directory is created `0700` and files `0600`. Override with
`PRIMERS_DATA_DIR` (and `PRIMERS_LOG_DIR` for the log).

## Configuration

Every setting in [`configs/settings.py`](configs/settings.py) can be
overridden with a `PRIMERS_`-prefixed environment variable:

| Variable | Default |
|---|---|
| `PRIMERS_CPU_ALERT_THRESHOLD` / `_MEMORY_` / `_DISK_` | 90 / 85 / 90 (%) |
| `PRIMERS_MONITOR_INTERVAL` / `PRIMERS_SECURITY_SCAN_INTERVAL` | 5 / 10 (s) |
| `PRIMERS_GUI_HOST` / `PRIMERS_GUI_PORT` | `127.0.0.1` / `5000` |
| `PRIMERS_DEBUG=1` | show all log messages in the terminal |
| `NO_COLOR=1` | plain output |

## Plugins

Drop a Python file in `~/.local/share/primers/plugins/` (it must be owned by
you and not group/world-writable):

```python
NAME = "Weather"
DESCRIPTION = "Shows the weather"
COMMANDS = {"weather": "Current weather"}

def weather(cmd, shell):          # handler(cmd, shell), handler(cmd) or handler()
    city = " ".join(cmd.args) or "your area"
    return f"Forecast for {city}: sunny"  # returned text is printed

def register(shell):
    shell.register_command("weather", weather, COMMANDS["weather"])
```

`services/sample_plugin/plugin.py` is a working example (`hello`).

## Voice

`primers-install voice` (on PRIMERS OS) or `pip install SpeechRecognition
pyaudio`, then `voice start` and say *"primers system status"*. Speech is
transcribed by Google's Web Speech API while voice is on; the Brain tells you
so when you enable it.

## Architecture

```
main.py                      argument parsing, wiring, one-shot vs interactive
core/
  system_monitor/            CPU, memory, disk, network snapshots + threshold alerts
  process_manager/           list / launch / signal processes (protected PIDs)
  security_engine/           process + connection anomaly detection (defensive)
  kernel_interface/          /proc readers with psutil fallbacks
ai/
  command_interpreter/       command registry, natural-language patterns, suggestions
  decision_engine/           rule-based recommendations, weighted by learned habits
  learning_engine/           usage history → stats, sequences, next-command suggestions
  automation_engine/         interval / time-of-day task scheduler
  cyber_intelligence/        localhost port audit with exposure + risk scoring
services/                    math, GPA, network graph, plugin loader
interface/                   cli shell, web dashboard (Flask), voice listener
utils/                       paths (data dirs, private files), logging
tests/                       pytest suite
```

## Tests

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q tests
```

CI runs them on Python 3.10 (what PRIMERS OS ships) and 3.12.
