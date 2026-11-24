"""
PRIMERS OS — Exam Mode: computer-based tests on lab machines.

Exam Mode runs on top of Lab Mode (the shared, wiped ``lab`` account). While
an exam is on (``sudo primers-exam start https://cbt.example.edu.ng``):

* the lab account's desktop is replaced by the exam kiosk: a bare window
  manager and Primers Lite Bee, full screen, showing only the exam site,
  with no address bar, other programs, downloads or developer tools, and a
  "Finish exam" button that signs the student out
  (/etc/X11/Xsession.d/98primers-exam, /usr/lib/primers/exam-session);
* a firewall table limits that account to the exam server(s) and their
  web ports, whatever program tries to connect (nftables table
  ``inet primers_exam``, separate from ufw so a ufw reload can't drop it);
* USB drives can't be mounted in that account (polkit);
* sessions, pages visited and blocked attempts are logged to the journal
  under ``primers-exam`` (``primers-exam log``).

Lab Mode still wipes the account before and after every session, so
nothing carries over from one candidate to the next.
"""

import contextlib
import ipaddress
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit

from core import lab_mode

CONF = "/etc/primers/exam.conf"
PKLA = "/etc/polkit-1/localauthority/90-mandatory.d/60-primers-exam.pkla"
RULES_FILE = "/run/primers-exam.nft"
NFT_TABLE = "primers_exam"
LOG_TAG = "primers-exam"
WEB_PORTS = (80, 443)

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")

USB_ACTIONS = (
    "org.freedesktop.udisks2.filesystem-mount",
    "org.freedesktop.udisks2.filesystem-mount-other-seat",
    "org.freedesktop.udisks2.filesystem-mount-system",
    "org.freedesktop.udisks2.encrypted-unlock",
    "org.freedesktop.udisks2.loop-setup",
)


class ExamError(Exception):
    """Exam Mode refused or failed to do something; the message says why."""


@dataclass
class ExamConfig:
    url: str
    allow: List[str]
    ports: List[int]
    started: str = ""


@dataclass
class Addresses:
    v4: Set[str] = field(default_factory=set)
    v6: Set[str] = field(default_factory=set)

    def __bool__(self) -> bool:
        return bool(self.v4 or self.v6)


# ------------------------------------------------------------------ #
#  Pure helpers
# ------------------------------------------------------------------ #

def valid_host(host: str) -> bool:
    if not host or len(host) > 253:
        return False
    with contextlib.suppress(ValueError):
        ipaddress.ip_address(host)
        return True
    return all(_LABEL.fullmatch(label) for label in host.split("."))


def parse_exam_url(url: str) -> Tuple[str, str, int]:
    """'https://cbt.uni.edu.ng/test' → ('https', 'cbt.uni.edu.ng', 443)."""
    try:
        parts = urlsplit((url or "").strip())
        port = parts.port
    except ValueError:
        raise ExamError(f"{url!r} is not a web address")
    if parts.scheme not in ("http", "https"):
        raise ExamError("the exam address must start with https:// (or http:// on a local network)")
    host = (parts.hostname or "").lower().rstrip(".")
    if not valid_host(host):
        raise ExamError(f"{url!r} has no valid server name")
    return parts.scheme, host, port or (443 if parts.scheme == "https" else 80)


def read_config(path: str = CONF) -> Optional[ExamConfig]:
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return None
    values: Dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    try:
        url = values["EXAM_URL"]
        parse_exam_url(url)
        allow = values.get("ALLOW", "").split()
        ports = [int(p) for p in values.get("PORTS", "80,443").split(",") if p.strip()]
    except (KeyError, ValueError, ExamError):
        raise ExamError(f"{path} is damaged")
    if not allow or not all(valid_host(h) for h in allow) or not all(0 < p < 65536 for p in ports):
        raise ExamError(f"{path} is damaged")
    return ExamConfig(url, allow, ports, values.get("STARTED", ""))


def config_text(conf: ExamConfig) -> str:
    return ("# Exam Mode, written by primers-exam. Don't edit: use primers-exam start/stop.\n"
            f"EXAM_URL={conf.url}\nALLOW={' '.join(conf.allow)}\n"
            f"PORTS={','.join(str(p) for p in conf.ports)}\nSTARTED={conf.started}\n")


