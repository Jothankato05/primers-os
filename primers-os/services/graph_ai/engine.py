import psutil
import socket
import json
import os
from typing import Dict, List, Set, Optional
from utils.logger import PrimersLogger

class GraphAIEngine:
    """
    Network topology mapper and graph intelligence engine.
    Builds a graph of local host connections to remote IPs.
    """

    def __init__(self):
        self.logger = PrimersLogger.get_logger("graph_ai")
        self._graph = {"nodes": {}, "edges": []}
        self.hostname = socket.gethostname()
        try:
            self.local_ip = socket.gethostbyname(self.hostname)
        except:
            self.local_ip = "127.0.0.1"
        
    def scan(self) -> dict:
        """
        Scan active connections and build the graph dict.
        Returns the graph dict.
        """
        nodes = {}
        edges = []
        
        # 1. Add local host as a node
        nodes[self.hostname] = {"id": self.hostname, "type": "local_host", "connections": 0}
        
        # 2. Identify local interfaces
        try:
            addrs = psutil.net_if_addrs()
            for nic, snics in addrs.items():
                for addr in snics:
                    if addr.family == socket.AF_INET:
                        nodes[addr.address] = {"id": addr.address, "type": "interface", "connections": 0}
        except Exception as e:
            self.logger.error(f"Failed to scan interfaces: {e}")

        # 3. Scan connections
        try:
            connections = psutil.net_connections(kind='inet')
            for conn in connections:
                laddr = f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "unknown"
                raddr_ip = conn.raddr.ip if conn.raddr else None
                raddr_port = conn.raddr.port if conn.raddr else None
                
                if raddr_ip:
                    # Add remote node if not exists
                    if raddr_ip not in nodes:
                        nodes[raddr_ip] = {"id": raddr_ip, "type": "remote_host", "connections": 0}
                    
                    nodes[raddr_ip]["connections"] += 1
                    
                    # Update source node connection count
                    src_id = self.hostname # default
                    if conn.laddr and conn.laddr.ip in nodes:
                        src_id = conn.laddr.ip
                    
                    if src_id in nodes:
                        nodes[src_id]["connections"] += 1
                    
                    # Add edge
                    edges.append({
                        "from": src_id,
                        "to": raddr_ip,
                        "port": raddr_port,
                        "status": conn.status,
                        "pid": conn.pid
                    })
        except Exception as e:
            self.logger.error(f"Network scan failed: {e}")

        self._graph = {"nodes": nodes, "edges": edges}
        return self._graph

    def build_graph(self) -> None:
        """Calls scan() and stores result internally."""
        self.scan()

    def detect_anomalies(self) -> List[dict]:
        """
        Analyses self._graph for anomalies.
        """
        anomalies = []
        if not self._graph["nodes"]:
            return anomalies

        # 1. High degree anomaly (> 20 connections)
        for node_id, node in self._graph["nodes"].items():
            if node["connections"] > 20:
                anomalies.append({
                    "type": "High Degree Anomaly",
                    "node": node_id,
                    "detail": f"Node has {node['connections']} active connections.",
                    "severity": "HIGH"
                })

        # 2. Multiple connections to same remote IP on different ports
        remote_ip_ports = {}
        for edge in self._graph["edges"]:
            remote_ip = edge["to"]
            port = edge["port"]
            if remote_ip not in remote_ip_ports:
                remote_ip_ports[remote_ip] = set()
            remote_ip_ports[remote_ip].add(port)
        
        for ip, ports in remote_ip_ports.items():
            if len(ports) > 5:
                anomalies.append({
                    "type": "Port Sweep Detection",
                    "node": ip,
                    "detail": f"Multiple connections ({len(ports)}) to different ports on same IP.",
                    "severity": "MEDIUM"
                })

        # 3. Connections to ports < 1024 from non-system processes
        # On many systems, system PIDs are small or specific. 
        # We'll check if PID > 1000 for ports < 1024 as a heuristic.
        for edge in self._graph["edges"]:
            if edge["port"] and edge["port"] < 1024:
                pid = edge.get("pid")
                if pid and pid > 1000:
                    # Simple heuristic: non-root/non-system process using privileged port
                    anomalies.append({
                        "type": "Privileged Port Usage",
                        "node": edge["to"],
                        "detail": f"Process (PID {pid}) connected to privileged port {edge['port']}.",
                        "severity": "MEDIUM"
                    })

        return anomalies

    def render_ascii(self) -> str:
        """Returns a multi-line ASCII string representing the graph."""
        if not self._graph["edges"]:
            return f"[LOCAL HOST: {self.hostname}]\n  └── (No active connections)"

        lines = [f"[LOCAL HOST: {self.hostname}]"]
        
        # Group edges by remote IP for cleaner rendering
        remote_edges = {}
        for edge in self._graph["edges"]:
            if edge["to"] not in remote_edges:
                remote_edges[edge["to"]] = []
            remote_edges[edge["to"]].append(edge)

        items = list(remote_edges.items())
        for i, (ip, edges) in enumerate(items):
            char = "└──" if i == len(items) - 1 else "├──"
            for j, edge in enumerate(edges):
                # Try to get process name if PID available
                proc_name = "unknown"
                if edge.get("pid"):
                    try:
                        proc_name = psutil.Process(edge["pid"]).name()
                    except:
                        pass
                
                status = edge["status"]
                port = edge["port"]
                lines.append(f"  {char} {ip}:{port} ({status}) [{proc_name}]")
                # Subsequent connections to same IP use same prefix but indented
                char = "   " 

        return "\n".join(lines)

    def export_json(self) -> str:
        """Returns JSON string of self._graph."""
        return json.dumps(self._graph, indent=2)

    def get_stats(self) -> dict:
        """Returns node/edge counts and top remote IPs."""
        node_count = len(self._graph["nodes"])
        edge_count = len(self._graph["edges"])
        anomalies = self.detect_anomalies()
        
        # Top remote IPs
        remote_counts = {}
        for edge in self._graph["edges"]:
            ip = edge["to"]
            remote_counts[ip] = remote_counts.get(ip, 0) + 1
        
        top_ips = sorted(remote_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            "node_count": node_count,
            "edge_count": edge_count,
            "anomaly_count": len(anomalies),
            "top_remote_ips": [f"{ip} ({count})" for ip, count in top_ips]
        }
