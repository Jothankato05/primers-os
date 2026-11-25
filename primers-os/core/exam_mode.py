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
* sessions, pages visited and blocked attempts are logged, durably, to
  /var/log/primers/exam.jsonl (``primers-exam log``; core.exam_log).

The escape routes around the kiosk are closed too (ADR 0003): no text
consoles (Ctrl+Alt+F1..F12, getty), no Ctrl+Alt+Backspace, no Magic SysRq,
no shell, sudo, su or pkexec for the lab account (every polkit action is
denied to it), no DNS of its own (exam servers are pinned in /etc/hosts, so
DNS can't be used as a tunnel), and the clock can't be changed by it.

A power cut or reboot doesn't end an exam (ADR 0004): every lock is a
file on disk, exam.conf is written before the locks and removed after them,
so a PC that loses power while an exam starts or stops comes back locked;
the boot service and every exam sign-in put the firewall back; the boot
menu is locked while an exam runs (no editing, no recovery mode, no other
system); and the exam log is fsync'd entry by entry.

Lab Mode still wipes the account before and after every session, so
nothing carries over from one candidate to the next.
"""

import contextlib
import hashlib
import ipaddress
import json
import os
import re
import secrets
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit

from core import exam_log, lab_mode

CONF = "/etc/primers/exam.conf"
PKLA = "/etc/polkit-1/localauthority/90-mandatory.d/60-primers-exam.pkla"
RULES_FILE = "/run/primers-exam.nft"
EXAM_SHELL = "/usr/lib/primers/exam-shell"
NFT_TABLE = "primers_exam"
HOSTS_BEGIN = "# BEGIN primers-exam: exam servers, pinned while the exam runs (do not edit)"
HOSTS_END = "# END primers-exam"
CONSOLE_UNITS = ("getty@.service", "autovt@.service")

XORG_TEXT = """# Written by primers-exam while an exam runs: no switching to text consoles
# (Ctrl+Alt+F1..F12) and no killing the display (Ctrl+Alt+Backspace).
Section "ServerFlags"
    Option "DontVTSwitch" "true"
    Option "DontZap" "true"
EndSection
"""
SYSCTL_TEXT = "# Written by primers-exam while an exam runs: no Magic SysRq keys.\nkernel.sysrq = 0\n"


@dataclass
class ExamPaths:
    conf: str = CONF
    pkla: str = PKLA
    rules: str = RULES_FILE
    xorg: str = "/etc/X11/xorg.conf.d/90-primers-exam.conf"
    sysctl: str = "/etc/sysctl.d/90-primers-exam.conf"
    hosts: str = "/etc/hosts"
    state: str = "/var/lib/primers/exam"
    exam_shell: str = EXAM_SHELL
    lightdm: str = "/etc/lightdm"
    log: str = exam_log.LOG_PATH
    boot_id: str = exam_log.BOOT_ID
    grub_script: str = "/etc/grub.d/09_primers_exam"
    grub_default: str = "/etc/default/grub.d/90-primers-exam.cfg"
    grub_cfg: str = "/boot/grub/grub.cfg"
    cmdline: str = "/proc/cmdline"


LOG_TAG = exam_log.LOG_TAG
# Addresses an exam server had recently stay allowed this long after DNS
# stops giving them (CDNs move; connections already open must not break)
ADDRESS_GRACE = 3600
MAX_ADDRESSES_PER_HOST = 16
LOG_SERVICE = "primers-exam-log.service"
GRUB_USER = "primers-exam"
GRUB_DEFAULT_TEXT = """# Written by primers-exam while an exam runs. Removed when the exam stops.
# No recovery mode or other systems in the boot menu, and the first entry
# (the normal PRIMERS OS one) is the default.
GRUB_DISABLE_RECOVERY=true
GRUB_DISABLE_OS_PROBER=true
GRUB_DEFAULT=0
"""
WEB_PORTS = (80, 443)

_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")

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


def parse_allow(entry: str) -> Tuple[str, Optional[int]]:
    """An --allow value: host, host:port, an IP address, or [IPv6]:port."""
    text = entry.strip().lower().rstrip(".")
    port = None
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        if rest:
            if not rest.startswith(":"):
                raise ExamError(f"{entry!r} is not a valid server")
            port = rest[1:]
    elif text.count(":") == 1:
        host, port = text.split(":")
    else:
        host = text                     # a name, an IPv4 address or a bare IPv6 address
    host = host.rstrip(".")
    if not valid_host(host):
        raise ExamError(f"{entry!r} is not a valid server name")
    if port is not None:
        if not port.isdigit() or not 0 < int(port) < 65536:
            raise ExamError(f"{entry!r}: the port must be a number from 1 to 65535")
        return host, int(port)
    return host, None


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
    """Firewall for the exam account: the exam servers' web ports and
    nothing else, not even loopback. No DNS of any kind (the local resolver,
    other servers, DNS over TLS on 853, mDNS, LLMNR) and no DNS over HTTPS
    (HTTPS only reaches the exam servers): exam servers are pinned in
    /etc/hosts, so DNS can't be used to tunnel out.

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
        f"    ip daddr @allow4 tcp dport {{ {port_set} }} accept",
        f"    ip6 daddr @allow6 tcp dport {{ {port_set} }} accept",
        "    counter reject",
        "  }",
        "}",
    ]
    return "\n".join(lines) + "\n"


