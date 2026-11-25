"""
PRIMERS OS — primers-fleet: the invigilator's PC runs exams on the lab PCs.

Each PC has its own key and a self-signed certificate (its identity), made
the first time it is needed. Pairing introduces two PCs once: the
invigilator runs ``primers-fleet pair``, which shows a one-time code; on each
lab PC staff run ``primers-fleet join <invigilator PC> <code>``. The two
exchange certificates, each proving it knows the code (HMAC with a key
stretched from the code by scrypt), so nobody without the code can pair or
sit in the middle. From then on every command travels over TLS 1.3 with
both certificates checked against the paired ones only: a PC that isn't
paired can't be controlled, and a controller that isn't paired can't control
anything. Lab PCs run only a short list of commands (status, start or stop
an exam, hand over the exam log), and both sides write every command and
every refused connection to /var/log/primers/fleet.jsonl (fsync'd).

Decisions: docs/decisions/0006-fleet-control.md.
"""

import contextlib
import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import socketserver
import ssl
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence

FLEET_DIR = "/etc/primers/fleet"
LOG_PATH = "/var/log/primers/fleet.jsonl"
AGENT_PORT = 7480
PAIR_PORT = 7481
PAIR_MINUTES = 15
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"     # no 0/O, 1/I/L: read aloud, typed by hand
CODE_LENGTH = 12                                     # ~59 bits
MAX_PAIR_FAILURES = 5
MAX_LINE = 64 * 1024                                 # a request, or a pairing message
MAX_REPLY = 64 * 1024 * 1024                         # a reply (an exam log)
MAX_LOG_BYTES = 32 * 1024 * 1024
COMMANDS = ("ping", "status", "exam-start", "exam-stop", "exam-log")
EXAM_LOG = "/var/log/primers/exam.jsonl"


class FleetError(Exception):
    pass


# ------------------------------------------------------------------ #
#  Files: identity, paired PCs, trusted controllers, the log
# ------------------------------------------------------------------ #

@dataclass
class FleetPaths:
    root: str = FLEET_DIR
    log: str = LOG_PATH

    @property
    def key(self) -> str:
        return os.path.join(self.root, "identity", "key.pem")

    @property
    def cert(self) -> str:
        return os.path.join(self.root, "identity", "cert.pem")

    @property
    def pcs(self) -> str:
        return os.path.join(self.root, "pcs")

    @property
    def controllers(self) -> str:
        return os.path.join(self.root, "controllers")


def _atomic_write(path: str, data: bytes, mode: int = 0o644) -> None:
    os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    dfd = os.open(os.path.dirname(path), os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def log_event(paths: FleetPaths, event: str, **fields) -> None:
    """One JSON line, appended and fsync'd before returning."""
    record = {"time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
              "event": event, **fields}
    os.makedirs(os.path.dirname(paths.log), exist_ok=True)
    fd = os.open(paths.log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
    try:
        os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def fingerprint(cert_pem: str) -> str:
    """SHA-256 of the certificate, as people compare it: 8 groups of 4."""
    der = ssl.PEM_cert_to_DER_cert(cert_pem)
    digest = hashlib.sha256(der).hexdigest().upper()
    return "-".join(digest[i:i + 4] for i in range(0, 32, 4))


def ensure_identity(paths: FleetPaths, name: Optional[str] = None) -> str:
    """This PC's certificate (PEM), made with a new key the first time."""
    if os.path.exists(paths.cert) and os.path.exists(paths.key):
        with open(paths.cert, encoding="ascii") as f:
            return f.read()
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"primers-fleet {name or socket.gethostname()}"[:64])])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=365 * 30))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, key_cert_sign=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH]),
                           critical=False)
            .sign(key, hashes.SHA256()))
    os.makedirs(os.path.dirname(paths.key), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(paths.key), 0o700)
    _atomic_write(paths.key, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()), 0o600)
    pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    _atomic_write(paths.cert, pem.encode("ascii"))
    return pem


@dataclass
class PC:
    name: str
    address: str
    port: int
    cert: str
    paired_at: str = ""

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.cert)


_NAME = re.compile(r"[^a-z0-9-]+")


def clean_name(name: str) -> str:
    return (_NAME.sub("-", name.lower()).strip("-") or "pc")[:40]


