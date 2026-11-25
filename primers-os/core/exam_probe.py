"""
PRIMERS OS — ``primers-exam probe URL``: which servers does an exam site need?

Exam sites (Moodle, TCExam and the rest) often load scripts, styles, fonts
or a login page from other servers. Exam Mode only lets the candidate reach
the servers on its allow list, so a missing one breaks the exam in the
middle of it. The probe opens the exam site in Lite Bee's probe window
(``lite-bee --probe``) with a throw-away profile; staff sign in with a test
account and go through a practice exam; then the probe reports every server
the site used, its addresses (IPv4 and IPv6), whether each port answers
from this PC, and the exact ``primers-exam start`` command for it.

It runs as the person at the desktop, never as root (it opens a browser).
"""

import contextlib
import ipaddress
import json
import os
import socket
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

WEB_PORTS = (80, 443)


@dataclass
class Finding:
    host: str
    ports: List[int]
    schemes: List[str]
    requests: int
    first: str
    main: bool = False
    v4: List[str] = field(default_factory=list)
    v6: List[str] = field(default_factory=list)
    reachable: Dict[int, bool] = field(default_factory=dict)

    @property
    def resolved(self) -> bool:
        return bool(self.v4 or self.v6)

    @property
    def extra_ports(self) -> List[int]:
        return [p for p in self.ports if p not in WEB_PORTS]


@dataclass
class ProbeResult:
    url: str
    findings: List[Finding]
    other_schemes: List[str]
    failed: List[dict]

    @property
    def main(self) -> Optional[Finding]:
        return next((f for f in self.findings if f.main), None)

    def allow_args(self) -> List[str]:
        """--allow values: every server but the exam's own, as host:port for
        each port it uses besides 80/443 (the exam's own server only for a
        port besides the one in its address)."""
        out = []
        for f in self.findings:
            name = f"[{f.host}]" if ":" in f.host else f.host
            extra = [p for p in f.extra_ports if not (f.main and p == _url_port(self.url))]
            if not f.main and not extra:
                out.append(name)
            out += [f"{name}:{p}" for p in extra]
        return out

    def command(self) -> str:
        parts = ["sudo primers-exam start", _quote(self.url)]
        for a in self.allow_args():
            parts += ["--allow", a]
        return " ".join(parts)


def _quote(text: str) -> str:
    return text if all(c.isalnum() or c in ":/._-?=&%~+#[]@" for c in text) else "'" + text.replace("'", "'\\''") + "'"


def _url_port(url: str) -> Optional[int]:
    try:
        parts = urlsplit(url)
        return parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    except ValueError:
        return None


# ------------------------------------------------------------------ #
#  Analysis (resolving and connecting are injected, for tests)
# ------------------------------------------------------------------ #

def system_resolve(host: str) -> Tuple[List[str], List[str]]:
    """IPv4 and IPv6 addresses for a name, from the system's resolver."""
    with contextlib.suppress(ValueError):
        ip = ipaddress.ip_address(host)
        return ([str(ip)], []) if ip.version == 4 else ([], [str(ip)])
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return [], []
    v4 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET})
    v6 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET6})
    return v4, v6


def tcp_open(address: str, port: int, timeout: float = 3.0) -> bool:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    with contextlib.suppress(OSError):
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((address, port))
            return True
    return False


def analyse(report: dict, resolve: Callable[[str], Tuple[List[str], List[str]]] = system_resolve,
            connect: Callable[[str, int], bool] = tcp_open) -> ProbeResult:
    url = report.get("start", "")
    main_host = report.get("main_host", "")
    findings = []
    for host, use in sorted(report.get("hosts", {}).items(), key=lambda kv: (kv[0] != main_host, kv[0])):
        f = Finding(host=host, ports=sorted(int(p) for p in use.get("ports", [])),
                    schemes=list(use.get("schemes", [])), requests=int(use.get("requests", 0)),
                    first=str(use.get("first", "")), main=(host == main_host))
        f.v4, f.v6 = resolve(host)
        for port in f.ports:
            addrs = f.v4 + f.v6
            f.reachable[port] = any(connect(a, port) for a in addrs[:4]) if addrs else False
        findings.append(f)
    return ProbeResult(url, findings, list(report.get("other_schemes", [])), list(report.get("failed", [])))


