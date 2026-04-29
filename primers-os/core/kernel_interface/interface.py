import os
import platform
import time
import psutil
from typing import Dict, List, Optional
from utils.logger import PrimersLogger

class KernelInterface:
    """
    Linux kernel interface wrapper.
    Reads from /proc for CPU, Memory, Load, Uptime, Version, and Network stats.
    Includes fallbacks for non-Linux systems.
    """

    def __init__(self):
        self.logger = PrimersLogger.get_logger("kernel_interface")
        self.is_linux = platform.system() == "Linux"

    def get_cpu_info(self) -> dict:
        """Reads /proc/cpuinfo or provides psutil fallback."""
        info = {"model": "Unknown", "cores": 0, "mhz": 0.0, "flags": []}
        
        if self.is_linux:
            try:
                with open("/proc/cpuinfo", "r") as f:
                    cores = 0
                    for line in f:
                        if ":" in line:
                            key, val = [part.strip() for part in line.split(":", 1)]
                            if key == "model name":
                                info["model"] = val
                            elif key == "cpu MHz":
                                info["mhz"] = float(val)
                            elif key == "flags":
                                info["flags"] = val.split()[:10]
                            elif key == "processor":
                                cores += 1
                    info["cores"] = cores
            except Exception as e:
                self.logger.error(f"Failed to read /proc/cpuinfo: {e}")
        
        # Fallback/Enhancement with psutil
        if info["cores"] == 0:
            info["cores"] = psutil.cpu_count(logical=False) or 0
        if info["mhz"] == 0.0:
            info["mhz"] = psutil.cpu_freq().current if psutil.cpu_freq() else 0.0
        if info["model"] == "Unknown":
            info["model"] = platform.processor() or "Unknown"
            
        return info

    def get_mem_info(self) -> dict:
        """Reads /proc/meminfo (values in MB)."""
        info = {"MemTotal": 0, "MemFree": 0, "MemAvailable": 0, "SwapTotal": 0, "SwapFree": 0}
        
        if self.is_linux:
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if ":" in line:
                            key, val = [part.strip() for part in line.split(":", 1)]
                            if key in info:
                                # Values are in kB, convert to MB
                                kb_val = int(val.split()[0])
                                info[key] = kb_val // 1024
            except Exception as e:
                self.logger.error(f"Failed to read /proc/meminfo: {e}")
        else:
            # Fallback for Windows
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            info = {
                "MemTotal": mem.total // (1024*1024),
                "MemFree": mem.free // (1024*1024),
                "MemAvailable": mem.available // (1024*1024),
                "SwapTotal": swap.total // (1024*1024),
                "SwapFree": swap.free // (1024*1024)
            }
            
        return info

    def get_load(self) -> dict:
        """Reads /proc/loadavg."""
        info = {"load_1min": 0.0, "load_5min": 0.0, "load_15min": 0.0, "running_processes": 0, "total_processes": 0}
        
        if self.is_linux:
            try:
                with open("/proc/loadavg", "r") as f:
                    line = f.read().split()
                    info["load_1min"] = float(line[0])
                    info["load_5min"] = float(line[1])
                    info["load_15min"] = float(line[2])
                    # Format: running/total
                    proc_parts = line[3].split('/')
                    info["running_processes"] = int(proc_parts[0])
                    info["total_processes"] = int(proc_parts[1])
            except Exception as e:
                self.logger.error(f"Failed to read /proc/loadavg: {e}")
        else:
            # psutil fallback (loadavg not directly on Windows psutil, return CPU percent instead?)
            # Actually psutil.getloadavg() is available on Unix, not Windows.
            # On Windows, we'll return 0s or CPU load.
            try:
                if hasattr(psutil, "getloadavg"):
                    load = psutil.getloadavg()
                    info["load_1min"], info["load_5min"], info["load_15min"] = load
                info["total_processes"] = len(psutil.pids())
            except:
                pass
                
        return info

    def get_uptime(self) -> dict:
        """Reads /proc/uptime."""
        uptime_seconds = 0.0
        
        if self.is_linux:
            try:
                with open("/proc/uptime", "r") as f:
                    uptime_seconds = float(f.read().split()[0])
            except Exception as e:
                self.logger.error(f"Failed to read /proc/uptime: {e}")
        else:
            uptime_seconds = time.time() - psutil.boot_time()
            
        days, remainder = divmod(int(uptime_seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        formatted = f"{days}d {hours}h {minutes}m {seconds}s"
        return {"uptime_seconds": uptime_seconds, "formatted": formatted}

    def get_kernel_version(self) -> str:
        """Reads /proc/version or platform release."""
        if self.is_linux:
            try:
                with open("/proc/version", "r") as f:
                    return f.read().strip()
            except Exception as e:
                self.logger.error(f"Failed to read /proc/version: {e}")
        
        return platform.version()

    def get_net_stats(self) -> dict:
        """Reads /proc/net/dev or psutil fallback."""
        interfaces = {}
        
        if self.is_linux:
            try:
                with open("/proc/net/dev", "r") as f:
                    lines = f.readlines()[2:] # Skip headers
                    for line in lines:
                        if ":" in line:
                            parts = line.split()
                            name = parts[0].strip(":")
                            interfaces[name] = {
                                "bytes_recv": int(parts[1]),
                                "packets_recv": int(parts[2]),
                                "bytes_sent": int(parts[9]),
                                "packets_sent": int(parts[10])
                            }
            except Exception as e:
                self.logger.error(f"Failed to read /proc/net/dev: {e}")
        else:
            # psutil fallback
            net_io = psutil.net_io_counters(pernic=True)
            for name, stats in net_io.items():
                interfaces[name] = {
                    "bytes_recv": stats.bytes_recv,
                    "packets_recv": stats.packets_recv,
                    "bytes_sent": stats.bytes_sent,
                    "packets_sent": stats.packets_sent
                }
                
        return {"interfaces": interfaces}

    def get_all(self) -> dict:
        """Aggregates all kernel information."""
        return {
            "cpu": self.get_cpu_info(),
            "memory": self.get_mem_info(),
            "load": self.get_load(),
            "uptime": self.get_uptime(),
            "kernel": self.get_kernel_version(),
            "network": self.get_net_stats()
        }