def load_pcs(paths: FleetPaths) -> List[PC]:
    out = []
    with contextlib.suppress(FileNotFoundError):
        for entry in sorted(os.listdir(paths.pcs)):
            if entry.endswith(".json"):
                with open(os.path.join(paths.pcs, entry), encoding="utf-8") as f:
                    d = json.load(f)
                out.append(PC(d["name"], d["address"], int(d.get("port", AGENT_PORT)), d["cert"],
                              d.get("paired_at", "")))
    return out


def save_pc(paths: FleetPaths, pc: PC) -> None:
    _atomic_write(os.path.join(paths.pcs, f"{pc.name}.json"),
                  json.dumps(pc.__dict__, indent=2, sort_keys=True).encode(), 0o600)


def forget_pc(paths: FleetPaths, name: str) -> bool:
    try:
        os.unlink(os.path.join(paths.pcs, f"{clean_name(name)}.json"))
        return True
    except FileNotFoundError:
        return False


def controllers(paths: FleetPaths) -> Dict[str, str]:
    """Certificates of the controllers allowed to control this PC, by fingerprint."""
    out = {}
    with contextlib.suppress(FileNotFoundError):
        for entry in sorted(os.listdir(paths.controllers)):
            if entry.endswith(".pem"):
                with open(os.path.join(paths.controllers, entry), encoding="ascii") as f:
                    pem = f.read()
                out[fingerprint(pem)] = pem
    return out


def trust_controller(paths: FleetPaths, pem: str, address: str = "") -> str:
    fp = fingerprint(pem)
    base = os.path.join(paths.controllers, fp.replace("-", "")[:32])
    _atomic_write(base + ".json", json.dumps({"address": address}).encode())
    _atomic_write(base + ".pem", pem.encode("ascii"))
    return fp


def controller_addresses(paths: FleetPaths) -> List[str]:
    """Where the paired controllers were when they paired (the firewall lets them in)."""
    out = []
    with contextlib.suppress(FileNotFoundError):
        for entry in sorted(os.listdir(paths.controllers)):
            if entry.endswith(".json"):
                with contextlib.suppress(OSError, ValueError):
                    with open(os.path.join(paths.controllers, entry), encoding="utf-8") as f:
                        address = json.load(f).get("address", "")
                    if address and address not in out:
                        out.append(address)
    return out


def forget_controllers(paths: FleetPaths) -> int:
    n = 0
    with contextlib.suppress(FileNotFoundError):
        for entry in os.listdir(paths.controllers):
            os.unlink(os.path.join(paths.controllers, entry))
            n += entry.endswith(".pem")
    return n


# ------------------------------------------------------------------ #
#  Pairing
# ------------------------------------------------------------------ #

def new_code() -> str:
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i:i + 4] for i in range(0, CODE_LENGTH, 4))


def normalise_code(code: str) -> str:
    raw = re.sub(r"[\s-]+", "", code.upper())
    if len(raw) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in raw):
        raise FleetError("that isn't a pairing code (12 letters and digits, like 4KQ7-M2XD-9PTA)")
    return raw


def code_key(code: str) -> bytes:
    """The pairing key: the code stretched by scrypt, so a recorded pairing
    can't be used to guess the code offline."""
    return hashlib.scrypt(normalise_code(code).encode(), salt=b"primers-fleet pairing v1",
                          n=2 ** 14, r=8, p=1, dklen=32)


def _transcript(role: bytes, n_agent: str, n_ctrl: str, agent_pem: str, ctrl_pem: str) -> bytes:
    return b"|".join([b"primers-fleet v1", role, n_agent.encode(), n_ctrl.encode(),
                      fingerprint(agent_pem).encode(), fingerprint(ctrl_pem).encode()])


def _mac(key: bytes, *parts) -> str:
    return hmac.new(key, _transcript(*parts), hashlib.sha256).hexdigest()


def _send(sock, obj) -> None:
    sock.sendall((json.dumps(obj) + "\n").encode())


def _recv(sock, limit: int = MAX_LINE) -> dict:
    buf = bytearray()
    while not buf.endswith(b"\n"):
        chunk = sock.recv(65536)
        if not chunk:
            raise FleetError("the other PC closed the connection")
        buf += chunk
        if len(buf) > limit:
            raise FleetError("message too long")
    try:
        obj = json.loads(buf.decode())
    except ValueError:
        raise FleetError("not a primers-fleet message")
    if not isinstance(obj, dict):
        raise FleetError("not a primers-fleet message")
    return obj