def format_result(result: ProbeResult) -> str:
    lines = [f"Exam site: {result.url}", ""]
    if not result.findings:
        return "\n".join(lines + ["Nothing was loaded: check the address and the network, then try again.", ""])
    lines.append(f"It used {len(result.findings)} server" + ("" if len(result.findings) == 1 else "s") + ":")
    notes = []
    for f in result.findings:
        addrs = ", ".join(f.v4 + f.v6) or "no address"
        ports = ", ".join(f"{p}{'' if f.reachable.get(p) else ' (no answer)'}" for p in f.ports)
        lines.append(f"  {f.host}{'  (the exam site)' if f.main else ''}")
        lines.append(f"      {f.requests} request(s), {'/'.join(f.schemes)}, port {ports}; {addrs}")
        if not f.resolved:
            notes.append(f"{f.host} can't be found from this PC: it won't work during the exam either.")
        elif f.v6 and not f.v4:
            notes.append(f"{f.host} has only IPv6 addresses: that's fine, the exam firewall covers IPv6.")
        unreachable = [p for p in f.ports if not f.reachable.get(p)]
        if f.resolved and unreachable:
            notes.append(f"{f.host} didn't answer on port {', '.join(map(str, unreachable))} from this PC.")
        if f.extra_ports and not f.main:
            notes.append(f"{f.host} uses port {', '.join(map(str, f.extra_ports))}: included as "
                         f"--allow {f.host}:{f.extra_ports[0]}.")
        if "http" in f.schemes and "https" not in f.schemes:
            notes.append(f"{f.host} is used over plain http (not encrypted).")
        if {"ws", "wss"} & set(f.schemes):
            notes.append(f"{f.host} uses WebSockets ({'/'.join(sorted({'ws', 'wss'} & set(f.schemes)))}).")
    lines.append("")
    if result.failed:
        lines.append(f"{len(result.failed)} load(s) failed, e.g.:")
        for item in result.failed[:5]:
            lines.append(f"  {item.get('uri', '')}: {item.get('error', '')}")
        lines.append("")
    if notes:
        lines.append("Notes:")
        lines += [f"  - {n}" for n in notes]
        lines.append("")
    lines.append("Start the exam with:")
    lines.append(f"  {result.command()}")
    lines.append("")
    lines.append("Only the pages you opened in the probe are counted: go through every kind of page the "
                 "exam uses (sign-in, instructions, questions, review, submit).")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ #
#  Running the probe window
# ------------------------------------------------------------------ #

class ProbeError(Exception):
    pass


def run(url: str, seconds: int = 0, browser: str = "lite-bee",
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> dict:
    """Open the probe window (until Done, closed, or `seconds`) and return its report."""
    if os.geteuid() == 0 and runner is subprocess.run:
        raise ProbeError("run the probe without sudo, from your desktop (it opens a browser window)")
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and runner is subprocess.run:
        raise ProbeError("the probe opens a browser window: run it from a desktop session")
    try:
        scheme = urlsplit(url).scheme
    except ValueError:
        scheme = ""
    if scheme not in ("http", "https"):
        raise ProbeError(f"{url!r} is not a web address (http:// or https://)")
    fd, path = tempfile.mkstemp(prefix="primers-probe-", suffix=".json")
    os.close(fd)
    try:
        argv = [browser, "--probe", url, "--probe-report", path]
        if seconds:
            argv += ["--probe-seconds", str(int(seconds))]
        result = runner(argv)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if not text.strip():
                raise ValueError("empty")
            return json.loads(text)
        except (OSError, ValueError):
            raise ProbeError(f"the probe window didn't report anything (exit {getattr(result, 'returncode', '?')})")
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


def probe(url: str, seconds: int = 0, **kw) -> ProbeResult:
    return analyse(run(url, seconds, **kw))
