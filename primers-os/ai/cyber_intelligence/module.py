import socket
import psutil
import time
from datetime import datetime
from typing import List, Dict, Optional
from utils.logger import PrimersLogger

class CyberIntelligence:
    """
    Strategic cyber intelligence layer (DEFENSIVE ONLY).
    Includes a localhost port scanner and security assessment tools.
    """

    KNOWN_SERVICES = {
        21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
        80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS",
        445: "SMB", 3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
        5900: "VNC", 6379: "Redis", 8080: "HTTP-Alt", 8443: "HTTPS-Alt",
        27017: "MongoDB"
    }

    HIGH_RISK_PORTS = {
        21: "FTP — plaintext credentials",
        23: "Telnet — plaintext, legacy protocol",
        445: "SMB — commonly targeted for ransomware",
        3389: "RDP — primary target for brute force attacks",
        5900: "VNC — often exposed without authentication"
    }

    def __init__(self):
        self.logger = PrimersLogger.get_logger("cyber_intelligence")
        self._last_scan_results = []

    def scan_ports(self, port_range: tuple = (1, 1024), timeout: float = 0.3) -> List[dict]:
        """
        Scan localhost for open ports.
        Returns list of { "port": int, "service": str, "risk": str }
        """
        self.logger.info(f"Scanning ports {port_range[0]}-{port_range[1]} on localhost...")
        open_ports = []
        
        for port in range(port_range[0], port_range[1] + 1):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout)
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        service = self.KNOWN_SERVICES.get(port, "Unknown")
                        risk = "LOW"
                        if port in self.HIGH_RISK_PORTS:
                            risk = "HIGH"
                        elif port in self.KNOWN_SERVICES:
                            risk = "MEDIUM"
                        
                        open_ports.append({
                            "port": port,
                            "service": service,
                            "risk": risk
                        })
            except Exception as e:
                self.logger.error(f"Error scanning port {port}: {e}")
        
        self._last_scan_results = open_ports
        return open_ports

    def fingerprint(self) -> dict:
        """
        Returns summary of open ports.
        """
        if not self._last_scan_results:
            self.scan_ports()
        
        open_ports_list = [res["port"] for res in self._last_scan_results]
        services = [res["service"] for res in self._last_scan_results]
        high_risk_count = sum(1 for res in self._last_scan_results if res["risk"] == "HIGH")
        
        return {
            "open_ports": open_ports_list,
            "high_risk_count": high_risk_count,
            "services_detected": list(set(services))
        }

    def get_report(self) -> dict:
        """
        Generates full security report.
        """
        scan_data = self.fingerprint()
        risk_score = self.get_risk_score()
        
        risk_level = "LOW"
        if risk_score > 75:
            risk_level = "CRITICAL"
        elif risk_score > 50:
            risk_level = "HIGH"
        elif risk_score > 25:
            risk_level = "MEDIUM"
            
        high_risk_ports = [res["port"] for res in self._last_scan_results if res["risk"] == "HIGH"]
        
        return {
            "scan_time": datetime.now().isoformat(),
            "hostname": socket.gethostname(),
            "open_ports": self._last_scan_results,
            "high_risk_ports": high_risk_ports,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "recommendations": self.get_recommendations()
        }

    def get_risk_score(self) -> int:
        """
        Calculates risk score 0-100.
        +20 per high-risk, +5 per medium-risk.
        """
        score = 0
        for res in self._last_scan_results:
            if res["risk"] == "HIGH":
                score += 20
            elif res["risk"] == "MEDIUM":
                score += 5
        
        return min(100, score)

    def get_recommendations(self) -> List[str]:
        """
        Returns human-readable security advice.
        """
        recommendations = []
        for res in self._last_scan_results:
            port = res["port"]
            if port == 21:
                recommendations.append("Disable FTP — use SFTP instead.")
            elif port == 23:
                recommendations.append("Disable Telnet — use SSH instead.")
            elif port == 445:
                recommendations.append("Close SMB (Port 445) unless absolutely necessary for file sharing.")
            elif port == 3389:
                recommendations.append("Secure RDP (Port 3389) with MFA or a VPN.")
            elif port == 5900:
                recommendations.append("Disable VNC (Port 5900) or tunnel it over SSH.")
        
        if not recommendations and self._last_scan_results:
            recommendations.append("Review all open ports and ensure they are necessary for system operation.")
        elif not self._last_scan_results:
            recommendations.append("Run a port scan to identify potential vulnerabilities.")
            
        return recommendations
