import sys
import os
import time
import threading
from datetime import datetime
from flask import Flask, jsonify, render_template_string

# Ensure project root is in path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from core.system_monitor.monitor import SystemMonitor
from core.process_manager.manager import ProcessManager
from core.security_engine.engine import SecurityEngine
from core.kernel_interface.interface import KernelInterface
from services.gpa_service.service import GPAService
from utils.logger import PrimersLogger

app = Flask(__name__)
logger = PrimersLogger.get_logger("gui_dashboard")

# Global instances (initialized in main block or via start_gui)
monitor = None
manager = None
security = None
kernel = None
gpa_service = None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PRIMERS OS — Dashboard</title>
    <style>
        :root {
            --bg: #0d0d0d;
            --panel: #1a1a1a;
            --accent: #00e5ff;
            --text: #e0e0e0;
            --warn: #ffcc00;
            --danger: #ff4444;
            --success: #00ff88;
            --dim: #888888;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 20px;
        }
        h1, h2, h3 { margin: 0; }
        .monospace { font-family: 'Consolas', 'Monaco', 'Courier New', monospace; }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid var(--accent);
            padding-bottom: 15px;
            margin-bottom: 25px;
        }
        header h1 { color: var(--accent); font-size: 1.8rem; letter-spacing: 2px; }
        #live-clock { color: var(--dim); font-size: 1.1rem; }

        .stats-row {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 20px;
            margin-bottom: 25px;
        }
        .card {
            background: var(--panel);
            border: 1px solid #333;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        .card h3 { color: var(--dim); font-size: 0.9rem; text-transform: uppercase; margin-bottom: 10px; }
        .card .value { font-size: 2.2rem; font-weight: bold; color: var(--accent); }

        .main-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
        }
        .panel {
            background: var(--panel);
            border: 1px solid #333;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        .panel h2 { color: var(--accent); font-size: 1.2rem; margin-bottom: 15px; border-left: 4px solid var(--accent); padding-left: 10px; }

        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th { text-align: left; padding: 10px; border-bottom: 1px solid #444; color: var(--dim); font-size: 0.8rem; text-transform: uppercase; }
        td { padding: 10px; border-bottom: 1px solid #333; font-size: 0.9rem; }
        
        .badge {
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: bold;
            text-transform: uppercase;
        }
        .badge-low { background: #333; color: var(--success); }
        .badge-medium { background: #443300; color: var(--warn); }
        .badge-high { background: #440000; color: var(--danger); }
        .badge-critical { background: var(--danger); color: white; animation: pulse 1s infinite; }

        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }

        .network-stats { display: flex; flex-wrap: wrap; gap: 10px; }
        .net-tag { background: #222; padding: 5px 10px; border-radius: 4px; border: 1px solid #444; font-size: 0.85rem; }
        .net-tag span { color: var(--accent); font-weight: bold; }

        footer {
            margin-top: 30px;
            text-align: center;
            color: var(--dim);
            font-size: 0.8rem;
            border-top: 1px solid #333;
            padding-top: 15px;
        }
    </style>
</head>
<body>
    <header>
        <h1>⚛ PRIMERS OS <small style="font-size: 0.8rem; color: var(--dim);">v4.0.0-AI</small></h1>
        <div id="live-clock" class="monospace">00:00:00</div>
    </header>

    <div class="stats-row">
        <div class="card">
            <h3>CPU Usage</h3>
            <div id="stat-cpu" class="value monospace">0.0%</div>
        </div>
        <div class="card">
            <h3>Memory</h3>
            <div id="stat-mem" class="value monospace">0.0%</div>
        </div>
        <div class="card">
            <h3>Processes</h3>
            <div id="stat-proc" class="value monospace">0</div>
        </div>
        <div class="card">
            <h3>Uptime</h3>
            <div id="stat-uptime" class="value monospace" style="font-size: 1.2rem; padding-top: 10px;">0d 0h 0m 0s</div>
        </div>
    </div>

    <div class="main-grid">
        <div class="panel">
            <h2>Top Processes</h2>
            <table id="proc-table">
                <thead>
                    <tr>
                        <th>PID</th>
                        <th>Name</th>
                        <th>CPU%</th>
                        <th>MEM%</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    <tr><td colspan="5" style="text-align:center; color:var(--dim);">Loading...</td></tr>
                </tbody>
            </table>
        </div>

        <div style="display: flex; flex-direction: column; gap: 20px;">
            <div class="panel">
                <h2>Security Events</h2>
                <div id="security-list">
                    <div style="color:var(--dim);">Loading events...</div>
                </div>
            </div>

            <div class="panel">
                <h2>Network Activity</h2>
                <div id="network-summary" class="network-stats">
                    <div class="net-tag">Connections: <span id="net-total">0</span></div>
                </div>
            </div>

            <div class="panel">
                <h2>Academic GPA</h2>
                <div id="gpa-summary">
                    <div style="font-size: 1.5rem; color: var(--accent);" class="monospace">CGPA: <span id="gpa-val">0.00</span></div>
                    <div style="color: var(--dim); font-size: 0.9rem; margin-top: 5px;">Credits: <span id="gpa-credits">0.0</span></div>
                </div>
            </div>
        </div>
    </div>

    <footer>
        Last updated: <span id="update-ts">Never</span> | PRIMERS OS Intelligence Layer
    </footer>

    <script>
        function updateClock() {
            const now = new Date();
            document.getElementById('live-clock').innerText = now.toLocaleTimeString();
        }
        setInterval(updateClock, 1000);
        updateClock();

        async function refresh() {
            try {
                const [status, procs, threats, network, gpa] = await Promise.all([
                    fetch('/api/status').then(r => r.json()),
                    fetch('/api/processes').then(r => r.json()),
                    fetch('/api/threats').then(r => r.json()),
                    fetch('/api/network').then(r => r.json()),
                    fetch('/api/gpa').then(r => r.json())
                ]);

                // Stats Row
                document.getElementById('stat-cpu').innerText = status.cpu.toFixed(1) + '%';
                document.getElementById('stat-mem').innerText = status.memory_percent.toFixed(1) + '%';
                document.getElementById('stat-proc').innerText = status.processes;
                document.getElementById('stat-uptime').innerText = status.uptime;

                // Process Table
                const tbody = document.querySelector('#proc-table tbody');
                tbody.innerHTML = procs.map(p => `
                    <tr>
                        <td class="monospace">${p.pid}</td>
                        <td>${p.name}</td>
                        <td class="monospace">${p.cpu.toFixed(1)}%</td>
                        <td class="monospace">${p.memory.toFixed(1)}%</td>
                        <td>${p.status}</td>
                    </tr>
                `).join('');

                // Security Events
                const secList = document.getElementById('security-list');
                secList.innerHTML = threats.map(t => {
                    const level = t.level.toLowerCase();
                    return `
                        <div style="margin-bottom: 10px; border-bottom: 1px solid #222; padding-bottom: 5px;">
                            <span class="badge badge-${level}">${t.level}</span>
                            <span style="font-size: 0.85rem;">${t.description}</span>
                            <div style="font-size: 0.7rem; color: var(--dim);">${new Date(t.timestamp * 1000).toLocaleTimeString()}</div>
                        </div>
                    `;
                }).join('') || '<div style="color:var(--dim);">No recent threats.</div>';

                // Network
                const netSummary = document.getElementById('network-summary');
                const states = {};
                network.forEach(n => { states[n.status] = (states[n.status] || 0) + 1; });
                document.getElementById('net-total').innerText = network.length;
                
                let netHtml = `<div class="net-tag">Total: <span>${network.length}</span></div>`;
                for (const [state, count] of Object.entries(states)) {
                    netHtml += `<div class="net-tag">${state}: <span>${count}</span></div>`;
                }
                netSummary.innerHTML = netHtml;

                // GPA
                document.getElementById('gpa-val').innerText = gpa.cgpa.toFixed(2);
                document.getElementById('gpa-credits').innerText = gpa.credits.toFixed(1);

                document.getElementById('update-ts').innerText = new Date().toLocaleTimeString();
            } catch (err) {
                console.error("Dashboard refresh failed", err);
            }
        }

        setInterval(refresh, 5000);
        refresh();
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/status')
def get_status():
    snap = monitor.get_summary() if monitor else {}
    uptime = kernel.get_uptime() if kernel else {"formatted": "0s"}
    return jsonify({
        "cpu": float(snap.get("cpu", "0").split()[0]),
        "memory_percent": float(snap.get("memory", "0").split()[0]),
        "processes": snap.get("processes", 0),
        "uptime": uptime["formatted"],
        "kernel_version": kernel.get_kernel_version() if kernel else "Unknown"
    })

@app.route('/api/processes')
def get_processes():
    procs = manager.list_processes(sort_by="cpu", limit=20) if manager else []
    return jsonify([{"pid": p.pid, "name": p.name, "cpu": p.cpu, "memory": p.memory, "status": p.status} for p in procs])

@app.route('/api/threats')
def get_threats():
    events = security.get_events(min_level="LOW") if security else []
    return jsonify([{
        "level": e.level,
        "description": e.description,
        "timestamp": e.timestamp
    } for e in events[-10:]])

@app.route('/api/network')
def get_network():
    conns = security.scan_connections() if security else []
    return jsonify(conns)

@app.route('/api/gpa')
def get_gpa():
    if gpa_service:
        report = gpa_service.get_report()
        return jsonify({"cgpa": report["cgpa"], "credits": report["total_credits"]})
    return jsonify({"cgpa": 0.0, "credits": 0.0})

def run_server(host='0.0.0.0', port=5000):
    app.run(host=host, port=port, debug=False, use_reloader=False)

def start_gui(system_monitor, process_manager, security_engine):
    global monitor, manager, security, kernel, gpa_service
    monitor = system_monitor
    manager = process_manager
    security = security_engine
    kernel = KernelInterface()
    gpa_service = GPAService()
    
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    logger.info("GUI Dashboard started at http://localhost:5000")
    return thread

if __name__ == "__main__":
    # Standalone mode: initialize its own components
    monitor = SystemMonitor()
    manager = ProcessManager()
    security = SecurityEngine()
    kernel = KernelInterface()
    gpa_service = GPAService()
    
    monitor.start()
    security.start()
    
    run_server()