def pkla_text(user: str) -> str:
    """polkit: while an exam runs the exam account may do nothing that needs
    polkit: no USB drives, no pkexec, no clock or time-zone changes, no
    network or power settings."""
    return ("# Written by primers-exam while an exam runs. Removed when the exam stops.\n"
            "[Primers Exam Mode: nothing that needs authorisation]\n"
            f"Identity=unix-user:{user}\n"
            "Action=*\n"
            "ResultAny=no\nResultInactive=no\nResultActive=no\n")


def parse_resolvectl(output: str) -> Addresses:
    """`resolvectl query --legend=no NAME` → addresses."""
    found = Addresses()
    for token in re.findall(r"[0-9A-Fa-f:.]{2,}", output or ""):
        with contextlib.suppress(ValueError):
            ip = ipaddress.ip_address(token)
            (found.v4 if ip.version == 4 else found.v6).add(str(ip))
    return found


def split_hosts(text: str) -> Tuple[str, str]:
    """/etc/hosts → (everything outside our block, our block)."""
    outside, ours, inside = [], [], False
    for line in (text or "").splitlines(keepends=True):
        if line.strip() == HOSTS_BEGIN:
            inside = True
        elif line.strip() == HOSTS_END and inside:
            inside = False
        elif inside:
            ours.append(line)
        else:
            outside.append(line)
    return "".join(outside), "".join(ours)


def static_hosts(text: str, name: str) -> Addresses:
    """Addresses an administrator put in /etc/hosts for `name` (outside our block)."""
    found = Addresses()
    for line in split_hosts(text)[0].splitlines():
        fields = line.split("#", 1)[0].split()
        if len(fields) >= 2 and name in (f.lower() for f in fields[1:]):
            with contextlib.suppress(ValueError):
                ip = ipaddress.ip_address(fields[0])
                (found.v4 if ip.version == 4 else found.v6).add(str(ip))
    return found


AUTOLOGIN_MARK = "#primers-exam# "
_AUTOLOGIN = re.compile(r"^(\s*autologin-user\s*=\s*)(\S+)\s*$")


def suspend_autologin(text: str, allowed_user: str) -> str:
    """Comment out automatic sign-in to any account but the exam account
    (a staff desktop that signs itself in would skip the exam kiosk)."""
    out = []
    for line in text.splitlines(keepends=True):
        m = _AUTOLOGIN.match(line.rstrip("\n"))
        if m and m.group(2) != allowed_user:
            line = AUTOLOGIN_MARK + line
        out.append(line)
    return "".join(out)


