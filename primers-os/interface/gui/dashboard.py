"""
PRIMERS OS — Web Dashboard

A small read-only Flask app showing live system metrics. It listens on
127.0.0.1 by default and rejects requests whose Host header is not local,
so web pages in the user's browser cannot read it via DNS rebinding.
"""

import os
import sys
import threading
from typing import Optional

parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from configs.settings import Settings  # noqa: E402
from utils.logger import PrimersLogger  # noqa: E402

logger = PrimersLogger.get_logger("gui_dashboard")

try:
    from flask import Flask, abort, jsonify, request
    from werkzeug.serving import make_server
    FLASK_AVAILABLE = True
    FLASK_ERROR = ""
except ImportError as _e:  # pragma: no cover - depends on the host
    FLASK_AVAILABLE = False
    FLASK_ERROR = str(_e)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PRIMERS OS Dashboard</title>
<style>
  :root {
    --bg: #0d0d0d; --panel: #1a1a1a; --accent: #00e5ff; --text: #e0e0e0;
    --warn: #ffcc00; --danger: #ff4444; --success: #00ff88; --dim: #888888; --line: #333;
  }
  * { box-sizing: border-box; }
  body { font-family: 'Noto Sans', 'Segoe UI', sans-serif; background: var(--bg); color: var(--text);
         margin: 0; padding: 20px; }
  h1, h2, h3 { margin: 0; }
  .mono { font-family: 'Noto Sans Mono', 'Consolas', monospace; }
  header { display: flex; justify-content: space-between; align-items: center; gap: 12px;
           border-bottom: 2px solid var(--accent); padding-bottom: 15px; margin-bottom: 25px; flex-wrap: wrap; }
  header h1 { color: var(--accent); font-size: 1.6rem; letter-spacing: 2px; }
  header small { font-size: .8rem; color: var(--dim); }
  #clock { color: var(--dim); }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 25px; }
  .card, .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; }
  .card { text-align: center; }
  .card h3 { color: var(--dim); font-size: .8rem; text-transform: uppercase; margin-bottom: 8px; }
  .card .value { font-size: 2rem; font-weight: bold; color: var(--accent); }
  .card .value.small { font-size: 1.1rem; padding-top: 10px; }
  .grid { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 20px; }
  @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  .side { display: flex; flex-direction: column; gap: 20px; min-width: 0; }
  .panel h2 { color: var(--accent); font-size: 1.1rem; margin-bottom: 12px; border-left: 4px solid var(--accent); padding-left: 10px; }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 8px; border-bottom: 1px solid #444; color: var(--dim); font-size: .75rem; text-transform: uppercase; }
  td { padding: 8px; border-bottom: 1px solid var(--line); font-size: .9rem; word-break: break-all; }
  .badge { padding: 2px 8px; border-radius: 4px; font-size: .7rem; font-weight: bold; margin-right: 6px; }
  .badge-info, .badge-low { background: #333; color: var(--success); }
  .badge-medium { background: #443300; color: var(--warn); }
  .badge-high { background: #440000; color: var(--danger); }
  .badge-critical { background: var(--danger); color: #fff; }
  .event { margin-bottom: 10px; border-bottom: 1px solid #222; padding-bottom: 6px; font-size: .85rem; }
  .event .ts { font-size: .7rem; color: var(--dim); }
  .tags { display: flex; flex-wrap: wrap; gap: 8px; }
  .tag { background: #222; padding: 4px 10px; border-radius: 4px; border: 1px solid #444; font-size: .85rem; }
  .tag b { color: var(--accent); }
  .muted { color: var(--dim); }
  .error { color: var(--danger); }
  footer { margin-top: 30px; text-align: center; color: var(--dim); font-size: .8rem; border-top: 1px solid var(--line); padding-top: 15px; }
</style>
</head>
<body>
<header>
  <h1>⚛ PRIMERS OS <small id="version"></small></h1>
  <div id="clock" class="mono">--:--:--</div>
</header>

<section class="stats">
  <div class="card"><h3>CPU</h3><div id="cpu" class="value mono">–</div></div>
  <div class="card"><h3>Memory</h3><div id="mem" class="value mono">–</div></div>
  <div class="card"><h3>Processes</h3><div id="procs" class="value mono">–</div></div>
  <div class="card"><h3>Load (1m)</h3><div id="load" class="value mono">–</div></div>
  <div class="card"><h3>Uptime</h3><div id="uptime" class="value small mono">–</div></div>
</section>

<section class="grid">
  <div class="panel">
    <h2>Top Processes</h2>
    <div class="scroll">
      <table>
        <thead><tr><th>PID</th><th>Name</th><th>CPU%</th><th>MEM%</th><th>Status</th></tr></thead>
        <tbody id="proc-body"><tr><td colspan="5" class="muted">Loading…</td></tr></tbody>
      </table>
    </div>
  </div>
  <div class="side">
    <div class="panel"><h2>Security Events</h2><div id="threats" class="muted">Loading…</div></div>
    <div class="panel"><h2>Network</h2><div id="network" class="tags"></div></div>
    <div class="panel"><h2>Academic GPA</h2>
      <div class="mono" style="font-size:1.4rem;color:var(--accent)">CGPA: <span id="gpa">0.00</span></div>
      <div class="muted">Credits: <span id="credits">0</span></div>
    </div>
  </div>
</section>

<footer>Last updated: <span id="updated">never</span> · PRIMERS OS Intelligence Layer · read-only</footer>

<script>
  "use strict";
  const $ = (id) => document.getElementById(id);
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    for (const c of children) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    return node;
  }
  const pct = (n) => (typeof n === "number" ? n.toFixed(1) + "%" : "–");

  function tick() { $("clock").textContent = new Date().toLocaleTimeString(); }
  setInterval(tick, 1000); tick();

  async function getJSON(path) {
    const r = await fetch(path, { cache: "no-store" });
    if (!r.ok) throw new Error(path + " → " + r.status);
    return r.json();
  }

  async function refresh() {
    try {
      const [status, procs, threats, network, gpa] = await Promise.all([
        getJSON("/api/status"), getJSON("/api/processes"), getJSON("/api/threats"),
        getJSON("/api/network"), getJSON("/api/gpa"),
      ]);
      $("version").textContent = "v" + status.version;
      $("cpu").textContent = pct(status.cpu);
      $("mem").textContent = pct(status.memory_percent);
      $("procs").textContent = status.processes;
      $("load").textContent = typeof status.load_1min === "number" ? status.load_1min.toFixed(2) : "–";
      $("uptime").textContent = status.uptime;

      const body = $("proc-body");
      body.replaceChildren(...procs.map((p) => el("tr", {},
        el("td", { class: "mono" }, p.pid), el("td", {}, p.name),
        el("td", { class: "mono" }, pct(p.cpu)), el("td", { class: "mono" }, pct(p.memory)),
        el("td", {}, p.status))));

      const t = $("threats");
      if (!threats.length) { t.replaceChildren(el("div", { class: "muted" }, "No recent threats.")); }
      else {
        t.replaceChildren(...threats.slice().reverse().map((ev) => el("div", { class: "event" },
          el("span", { class: "badge badge-" + String(ev.level).toLowerCase() }, ev.level),
          el("span", {}, ev.description),
          el("div", { class: "ts" }, new Date(ev.timestamp * 1000).toLocaleTimeString()))));
      }

      const states = {};
      network.forEach((n) => { states[n.status] = (states[n.status] || 0) + 1; });
      $("network").replaceChildren(
        el("div", { class: "tag" }, "Total: ", el("b", {}, network.length)),
        ...Object.entries(states).map(([s, c]) => el("div", { class: "tag" }, s + ": ", el("b", {}, c))));

      $("gpa").textContent = Number(gpa.cgpa).toFixed(2);
      $("credits").textContent = Number(gpa.credits).toFixed(1);
      $("updated").textContent = new Date().toLocaleTimeString();
    } catch (err) {
      $("updated").textContent = "error — " + err.message;
      $("updated").className = "error";
    }
  }
  setInterval(refresh, 5000); refresh();
</script>
</body>
</html>
"""


def create_app(system_monitor=None, process_manager=None, security_engine=None,
               kernel_interface=None, gpa_service=None, settings: Optional[Settings] = None,
               allow_any_host: bool = False):
    """Build the Flask app around the given PRIMERS components."""
    if not FLASK_AVAILABLE:
        raise RuntimeError(f"Flask is not installed ({FLASK_ERROR}). Install python3-flask.")

    settings = settings or Settings()
    app = Flask(__name__)

    @app.before_request
    def _only_local_hosts():
        if allow_any_host:
            return None
        host = (request.host or "").rsplit(":", 1)[0] if not (request.host or "").startswith("[") \
            else (request.host or "").split("]")[0] + "]"
        if host not in LOCAL_HOSTS:
            abort(403)
        return None

    @app.after_request
    def _security_headers(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
            "frame-ancestors 'none'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/")
    def index():
        return HTML_TEMPLATE, 200, {"Content-Type": "text/html; charset=utf-8"}

    @app.route("/api/status")
    def api_status():
        metrics = system_monitor.get_metrics() if system_monitor else {"ready": False}
        uptime = kernel_interface.get_uptime() if kernel_interface else {"formatted": "–"}
        load = kernel_interface.get_load() if kernel_interface else {}
        return jsonify({
            "ready": metrics.get("ready", False),
            "version": settings.VERSION,
            "cpu": metrics.get("cpu_percent"),
            "memory_percent": metrics.get("memory_percent"),
            "processes": metrics.get("process_count", 0),
            "uptime": uptime.get("formatted", "–"),
            "load_1min": load.get("load_1min"),
        })

    @app.route("/api/processes")
    def api_processes():
        procs = process_manager.list_processes(sort_by="cpu", limit=20) if process_manager else []
        return jsonify([{"pid": p.pid, "name": p.name, "cpu": p.cpu, "memory": p.memory,
                         "status": p.status} for p in procs])

    @app.route("/api/threats")
    def api_threats():
        events = security_engine.get_events(min_level="LOW") if security_engine else []
        return jsonify([{"level": e.level, "description": e.description, "timestamp": e.timestamp}
                        for e in events[-10:]])

    @app.route("/api/network")
    def api_network():
        conns = security_engine.scan_connections() if security_engine else []
        return jsonify([{"status": c["status"], "pid": c["pid"], "name": c["name"]} for c in conns])

    @app.route("/api/gpa")
    def api_gpa():
        if gpa_service:
            report = gpa_service.get_report()
            return jsonify({"cgpa": report["cgpa"], "credits": report["total_credits"]})
        return jsonify({"cgpa": 0.0, "credits": 0.0})

    return app


class DashboardServer:
    """Runs the dashboard in a background thread and can stop it again."""

    def __init__(self, app, host: str = "127.0.0.1", port: int = 5000):
        self.app = app
        self.host = host
        self.port = port
        self._server = None
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        self._server = make_server(self.host, self.port, self.app, threaded=True)
        self.port = self._server.server_port  # resolves port 0 in tests
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="Dashboard")
        self._thread.start()
        logger.info(f"GUI dashboard listening on http://{self.host}:{self.port}")

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None
        logger.info("GUI dashboard stopped")


def start_gui(system_monitor, process_manager, security_engine, kernel_interface=None,
              gpa_service=None, settings: Optional[Settings] = None) -> DashboardServer:
    """Create and start the dashboard. Raises OSError if the port is busy."""
    from core.kernel_interface.interface import KernelInterface
    from services.gpa_service.service import GPAService

    settings = settings or Settings()
    # A dashboard deliberately exposed on the LAN must accept LAN host names
    exposed = settings.GUI_HOST not in ("127.0.0.1", "localhost", "::1")
    app = create_app(system_monitor, process_manager, security_engine,
                     kernel_interface or KernelInterface(), gpa_service or GPAService(), settings,
                     allow_any_host=exposed)
    server = DashboardServer(app, settings.GUI_HOST, settings.GUI_PORT)
    server.start()
    return server


if __name__ == "__main__":
    # Standalone mode: python3 interface/gui/dashboard.py
    from core.kernel_interface.interface import KernelInterface
    from core.process_manager.manager import ProcessManager
    from core.security_engine.engine import SecurityEngine
    from core.system_monitor.monitor import SystemMonitor
    from services.gpa_service.service import GPAService

    s = Settings()
    monitor, security = SystemMonitor(s), SecurityEngine(s)
    monitor.start()
    security.start()
    application = create_app(monitor, ProcessManager(), security, KernelInterface(), GPAService(), s)
    print(f"PRIMERS dashboard on {s.gui_url}  (Ctrl+C to stop)")
    make_server(s.GUI_HOST, s.GUI_PORT, application, threaded=True).serve_forever()