def parse_getent(output: str) -> Addresses:
    """`getent ahosts NAME` → addresses."""
    found = Addresses()
    for line in (output or "").splitlines():
        token = line.split()[0] if line.split() else ""
        with contextlib.suppress(ValueError):
            ip = ipaddress.ip_address(token)
            (found.v4 if ip.version == 4 else found.v6).add(str(ip))
    return found


def nft_ruleset(uid: int, addrs: Addresses, ports: Sequence[int]) -> str:
    """Firewall for the exam account: loopback (DNS via systemd-resolved)
    and the exam servers' web ports; everything else is refused.

    Only packets from the exam account's own sockets are sent to the
    restrictive chain, so nobody else's traffic (and no kernel-generated
    reply, which has no socket) is affected.
    """
    port_set = ", ".join(str(p) for p in sorted(set(ports)))
    lines = [
        f"table inet {NFT_TABLE}",
        f"delete table inet {NFT_TABLE}",
        f"table inet {NFT_TABLE} {{",
        "  set allow4 { type ipv4_addr;" + (f" elements = {{ {', '.join(sorted(addrs.v4))} }};" if addrs.v4 else "") + " }",
        "  set allow6 { type ipv6_addr;" + (f" elements = {{ {', '.join(sorted(addrs.v6))} }};" if addrs.v6 else "") + " }",
        "  chain output {",
        "    type filter hook output priority 0; policy accept;",
        f"    meta skuid {int(uid)} jump exam",
        "  }",
        "  chain exam {",
        '    oifname "lo" accept',
        f"    ip daddr @allow4 tcp dport {{ {port_set} }} accept",
        f"    ip6 daddr @allow6 tcp dport {{ {port_set} }} accept",
        "    counter reject",
        "  }",
        "}",
    ]
    return "\n".join(lines) + "\n"


def pkla_text(user: str) -> str:
    return ("# Written by primers-exam: no USB drives in the exam account while an exam runs.\n"
            "[Primers Exam Mode: no removable drives]\n"
            f"Identity=unix-user:{user}\n"
            f"Action={';'.join(USB_ACTIONS)}\n"
            "ResultAny=no\nResultInactive=no\nResultActive=no\n")


# ------------------------------------------------------------------ #
#  Exam Mode
# ------------------------------------------------------------------ #

def _default_run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(argv), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(list(argv), 1, "", str(e))


def _default_log(message: str) -> None:
    import syslog
    syslog.openlog(LOG_TAG, syslog.LOG_PID, syslog.LOG_AUTH)
    syslog.syslog(syslog.LOG_NOTICE, message)