def restore_autologin(text: str) -> str:
    return "".join(line[len(AUTOLOGIN_MARK):] if line.startswith(AUTOLOGIN_MARK) else line
                   for line in text.splitlines(keepends=True))


def hosts_text(original: str, pins: Dict[str, Addresses]) -> str:
    """/etc/hosts with our block replaced (or removed when `pins` is empty)."""
    outside = split_hosts(original)[0]
    if outside and not outside.endswith("\n"):
        outside += "\n"
    if not pins:
        return outside
    lines = [HOSTS_BEGIN + "\n"]
    for name in sorted(pins):
        for ip in sorted(pins[name].v4) + sorted(pins[name].v6):
            lines.append(f"{ip}\t{name}\n")
    lines.append(HOSTS_END + "\n")
    return outside + "".join(lines)


# ------------------------------------------------------------------ #
#  Exam Mode
# ------------------------------------------------------------------ #

def grub_password_hash(secret: bytes, salt: bytes, rounds: int = 10000) -> str:
    """The grub-mkpasswd-pbkdf2 form of a password."""
    digest = hashlib.pbkdf2_hmac("sha512", secret, salt, rounds, 64)
    return f"grub.pbkdf2.sha512.{rounds}.{salt.hex().upper()}.{digest.hex().upper()}"


GRUB_SCRIPT = r"""#!/bin/sh
# Written by primers-exam while an exam runs. Removed when the exam stops.
# Locks the boot menu: no editing entries (init=/bin/sh), no GRUB command
# line, no recovery mode or other systems. The password below is random and
# was thrown away; stop the exam to unlock the menu.
set -e
cat <<'END_OF_LOCK'
set superusers="@USER@"
password_pbkdf2 @USER@ @HASH@
END_OF_LOCK
# 10_linux's set-up and its first (normal) entry, bootable without the password
entry=$("$(dirname "$0")/10_linux" | awk '
  !started && /^menuentry / { started = 1; if (!sub(/ --class /, " --unrestricted --class ")) exit 3 }
  { print }
  started { depth += gsub(/{/, "{"); depth -= gsub(/}/, "}"); if (depth == 0) exit }
  END { if (!started) exit 4 }')
if [ -z "$entry" ]; then
  echo "09_primers_exam: no boot entry from 10_linux" >&2
  exit 1
fi
printf '%s\n' "$entry"
"""


def grub_script_text(password_hash: str) -> str:
    """/etc/grub.d/09_primers_exam. With a superuser set, GRUB asks for a
    password before editing an entry, opening its command line or booting
    any entry not marked --unrestricted; the password is random and thrown
    away, so nobody can. The normal entry from 10_linux is repeated first
    with --unrestricted, so the PC still boots on its own; everything after
    it (other kernels, firmware settings) needs the password."""
    if not re.fullmatch(r"grub\.pbkdf2\.sha512\.\d+\.[0-9A-F]+\.[0-9A-F]+", password_hash):
        raise ExamError("bad boot menu password hash")
    return GRUB_SCRIPT.replace("@USER@", GRUB_USER).replace("@HASH@", password_hash)


def _default_run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    # update-grub looks at every disk for other systems: it can take minutes
    timeout = 600 if argv and argv[0] == "update-grub" else 30
    try:
        return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(list(argv), 1, "", str(e))


def _syslog(message: str) -> None:
    import syslog
    syslog.openlog(LOG_TAG, syslog.LOG_PID, syslog.LOG_AUTH)
    syslog.syslog(syslog.LOG_NOTICE, message)