class Pairing:
    """The invigilator's side: accepts lab PCs that know the code, for a while."""

    def __init__(self, paths: FleetPaths, code: str, port: int = PAIR_PORT, host: str = "",
                 on_paired: Callable[[PC], None] = lambda pc: None, on_refused: Callable[[str, str], None] = None):
        self.paths, self.port, self.host = paths, port, host
        self.key = code_key(code)
        self.cert = ensure_identity(paths)
        self.on_paired = on_paired
        self.on_refused = on_refused or (lambda addr, why: None)
        self.failures = 0
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.sock = _listen(host, port)

    def serve(self, seconds: float) -> None:
        deadline = time.time() + seconds
        self.sock.settimeout(1.0)
        try:
            while not self.closed.is_set() and time.time() < deadline:
                try:
                    conn, addr = self.sock.accept()
                except socket.timeout:
                    continue
                threading.Thread(target=self._one, args=(conn, addr[0]), daemon=True).start()
        finally:
            self.sock.close()

    def close(self) -> None:
        self.closed.set()

    def _one(self, conn: socket.socket, addr: str) -> None:
        addr = _plain_address(addr)
        with conn:
            conn.settimeout(20)
            try:
                hello = _recv(conn)
                agent_pem, n_agent = str(hello.get("cert", "")), str(hello.get("nonce", ""))
                if hello.get("type") != "join" or len(n_agent) != 32:
                    raise FleetError("not a join request")
                fingerprint(agent_pem)                       # it parses
                n_ctrl = secrets.token_hex(16)
                _send(conn, {"type": "challenge", "cert": self.cert, "nonce": n_ctrl,
                             "mac": _mac(self.key, b"controller", n_agent, n_ctrl, agent_pem, self.cert)})
                confirm = _recv(conn)
                want = _mac(self.key, b"agent", n_agent, n_ctrl, agent_pem, self.cert)
                if not hmac.compare_digest(str(confirm.get("mac", "")), want):
                    with self.lock:
                        self.failures += 1
                        if self.failures >= MAX_PAIR_FAILURES:
                            self.close()
                    raise FleetError("wrong pairing code")
                with self.lock:
                    pc = self._store(str(hello.get("name", "")), addr, agent_pem)
                _send(conn, {"type": "paired", "name": pc.name})
                log_event(self.paths, "paired", pc=pc.name, address=addr, fingerprint=pc.fingerprint)
                self.on_paired(pc)
            except (FleetError, OSError, ValueError) as e:
                log_event(self.paths, "pairing refused", address=addr, reason=str(e))
                self.on_refused(addr, str(e))
                with contextlib.suppress(OSError):
                    _send(conn, {"type": "refused", "reason": "pairing refused"})

    def _store(self, name: str, address: str, pem: str) -> PC:
        fp = fingerprint(pem)
        existing = {pc.name: pc for pc in load_pcs(self.paths)}
        for pc in existing.values():                 # the same PC again (new address): update it
            if pc.fingerprint == fp:
                pc.address = address
                save_pc(self.paths, pc)
                return pc
        base = clean_name(name)
        final, n = base, 2
        while final in existing:
            final, n = f"{base}-{n}", n + 1
        pc = PC(final, address, AGENT_PORT, pem,
                datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"))
        save_pc(self.paths, pc)
        return pc


def join(paths: FleetPaths, host: str, code: str, port: int = PAIR_PORT, name: Optional[str] = None,
         timeout: float = 30) -> str:
    """The lab PC's side: pair with the invigilator's PC; returns its fingerprint."""
    key = code_key(code)
    mine = ensure_identity(paths)
    n_agent = secrets.token_hex(16)
    with socket.create_connection((host, port), timeout=timeout) as conn:
        conn.settimeout(timeout)
        peer = _plain_address(conn.getpeername()[0])
        _send(conn, {"type": "join", "name": name or socket.gethostname(), "cert": mine, "nonce": n_agent})
        challenge = _recv(conn)
        if challenge.get("type") != "challenge":
            raise FleetError("the invigilator's PC refused: is pairing open, and is the code right?")
        ctrl_pem, n_ctrl = str(challenge.get("cert", "")), str(challenge.get("nonce", ""))
        try:
            want = _mac(key, b"controller", n_agent, n_ctrl, mine, ctrl_pem)
        except ValueError:
            raise FleetError("the other PC sent a broken certificate")
        if not hmac.compare_digest(str(challenge.get("mac", "")), want):
            log_event(paths, "pairing refused", address=host, reason="the other PC doesn't know the code")
            raise FleetError("the other PC doesn't know this code: wrong code, or not the invigilator's PC")
        _send(conn, {"type": "confirm", "mac": _mac(key, b"agent", n_agent, n_ctrl, mine, ctrl_pem)})
        done = _recv(conn)
        if done.get("type") != "paired":
            raise FleetError("the invigilator's PC refused: check the code")
    fp = trust_controller(paths, ctrl_pem, peer)
    log_event(paths, "joined", controller=host, address=peer, fingerprint=fp, name=done.get("name", ""))
    return fp


# ------------------------------------------------------------------ #
#  TLS: both ends checked against the paired certificates only
# ------------------------------------------------------------------ #

def _context(purpose: int, paths: FleetPaths, trusted: Sequence[str]) -> ssl.SSLContext:
    if not trusted:
        raise FleetError("not paired with any PC")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if purpose == ssl.Purpose.CLIENT_AUTH else ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False                  # identity is the pinned certificate, not a name
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cadata="\n".join(trusted))
    ctx.load_cert_chain(paths.cert, paths.key)
    return ctx