class ExamMode:
    def __init__(self, lab: Optional[lab_mode.LabMode] = None, conf: str = CONF, pkla: str = PKLA,
                 rules_file: str = RULES_FILE,
                 run: Callable[[Sequence[str]], subprocess.CompletedProcess] = _default_run,
                 log: Callable[[str], None] = _default_log):
        self.lab = lab or lab_mode.LabMode()
        self.conf_path, self.pkla, self.rules_file = conf, pkla, rules_file
        self.run, self.log = run, log

    # ---------------- read-only ----------------

    def config(self) -> Optional[ExamConfig]:
        return read_config(self.conf_path)

    def firewall_active(self) -> bool:
        return self.run(["nft", "list", "table", "inet", NFT_TABLE]).returncode == 0

    def status(self) -> Dict:
        try:
            conf = self.config()
        except ExamError as e:
            return {"active": None, "error": str(e)}
        if conf is None:
            return {"active": False}
        return {"active": True, "url": conf.url, "allow": conf.allow, "ports": conf.ports,
                "started": conf.started, "firewall": self.firewall_active(),
                "usb_blocked": os.path.exists(self.pkla)}

    # ---------------- helpers ----------------

    def resolve(self, hosts: Sequence[str]) -> Addresses:
        found = Addresses()
        for host in hosts:
            with contextlib.suppress(ValueError):
                ip = ipaddress.ip_address(host)
                (found.v4 if ip.version == 4 else found.v6).add(str(ip))
                continue
            got = parse_getent(self.run(["getent", "ahosts", host]).stdout)
            found.v4 |= got.v4
            found.v6 |= got.v6
        return found

    def _lab_account(self) -> lab_mode.Account:
        try:
            labconf = self.lab.config()
        except lab_mode.LabError as e:
            raise ExamError(str(e))
        if labconf is None:
            raise ExamError("Exam Mode runs on the shared lab account: turn on Lab Mode first "
                            "(sudo primers-lab enable, then restart the computer)")
        acct = self.lab.lookup(labconf.user)
        if acct is None:
            raise ExamError(f"the lab account '{labconf.user}' does not exist")
        problems = lab_mode.account_problems(acct, labconf, self.lab.paths.home_root)
        if problems:
            raise ExamError(f"won't use account '{acct.name}': " + "; ".join(problems))
        return acct

    def _apply_firewall(self, uid: int, addrs: Addresses, ports: Sequence[int]) -> None:
        os.makedirs(os.path.dirname(self.rules_file), exist_ok=True)
        with open(self.rules_file, "w", encoding="utf-8") as f:
            f.write(nft_ruleset(uid, addrs, ports))
        result = self.run(["nft", "-f", self.rules_file])
        if result.returncode != 0:
            raise ExamError("could not set up the exam firewall: " +
                            (result.stderr or result.stdout or "nft failed").strip())

    def _remove_firewall(self) -> None:
        if self.firewall_active():
            self.run(["nft", "delete", "table", "inet", NFT_TABLE])

    def _write_pkla(self, user: str) -> None:
        lab_mode._atomic_write(self.pkla, pkla_text(user))

    def _end_lab_sessions(self, reason: str) -> List[str]:
        try:
            self.lab.reset(reason)
            return []
        except (lab_mode.LabError, OSError) as e:
            return [f"could not reset the lab account: {e}"]

    # ---------------- actions ----------------

    def start(self, url: str, allow: Sequence[str] = ()) -> Tuple[ExamConfig, List[str]]:
        """Turn Exam Mode on. Returns the configuration and any warnings."""
        if self.config() is not None:
            raise ExamError("an exam is already running. Stop it first: sudo primers-exam stop")
        scheme, host, port = parse_exam_url(url)
        hosts = [host]
        for extra in allow:
            name = extra.strip().lower().rstrip(".")
            if not valid_host(name):
                raise ExamError(f"{extra!r} is not a valid server name")
            if name not in hosts:
                hosts.append(name)
        acct = self._lab_account()
        addrs = self.resolve(hosts)
        if not self.resolve([host]):
            raise ExamError(f"can't find the exam server {host}: check the address and the network")
        ports = sorted(set(WEB_PORTS) | {port})
        started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        conf = ExamConfig(url.strip(), hosts, ports, started)
        try:
            self._apply_firewall(acct.uid, addrs, ports)
            self._write_pkla(acct.name)
            lab_mode._atomic_write(self.conf_path, config_text(conf))
        except (ExamError, OSError):
            self._undo()
            raise
        warnings = self._end_lab_sessions("exam-start")
        unresolved = [h for h in hosts[1:] if not self.resolve([h])]
        if unresolved:
            warnings.append("not found, so not reachable during the exam: " + ", ".join(unresolved))
        self.log(f"exam started: {conf.url} (servers: {', '.join(hosts)}; account {acct.name})")
        return conf, warnings

    def _undo(self) -> None:
        for path in (self.conf_path, self.pkla):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)
        self._remove_firewall()

    def stop(self) -> List[str]:
        try:
            conf = self.config()
        except ExamError:
            conf = ExamConfig("damaged", [], [])
        if conf is None:
            raise ExamError("no exam is running")
        self._undo()
        warnings = self._end_lab_sessions("exam-stop")
        self.log(f"exam stopped: {conf.url}")
        return warnings

    def refresh(self) -> bool:
        """Re-apply the firewall with fresh addresses (boot, every exam sign-in).

        Returns False when no exam is running. Raises ExamError when an exam
        is running but its firewall can't be put in place.
        """
        conf = self.config()
        if conf is None:
            return False
        acct = self._lab_account()
        addrs = self.resolve(conf.allow)
        if not addrs and self.firewall_active():
            self.log("exam servers not found (offline?); keeping the previous firewall")
        else:
            self._apply_firewall(acct.uid, addrs, conf.ports)   # no addresses: everything blocked
        self._write_pkla(acct.name)
        return True

    def journal(self, since: Optional[str] = None) -> str:
        """The exam log (needs root or the adm group). Defaults to the
        current exam, or today when none is running."""
        conf = None
        with contextlib.suppress(ExamError):
            conf = self.config()
        since = since or (conf.started if conf and conf.started else "today")
        result = self.run(["journalctl", "-t", LOG_TAG, "-o", "short-iso", "--no-pager",
                           "--since", since])
        return result.stdout if result.returncode == 0 else (result.stderr or "")