class ExamMode:
    def __init__(self, lab: Optional[lab_mode.LabMode] = None, paths: Optional[ExamPaths] = None,
                 run: Callable[[Sequence[str]], subprocess.CompletedProcess] = _default_run,
                 log: Optional[Callable[[str], None]] = None,
                 is_root: Callable[[], bool] = lambda: os.geteuid() == 0,
                 syslog: Callable[[str], None] = _syslog,
                 clock: Callable[[], float] = time.time):
        self.lab = lab or lab_mode.LabMode()
        self.paths = paths or ExamPaths()
        self.is_root = is_root
        self.run = run
        self.examlog = exam_log.ExamLog(self.paths.log, self.paths.boot_id)
        self.clock = clock
        self.syslog = syslog
        self.log = log or self._log

    def _log(self, message: str) -> None:
        """Durable exam log (fsync'd), and the journal."""
        if self.is_root():
            try:
                self.examlog.log(message)
            except OSError as e:
                self.syslog(f"could not write the exam log {self.paths.log}: {e}")
        self.syslog(message)

    # ---------------- read-only ----------------

    def config(self) -> Optional[ExamConfig]:
        return read_config(self.paths.conf)

    def firewall_active(self) -> bool:
        return self.run(["nft", "list", "table", "inet", NFT_TABLE]).returncode == 0

    def status(self) -> Dict:
        try:
            conf = self.config()
        except ExamError as e:
            return {"active": None, "error": str(e)}
        if conf is None:
            return {"active": False}
        # The firewall and the polkit file can only be checked by root:
        # None means "unknown", never "off".
        root = self.is_root()
        return {"active": True, "url": conf.url, "allow": conf.allow, "ports": conf.ports,
                "started": conf.started, "firewall": self.firewall_active() if root else None,
                "usb_blocked": os.path.exists(self.paths.pkla) if root else None,
                "consoles_locked": (os.path.exists(self.paths.xorg) and os.path.exists(self.paths.sysctl))
                if root else None,
                "boot_menu": self.boot_menu_state() if root else None}

    def live_session(self) -> bool:
        try:
            with open(self.paths.cmdline, encoding="utf-8") as f:
                return "boot=casper" in f.read().split()
        except OSError:
            return False

    def boot_menu_lockable(self) -> bool:
        """Only an installed system's boot menu can be locked (the live USB's
        is on the USB stick)."""
        return os.path.exists(self.paths.grub_cfg) and not self.live_session()

    def boot_menu_state(self) -> str:
        """"locked", "unlocked", or "live" (a live session: can't be locked)."""
        if not self.boot_menu_lockable():
            return "live"
        try:
            with open(self.paths.grub_cfg, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return "unlocked"
        locked = (f'set superusers="{GRUB_USER}"' in text and "--unrestricted" in text
                  and os.path.exists(self.paths.grub_script))
        return "locked" if locked else "unlocked"

    # ---------------- helpers ----------------

    def _read_hosts(self) -> str:
        try:
            with open(self.paths.hosts, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def resolve(self, hosts: Sequence[str]) -> Addresses:
        """Current addresses of the exam servers, from DNS and from the
        administrator's own /etc/hosts entries, never from our pinned block
        (so a server that moves is followed)."""
        found = Addresses()
        hosts_file = self._read_hosts()
        for host in hosts:
            with contextlib.suppress(ValueError):
                ip = ipaddress.ip_address(host)
                (found.v4 if ip.version == 4 else found.v6).add(str(ip))
                continue
            got = parse_resolvectl(self.run(["resolvectl", "query", "--legend=no", "--synthesize=no",
                                             host]).stdout)
            local = static_hosts(hosts_file, host)
            found.v4 |= got.v4 | local.v4
            found.v6 |= got.v6 | local.v6
        return found

    def pinned(self) -> Dict[str, Addresses]:
        """What our /etc/hosts block holds now."""
        out: Dict[str, Addresses] = {}
        for line in split_hosts(self._read_hosts())[1].splitlines():
            fields = line.split()
            if len(fields) >= 2:
                with contextlib.suppress(ValueError):
                    ip = ipaddress.ip_address(fields[0])
                    entry = out.setdefault(fields[1], Addresses())
                    (entry.v4 if ip.version == 4 else entry.v6).add(str(ip))
        return out

    def pins(self, hosts: Sequence[str]) -> Dict[str, Addresses]:
        """Fresh addresses for every exam server name; a name that can't be
        looked up right now keeps the addresses it had (offline, power cut)."""
        previous = self.pinned()
        out = {}
        for host in hosts:
            with contextlib.suppress(ValueError):
                ipaddress.ip_address(host)
                continue                      # an address needs no name lookup
            addrs = self.resolve([host]) or previous.get(host)
            if addrs:
                out[host] = addrs
        return out

    def _seen_path(self) -> str:
        return os.path.join(self.paths.state, "addresses.json")

    def allowed(self, hosts: Sequence[str], pins: Dict[str, Addresses]) -> Addresses:
        """What the firewall lets through: the pinned addresses, plus those
        each server had within the last ADDRESS_GRACE seconds."""
        now = self.clock()
        try:
            with open(self._seen_path(), encoding="utf-8") as f:
                seen = {h: {a: float(t) for a, t in v.items()} for h, v in json.load(f).items()}
        except (OSError, ValueError, AttributeError):
            seen = {}
        for host, addrs in pins.items():
            entry = seen.setdefault(host, {})
            for a in addrs.v4 | addrs.v6:
                entry[a] = now
        kept = {}
        for host in hosts:
            recent = {a: t for a, t in seen.get(host, {}).items() if now - t <= ADDRESS_GRACE}
            newest = sorted(recent.items(), key=lambda kv: kv[1], reverse=True)[:MAX_ADDRESSES_PER_HOST]
            if newest:
                kept[host] = dict(newest)
        os.makedirs(self.paths.state, exist_ok=True)
        lab_mode._atomic_write(self._seen_path(), json.dumps(kept, sort_keys=True), 0o600)
        out = self.addresses(hosts, pins)
        for addrs in kept.values():
            for a in addrs:
                (out.v6 if ":" in a else out.v4).add(a)
        return out

    @staticmethod
    def addresses(hosts: Sequence[str], pins: Dict[str, Addresses]) -> Addresses:
        found = Addresses()
        for host in hosts:
            with contextlib.suppress(ValueError):
                ip = ipaddress.ip_address(host)
                (found.v4 if ip.version == 4 else found.v6).add(str(ip))
                continue
            if host in pins:
                found.v4 |= pins[host].v4
                found.v6 |= pins[host].v6
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

    def _checked(self, argv: Sequence[str], what: str) -> None:
        result = self.run(argv)
        if result.returncode != 0:
            raise ExamError(f"could not {what}: " + (result.stderr or result.stdout or "failed").strip())

    def _apply_firewall(self, uid: int, addrs: Addresses, ports: Sequence[int]) -> None:
        os.makedirs(os.path.dirname(self.paths.rules), exist_ok=True)
        with open(self.paths.rules, "w", encoding="utf-8") as f:
            f.write(nft_ruleset(uid, addrs, ports))
        self._checked(["nft", "-f", self.paths.rules], "set up the exam firewall")

    def _remove_firewall(self) -> None:
        if self.firewall_active():
            self.run(["nft", "delete", "table", "inet", NFT_TABLE])

    def _pin_hosts(self, pins: Dict[str, Addresses]) -> None:
        original = self._read_hosts()
        text = hosts_text(original, pins)
        if text != original:
            lab_mode._atomic_write(self.paths.hosts, text)

    def _lock(self, acct: lab_mode.Account, conf: ExamConfig, addrs: Addresses) -> None:
        """Everything that closes the escape routes. Idempotent: run at
        start, at boot and before every exam session."""
        self._apply_firewall(acct.uid, addrs, conf.ports)
        lab_mode._atomic_write(self.paths.pkla, pkla_text(acct.name))
        # Text consoles: no VT switching or display kill in X, no gettys,
        # no Magic SysRq. Files persist, so they hold after a power cut too.
        lab_mode._atomic_write(self.paths.xorg, XORG_TEXT)
        lab_mode._atomic_write(self.paths.sysctl, SYSCTL_TEXT)
        self._checked(["sysctl", "-q", "-w", "kernel.sysrq=0"], "turn off Magic SysRq")
        self._checked(["systemctl", "mask", *CONSOLE_UNITS], "turn off the text consoles")
        # The login screen must come up: no automatic sign-in to a desktop
        self._rewrite_lightdm(lambda text: suspend_autologin(text, acct.name))
        # No shell for the exam account
        if self._shell(acct.name) != self.paths.exam_shell:
            os.makedirs(self.paths.state, exist_ok=True)
            saved = os.path.join(self.paths.state, "shell")
            if not os.path.exists(saved):
                lab_mode._atomic_write(saved, (self._shell(acct.name) or "/bin/bash") + "\n", 0o600)
            self._checked(["usermod", "--shell", self.paths.exam_shell, acct.name],
                          "take the shell away from the exam account")
        self._lock_boot_menu()
        # The candidate's events (kiosk, session) go to the durable log too
        self._checked(["systemctl", "start", LOG_SERVICE], "start the exam log writer")

    def _lock_boot_menu(self) -> None:
        if not self.boot_menu_lockable():
            return
        changed = False
        script = None
        with contextlib.suppress(OSError):
            with open(self.paths.grub_script, encoding="utf-8") as f:
                script = f.read()
        if not script or f"password_pbkdf2 {GRUB_USER} grub.pbkdf2." not in script:
            password = grub_password_hash(secrets.token_bytes(32), secrets.token_bytes(64))
            lab_mode._atomic_write(self.paths.grub_script, grub_script_text(password), 0o755)
            changed = True
        try:
            with open(self.paths.grub_default, encoding="utf-8") as f:
                current = f.read()
        except OSError:
            current = None
        if current != GRUB_DEFAULT_TEXT:
            lab_mode._atomic_write(self.paths.grub_default, GRUB_DEFAULT_TEXT)
            changed = True
        if changed or self.boot_menu_state() != "locked":
            self._checked(["update-grub"], "lock the boot menu")
            if self.boot_menu_state() != "locked":
                raise ExamError("the boot menu did not lock (update-grub ran, but "
                                f"{self.paths.grub_cfg} has no password)")

    def _unlock_boot_menu(self) -> List[str]:
        removed = False
        for path in (self.paths.grub_script, self.paths.grub_default):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)
                removed = True
        if removed and os.path.exists(self.paths.grub_cfg) and not self.live_session():
            if self.run(["update-grub"]).returncode != 0:
                return ["could not unlock the boot menu: run sudo update-grub"]
        return []

    def _lightdm_files(self) -> List[str]:
        files = [os.path.join(self.paths.lightdm, "lightdm.conf")]
        confd = os.path.join(self.paths.lightdm, "lightdm.conf.d")
        with contextlib.suppress(OSError):
            files += sorted(os.path.join(confd, f) for f in os.listdir(confd) if f.endswith(".conf"))
        return [f for f in files if os.path.isfile(f)]

    def _rewrite_lightdm(self, change: Callable[[str], str]) -> None:
        for path in self._lightdm_files():
            with open(path, encoding="utf-8") as f:
                text = f.read()
            new = change(text)
            if new != text:
                lab_mode._atomic_write(path, new)

    def _shell(self, user: str) -> Optional[str]:
        line = self.run(["getent", "passwd", user]).stdout.strip()
        return line.split(":")[6] if line.count(":") >= 6 else None

    def _unlock(self, user: Optional[str]) -> List[str]:
        """Undo every lock. exam.conf goes last, so a stop cut short by a
        power cut leaves an exam that is still on (and can be stopped again)."""
        warnings = []
        for path in (self.paths.pkla, self.paths.xorg, self.paths.sysctl):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)
        warnings += self._unlock_boot_menu()
        self._remove_firewall()
        self._pin_hosts({})
        self._rewrite_lightdm(restore_autologin)
        self.run(["systemctl", "unmask", *CONSOLE_UNITS])
        self.run(["sysctl", "-q", "--system"])
        self.run(["systemctl", "start", "getty@tty1.service"])
        saved = os.path.join(self.paths.state, "shell")
        if user:
            shell = "/bin/bash"
            with contextlib.suppress(OSError):
                with open(saved, encoding="utf-8") as f:
                    shell = f.read().strip() or shell
            if shell == self.paths.exam_shell:
                shell = "/bin/bash"
            if self.run(["usermod", "--shell", shell, user]).returncode != 0:
                warnings.append(f"could not give the shell back to '{user}'")
        with contextlib.suppress(FileNotFoundError):
            os.unlink(saved)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._seen_path())
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.paths.conf)
        lab_mode.sync_dir(os.path.dirname(self.paths.conf))
        return warnings

    def _stop_idle_consoles(self) -> None:
        """Stop the login prompts on text consoles nobody is signed in on (a
        staff member's own console session is left alone)."""
        busy = set()
        for line in self.run(["loginctl", "list-sessions", "--no-legend"]).stdout.splitlines():
            sid = line.split()[0] if line.split() else ""
            if sid:
                tty = self.run(["loginctl", "show-session", sid, "-p", "TTY", "--value"]).stdout.strip()
                if tty:
                    busy.add(tty)
        units = self.run(["systemctl", "list-units", "--plain", "--no-legend", "--state=active",
                          "getty@*.service", "autovt@*.service"]).stdout
        for line in units.splitlines():
            unit = line.split()[0] if line.split() else ""
            tty = unit.split("@", 1)[1].rsplit(".", 1)[0] if "@" in unit else ""
            if tty and tty not in busy:
                self.run(["systemctl", "stop", unit])

    def _desktop_sessions(self) -> int:
        """Desktop sessions of real users on this PC (not the login screen)."""
        listing = self.run(["loginctl", "list-sessions", "--no-legend"]).stdout
        count = 0
        for line in listing.splitlines():
            sid = line.split()[0] if line.split() else ""
            if not sid:
                continue
            props = self.run(["loginctl", "show-session", sid, "-p", "Class", "-p", "Type",
                              "-p", "State"]).stdout
            if "Class=user" in props and ("Type=x11" in props or "Type=wayland" in props) \
                    and "State=closing" not in props:
                count += 1
        return count

    def _restart_login_screen(self) -> List[str]:
        """The login screen's display picks up the console lock when it
        starts. Restart it now unless someone is using this PC's desktop."""
        if self._desktop_sessions():
            return ["sign out of the desktop on this PC so the login screen restarts locked "
                    "(until then Ctrl+Alt+F1..F12 still works there)"]
        self.run(["systemctl", "restart", "display-manager.service"])
        return []

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
        extra_ports = set()
        for extra in allow:
            name, extra_port = parse_allow(extra)
            if name not in hosts:
                hosts.append(name)
            if extra_port:
                extra_ports.add(extra_port)
        acct = self._lab_account()
        if not self.resolve([host]):
            raise ExamError(f"can't find the exam server {host}: check the address and the network")
        pins = self.pins(hosts)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self._seen_path())        # nothing carried over from an earlier exam
        addrs = self.allowed(hosts, pins)
        ports = sorted(set(WEB_PORTS) | {port} | extra_ports)
        started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        conf = ExamConfig(url.strip(), hosts, ports, started)
        self._check_log()
        try:
            # exam.conf first: from here on, a power cut brings the PC back
            # with the exam on, and the boot service puts every lock in place
            lab_mode._atomic_write(self.paths.conf, config_text(conf))
            self._lock(acct, conf, addrs)
            self._pin_hosts(pins)
        except (ExamError, OSError):
            self._unlock(acct.name)
            raise
        os.sync()
        self._stop_idle_consoles()
        warnings = self._end_lab_sessions("exam-start")
        warnings += self._restart_login_screen()
        unresolved = [h for h in hosts[1:] if not self.resolve([h])]
        if unresolved:
            warnings.append("not found, so not reachable during the exam: " + ", ".join(unresolved))
        self.log(f"exam started: {conf.url} (servers: {', '.join(hosts)}; account {acct.name})")
        return conf, warnings

    def stop(self) -> List[str]:
        try:
            conf = self.config()
        except ExamError:
            conf = ExamConfig("damaged", [], [])
        if conf is None:
            raise ExamError("no exam is running")
        user = None
        with contextlib.suppress(lab_mode.LabError):
            labconf = self.lab.config()
            user = labconf.user if labconf else None
        warnings = self._unlock(user)
        os.sync()
        warnings += self._end_lab_sessions("exam-stop")
        self.log(f"exam stopped: {conf.url}")
        return warnings

    def _check_log(self) -> None:
        """The exam log must be writable before an exam starts."""
        try:
            os.makedirs(os.path.dirname(self.paths.log), mode=0o750, exist_ok=True)
            fd = os.open(self.paths.log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o640)
            os.close(fd)
        except OSError as e:
            raise ExamError(f"can't write the exam log {self.paths.log}: {e}")

    def refresh(self, addresses_only: bool = False) -> bool:
        """Re-apply every lock with fresh addresses (boot, every exam sign-in),
        or, with addresses_only (the primers-exam-refresh timer, every few
        minutes), just follow exam servers whose addresses changed.

        Returns False when no exam is running. Raises ExamError when an exam
        is running but the locks can't be put in place.
        """
        conf = self.config()
        if conf is None:
            return False
        acct = self._lab_account()
        before = self.pinned()
        fresh = self.resolve(conf.allow)
        pins = self.pins(conf.allow)
        if not fresh:
            self.log("exam servers not found (offline?); using their last known addresses")
        self._pin_hosts(pins)
        addrs = self.allowed(conf.allow, pins)
        changed = {h: sorted((pins[h].v4 | pins[h].v6) - (before.get(h, Addresses()).v4 | before.get(h, Addresses()).v6))
                   for h in pins}
        changed = {h: a for h, a in changed.items() if a and h in before}
        for host, new in changed.items():
            self.log(f"exam server {host} moved: now also {', '.join(new)} "
                     f"(earlier addresses stay allowed for {ADDRESS_GRACE // 60} minutes)")
        if addresses_only:
            rules = nft_ruleset(acct.uid, addrs, conf.ports)
            try:
                with open(self.paths.rules, encoding="utf-8") as f:
                    current = f.read()
            except OSError:
                current = ""
            if rules != current or not self.firewall_active():
                self._apply_firewall(acct.uid, addrs, conf.ports)
            return True
        # No addresses at all (never resolved): everything is blocked
        self._lock(acct, conf, addrs)
        self._stop_idle_consoles()
        return True

    def journal(self, since: Optional[str] = None, everything: bool = False) -> str:
        """The exam log (root, or the adm group). By default the current
        exam, or the last one when none is running."""
        if not os.path.exists(self.paths.log):
            return ""
        if everything:
            when = None
        elif since:
            when = exam_log.parse_time(since)
            if when is None:
                raise ExamError(f"can't read the time {since!r}: use e.g. 2026-11-25 or '2026-11-25 09:00'")
        else:
            conf = None
            with contextlib.suppress(ExamError):
                conf = self.config()
            when = (exam_log.parse_time(conf.started) if conf and conf.started else None) \
                or self.examlog.last_exam_start()
        records, damaged = self.examlog.since(when)
        out = "".join(exam_log.format_record(r) + "\n" for r in records)
        if damaged:
            out += f"({damaged} damaged line(s) skipped: written when the power went off)\n"
        return out