def _peer_fingerprint(tls: ssl.SSLSocket) -> str:
    return fingerprint(ssl.DER_cert_to_PEM_cert(tls.getpeercert(binary_form=True)))


def _plain_address(addr: str) -> str:
    with contextlib.suppress(ValueError):
        ip = ipaddress.ip_address(addr)
        if ip.version == 6 and ip.ipv4_mapped:
            return str(ip.ipv4_mapped)
    return addr


def _listen(host: str, port: int) -> socket.socket:
    """A listening socket on every address, IPv4 and IPv6 where there is IPv6."""
    if host:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
    else:
        try:
            sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            host = "::"
        except OSError:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            host = "0.0.0.0"
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(16)
    return sock


# ------------------------------------------------------------------ #
#  The lab PC: run the allowed commands for paired controllers
# ------------------------------------------------------------------ #

def _default_run(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)


class Agent:
    def __init__(self, paths: FleetPaths, port: int = AGENT_PORT, host: str = "",
                 run: Callable[..., subprocess.CompletedProcess] = _default_run,
                 status: Optional[Callable[[], dict]] = None, exam_log: str = EXAM_LOG):
        self.paths, self.port, self.host = paths, port, host
        self.run, self.exam_log = run, exam_log
        self.status_fn = status or local_status
        ensure_identity(paths)
        self.sock = _listen(host, port)
        self.slots = threading.BoundedSemaphore(16)
        self._refusals: Dict[str, float] = {}
        self.stopping = threading.Event()

    @property
    def address(self):
        return self.sock.getsockname()

    def serve_forever(self) -> None:
        self.sock.settimeout(1.0)
        while not self.stopping.is_set():
            try:
                conn, addr = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self.slots.acquire(blocking=False):
                conn.close()
                continue
            threading.Thread(target=self._serve_one, args=(conn, _plain_address(addr[0])), daemon=True).start()

    def stop(self) -> None:
        self.stopping.set()
        with contextlib.suppress(OSError):
            self.sock.close()

    def _refused(self, addr: str, why: str) -> None:
        now = time.time()
        if now - self._refusals.get(addr, 0) >= 60:        # once a minute per address is enough
            self._refusals[addr] = now
            log_event(self.paths, "refused", address=addr, reason=why)

    def _serve_one(self, conn: socket.socket, addr: str) -> None:
        try:
            conn.settimeout(30)
            trusted = controllers(self.paths)
            if not trusted:
                self._refused(addr, "this PC isn't paired with any invigilator PC")
                return
            try:
                tls = _context(ssl.Purpose.CLIENT_AUTH, self.paths, list(trusted.values())).wrap_socket(
                    conn, server_side=True)
            except (ssl.SSLError, OSError) as e:
                self._refused(addr, f"not a paired invigilator PC ({getattr(e, 'reason', None) or e})")
                return
            with tls:
                who = _peer_fingerprint(tls)
                if who not in trusted:                      # belt and braces: the chain was checked
                    self._refused(addr, "not a paired invigilator PC")
                    return
                try:
                    request = _recv(tls)
                    reply = self.handle(request, who, addr)
                except FleetError as e:
                    reply = {"ok": False, "error": str(e)}
                _send(tls, reply)
        finally:
            with contextlib.suppress(OSError):
                conn.close()
            self.slots.release()

    def handle(self, request: dict, who: str, addr: str) -> dict:
        cmd, args = request.get("cmd"), request.get("args") or {}
        if cmd not in COMMANDS or not isinstance(args, dict):
            log_event(self.paths, "command refused", by=who, address=addr, cmd=str(cmd)[:40])
            return {"ok": False, "error": f"unknown command {str(cmd)[:40]!r}"}
        try:
            reply = getattr(self, "_" + cmd.replace("-", "_"))(args)
        except FleetError as e:
            reply = {"ok": False, "error": str(e)}
        logged = {k: v for k, v in args.items() if k in ("url", "allow")}
        log_event(self.paths, "command", by=who, address=addr, cmd=cmd, args=logged, ok=bool(reply.get("ok")),
                  error=reply.get("error", ""))
        return reply

    def _ping(self, args: dict) -> dict:
        return {"ok": True, "name": socket.gethostname()}

    def _status(self, args: dict) -> dict:
        return {"ok": True, "status": self.status_fn()}

    def _exam_start(self, args: dict) -> dict:
        url, allow = args.get("url"), args.get("allow") or []
        if not isinstance(url, str) or not re.match(r"^https?://", url) or len(url) > 2000:
            raise FleetError("the exam address must start with http:// or https://")
        if not isinstance(allow, list) or len(allow) > 50 or not all(isinstance(a, str) and a and
                                                                    not a.startswith("-") for a in allow):
            raise FleetError("bad --allow list")
        argv = ["primers-exam", "start", url]
        for a in allow:
            argv += ["--allow", a]
        return self._primers_exam(argv)

    def _exam_stop(self, args: dict) -> dict:
        return self._primers_exam(["primers-exam", "stop"])

    def _primers_exam(self, argv: List[str]) -> dict:
        try:
            r = self.run(argv, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise FleetError(f"primers-exam didn't run: {e}")
        return {"ok": r.returncode == 0, "rc": r.returncode, "output": (r.stdout + r.stderr)[-4000:],
                **({} if r.returncode == 0 else {"error": (r.stderr or r.stdout).strip()[-500:]})}

    def _exam_log(self, args: dict) -> dict:
        try:
            with open(self.exam_log, "rb") as f:
                data = f.read(MAX_LOG_BYTES + 1)
        except FileNotFoundError:
            data = b""
        if len(data) > MAX_LOG_BYTES:
            raise FleetError("the exam log is too big to send: copy it from the PC")
        return {"ok": True, "log": data.decode("utf-8", "replace"), "sha256": hashlib.sha256(data).hexdigest()}


def local_status() -> dict:
    """What the invigilator sees for this PC."""
    import sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in sys.path:
        sys.path.insert(0, here)
    from core import exam_log, exam_mode, lab_mode
    out = {"name": socket.gethostname()}
    lab_user = lab_mode.DEFAULT_USER
    try:
        lab = lab_mode.LabMode().status()
        out["lab"] = bool(lab.get("enabled"))
        lab_user = lab.get("user") or lab_user
    except Exception as e:                                # noqa: BLE001 - report, don't fail the status
        out["lab"], out["lab_error"] = None, str(e)
    try:
        st = exam_mode.ExamMode().status()
        out["exam"] = bool(st.get("active"))
        out["exam_url"] = st.get("url") or ""
    except Exception as e:                                # noqa: BLE001
        out["exam"], out["exam_error"] = None, str(e)
    try:
        r = subprocess.run(["loginctl", "list-users", "--no-legend"], capture_output=True, text=True, timeout=10)
        out["candidate"] = any(line.split()[1:2] == [lab_user] for line in r.stdout.splitlines())
    except (OSError, subprocess.TimeoutExpired):
        out["candidate"] = None
    try:
        log = exam_log.ExamLog()
        records, _ = log.since(log.last_exam_start())
        out["events"] = len(records)
        if records:
            out["last_event"] = f"{records[-1].time} {records[-1].message}"[:200]
    except Exception:                                     # noqa: BLE001
        out["events"] = None
    return out


# ------------------------------------------------------------------ #
#  The invigilator's PC: send a command to paired PCs
# ------------------------------------------------------------------ #

def call(paths: FleetPaths, pc: PC, cmd: str, args: Optional[dict] = None, timeout: float = 20,
         limit: int = MAX_REPLY) -> dict:
    if cmd not in COMMANDS:
        raise FleetError(f"unknown command {cmd!r}")
    ctx = _context(ssl.Purpose.SERVER_AUTH, paths, [pc.cert])
    try:
        with socket.create_connection((pc.address, pc.port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw) as tls:
                tls.settimeout(max(timeout, 600) if cmd in ("exam-start", "exam-stop") else timeout)
                if _peer_fingerprint(tls) != pc.fingerprint:
                    raise FleetError("a different PC answered")
                _send(tls, {"cmd": cmd, "args": args or {}})
                reply = _recv(tls, limit)
    except ssl.SSLError as e:
        reply = {"ok": False, "error": f"refused: {getattr(e, 'reason', None) or e} (still paired?)"}
    except (OSError, FleetError) as e:
        reply = {"ok": False, "error": f"not reachable: {e}" if isinstance(e, OSError) else str(e)}
    log_event(paths, "sent", pc=pc.name, address=pc.address, cmd=cmd,
              args={k: v for k, v in (args or {}).items() if k in ("url", "allow")},
              ok=bool(reply.get("ok")), error=reply.get("error", ""))
    return reply


def select(paths: FleetPaths, names: Sequence[str] = ()) -> List[PC]:
    pcs = load_pcs(paths)
    if not names:
        return pcs
    wanted = {clean_name(n) for n in names}
    missing = wanted - {pc.name for pc in pcs}
    if missing:
        raise FleetError(f"not paired: {', '.join(sorted(missing))} ('primers-fleet list' shows the paired PCs)")
    return [pc for pc in pcs if pc.name in wanted]


def on_each(paths: FleetPaths, pcs: Sequence[PC], cmd: str, args: Optional[dict] = None,
            timeout: float = 20) -> Dict[str, dict]:
    """The same command to several PCs at once."""
    results: Dict[str, dict] = {}
    threads = [threading.Thread(target=lambda p=pc: results.__setitem__(p.name, call(paths, p, cmd, args, timeout)))
               for pc in pcs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return {pc.name: results[pc.name] for pc in pcs}


def collect(paths: FleetPaths, pcs: Sequence[PC], dest: str) -> Dict[str, dict]:
    """Every PC's exam log into dest/<pc>/exam.jsonl, with SHA256SUMS."""
    replies = on_each(paths, pcs, "exam-log", timeout=60)
    sums = []
    for name, reply in replies.items():
        if not reply.get("ok"):
            continue
        data = reply.get("log", "").encode("utf-8")
        if hashlib.sha256(data).hexdigest() != reply.get("sha256"):
            reply.update(ok=False, error="the log arrived damaged")
            continue
        path = os.path.join(dest, name, "exam.jsonl")
        _atomic_write(path, data, 0o640)
        sums.append(f"{reply['sha256']}  {name}/exam.jsonl")
    if sums:
        _atomic_write(os.path.join(dest, "SHA256SUMS"), ("\n".join(sums) + "\n").encode(), 0o640)
    return replies


def format_status(rows: Dict[str, dict], pcs: Sequence[PC]) -> str:
    head = ("PC", "ADDRESS", "STATE", "LAB", "EXAM", "CANDIDATE", "LAST EVENT")
    table = [head]
    for pc in pcs:
        r = rows.get(pc.name, {})
        st = r.get("status") or {}
        if not r.get("ok"):
            table.append((pc.name, pc.address, "unreachable", "", "", "", r.get("error", "")[:60]))
            continue
        exam = ("on " + st.get("exam_url", "")) if st.get("exam") else ("off" if st.get("exam") is False else "?")
        table.append((pc.name, pc.address, "ok", {True: "on", False: "off"}.get(st.get("lab"), "?"), exam[:50],
                      "signed in" if st.get("candidate") else "-", str(st.get("last_event", ""))[:60]))
    widths = [max(len(str(row[i])) for row in table) for i in range(len(head))]
    return "\n".join("  ".join(str(c).ljust(w) for c, w in zip(row, widths)).rstrip() for row in table) + "\n"
