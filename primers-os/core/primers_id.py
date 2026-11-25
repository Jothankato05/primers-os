"""
PRIMERS OS — Primers ID: sign in with your Primers account (OpenID Connect).

``primers-id login`` signs the person at the desktop in with Primers ID:
with the device flow (RFC 8628: a code to type at the provider's page, on
this PC or a phone) when the provider offers it, otherwise with the
authorization code flow and PKCE through a browser and a loopback address
on this PC (RFC 8252). The ID token's signature is checked against the
provider's published keys (JWKS), and its issuer, audience, expiry and
nonce are checked too.

Offline: at an online sign-in the person chooses a PIN. Later, when the
provider can't be reached, ``primers-id login --offline`` signs them in
with that PIN, for up to ``offline_days`` days after the last online
sign-in; five wrong PINs lock offline sign-in until the next online one.

Which provider: /etc/primers/id.conf (issuer, client ID, scopes). Moving
from a test provider to the real Primers ID service is a change to that
file only. Each person's session is in ~/.local/share/primers/id
(readable by them only); Lab Mode wipes it with the lab account.

Decisions: docs/decisions/0007-primers-id.md.
"""

import base64
import configparser
import contextlib
import hashlib
import hmac
import http.server
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

CONF_PATH = "/etc/primers/id.conf"
LEEWAY = 120                       # seconds of clock difference accepted
MAX_PIN_FAILURES = 5
SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


class IdError(Exception):
    pass


class Unreachable(IdError):
    """The provider couldn't be reached (offline sign-in may be possible)."""


# ------------------------------------------------------------------ #
#  Configuration
# ------------------------------------------------------------------ #

@dataclass
class IdConfig:
    issuer: str
    client_id: str
    scopes: List[str] = field(default_factory=lambda: ["openid", "profile", "email"])
    offline_days: int = 14
    timeout: float = 10.0

    @classmethod
    def load(cls, path: str = CONF_PATH) -> "IdConfig":
        cp = configparser.ConfigParser()
        if not cp.read(path, encoding="utf-8") or not cp.has_section("primers-id"):
            raise IdError(f"Primers ID isn't set up on this PC ({path} is missing)")
        s = cp["primers-id"]
        issuer, client_id = s.get("issuer", "").strip().rstrip("/"), s.get("client_id", "").strip()
        if not issuer or not client_id:
            raise IdError(f"{path} needs an issuer and a client_id")
        parts = urllib.parse.urlsplit(issuer)
        local = parts.hostname in ("localhost", "127.0.0.1", "::1")
        if parts.scheme != "https" and not (parts.scheme == "http" and (local or s.getboolean("allow_http", False))):
            raise IdError("the Primers ID issuer must be an https:// address")
        return cls(issuer, client_id, s.get("scopes", "openid profile email").split(),
                   s.getint("offline_days", 14), s.getfloat("timeout", 10.0))


# ------------------------------------------------------------------ #
#  HTTP (injectable for tests; never follows redirects to other schemes)
# ------------------------------------------------------------------ #

def _http(method: str, url: str, data: Optional[dict] = None, timeout: float = 10.0) -> dict:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Accept": "application/json",
                                          **({"Content-Type": "application/x-www-form-urlencoded"} if body else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read(1024 * 1024)
    except urllib.error.HTTPError as e:
        payload = e.read(64 * 1024)
        try:
            err = json.loads(payload)
        except ValueError:
            raise IdError(f"{url}: HTTP {e.code}")
        return {"_status": e.code, **(err if isinstance(err, dict) else {})}
    except (urllib.error.URLError, OSError, socket.timeout) as e:
        raise Unreachable(f"Primers ID can't be reached ({getattr(e, 'reason', e)})")
    try:
        obj = json.loads(payload)
    except ValueError:
        raise IdError(f"{url}: not JSON")
    if not isinstance(obj, dict):
        raise IdError(f"{url}: unexpected reply")
    return obj


# ------------------------------------------------------------------ #
#  Tokens
# ------------------------------------------------------------------ #

def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _public_key(jwk: dict):
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    if jwk.get("kty") == "RSA":
        n = int.from_bytes(b64url_decode(jwk["n"]), "big")
        e = int.from_bytes(b64url_decode(jwk["e"]), "big")
        return rsa.RSAPublicNumbers(e, n).public_key()
    if jwk.get("kty") == "EC" and jwk.get("crv") == "P-256":
        x = int.from_bytes(b64url_decode(jwk["x"]), "big")
        y = int.from_bytes(b64url_decode(jwk["y"]), "big")
        return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
    raise IdError("the provider uses a key type PRIMERS OS doesn't accept")


def verify_id_token(token: str, jwks: dict, issuer: str, client_id: str, nonce: Optional[str] = None,
                    now: Optional[float] = None) -> dict:
    """The ID token's claims, if its signature and claims are all right."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, utils
    try:
        head_b64, body_b64, sig_b64 = token.split(".")
        header, claims = json.loads(b64url_decode(head_b64)), json.loads(b64url_decode(body_b64))
        signature = b64url_decode(sig_b64)
    except (ValueError, TypeError):
        raise IdError("the ID token is malformed")
    alg = header.get("alg")
    if alg not in ("RS256", "ES256"):                 # never 'none', never HMAC with a public key
        raise IdError(f"ID token algorithm {alg!r} isn't accepted")
    keys = [k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid") or "kid" not in header]
    if not keys:
        raise IdError("the ID token's key isn't one the provider publishes")
    signed = f"{head_b64}.{body_b64}".encode()
    for jwk in keys:
        try:
            key = _public_key(jwk)
            if alg == "RS256" and jwk.get("kty") == "RSA":
                key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
            elif alg == "ES256" and jwk.get("kty") == "EC" and len(signature) == 64:
                der = utils.encode_dss_signature(int.from_bytes(signature[:32], "big"),
                                                 int.from_bytes(signature[32:], "big"))
                key.verify(der, signed, ec.ECDSA(hashes.SHA256()))
            else:
                continue
            break
        except (InvalidSignature, ValueError, KeyError):
            continue
    else:
        raise IdError("the ID token's signature is wrong")
    now = time.time() if now is None else now
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if claims.get("iss") != issuer:
        raise IdError("the ID token is from another issuer")
    if client_id not in auds or (len(auds) > 1 and claims.get("azp") != client_id):
        raise IdError("the ID token is for another application")
    if not isinstance(claims.get("exp"), (int, float)) or claims["exp"] < now - LEEWAY:
        raise IdError("the ID token has expired")
    if isinstance(claims.get("iat"), (int, float)) and claims["iat"] > now + LEEWAY:
        raise IdError("the ID token is from the future (check the PC's clock)")
    if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise IdError("the ID token doesn't match this sign-in")
    if not claims.get("sub"):
        raise IdError("the ID token names nobody")
    return claims


# ------------------------------------------------------------------ #
#  The session, kept for the person (and for offline sign-in)
# ------------------------------------------------------------------ #

def default_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "primers", "id")


def pin_hash(pin: str, salt: bytes) -> str:
    return hashlib.scrypt(pin.encode(), salt=salt, **SCRYPT).hex()


class Store:
    def __init__(self, directory: Optional[str] = None):
        self.dir = directory or default_dir()
        self.path = os.path.join(self.dir, "session.json")

    def load(self) -> Optional[dict]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def save(self, session: dict) -> None:
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        os.chmod(self.dir, 0o700)
        tmp = f"{self.path}.tmp.{os.getpid()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(session, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def clear(self) -> bool:
        try:
            os.unlink(self.path)
            return True
        except FileNotFoundError:
            return False


# ------------------------------------------------------------------ #
#  Sign-in
# ------------------------------------------------------------------ #

class PrimersID:
    def __init__(self, config: IdConfig, store: Optional[Store] = None,
                 http: Callable[..., dict] = _http, clock: Callable[[], float] = time.time,
                 open_browser: Optional[Callable[[str], None]] = None, sleep: Callable[[float], None] = time.sleep):
        self.config, self.store, self.http, self.clock = config, store or Store(), http, clock
        self.open_browser = open_browser or _open_browser
        self.sleep = sleep
        self._discovery: Optional[dict] = None

    # ---- the provider ----

    def discovery(self) -> dict:
        if self._discovery is None:
            doc = self.http("GET", self.config.issuer + "/.well-known/openid-configuration",
                            timeout=self.config.timeout)
            if doc.get("issuer", "").rstrip("/") != self.config.issuer:
                raise IdError("the provider says it is another issuer")
            for need in ("token_endpoint", "jwks_uri"):
                if not doc.get(need):
                    raise IdError(f"the provider publishes no {need}")
            self._discovery = doc
        return self._discovery

    def jwks(self) -> dict:
        return self.http("GET", self.discovery()["jwks_uri"], timeout=self.config.timeout)

    def _finish(self, tokens: dict, nonce: Optional[str], pin: Optional[str]) -> dict:
        if "id_token" not in tokens:
            raise IdError(tokens.get("error_description") or tokens.get("error") or "no ID token in the reply")
        claims = verify_id_token(tokens["id_token"], self.jwks(), self.config.issuer, self.config.client_id,
                                 nonce, now=self.clock())
        now = self.clock()
        session = {"issuer": self.config.issuer, "client_id": self.config.client_id, "sub": claims["sub"],
                   "name": claims.get("name") or claims.get("preferred_username") or "",
                   "email": claims.get("email", ""), "online_at": int(now),
                   "offline_until": int(now + self.config.offline_days * 86400), "mode": "online",
                   "pin_failures": 0}
        if tokens.get("refresh_token"):
            session["refresh_token"] = tokens["refresh_token"]
        if pin:
            if len(pin) < 4 or not pin.isdigit():
                raise IdError("the offline PIN must be at least 4 digits")
            salt = secrets.token_bytes(16)
            session.update(pin_salt=salt.hex(), pin_hash=pin_hash(pin, salt))
        else:
            old = self.store.load() or {}
            if old.get("sub") == claims["sub"] and old.get("issuer") == self.config.issuer and old.get("pin_hash"):
                session.update(pin_salt=old["pin_salt"], pin_hash=old["pin_hash"])
        self.store.save(session)
        return session

    # ---- device flow (RFC 8628) ----

    def device_login(self, show: Callable[[str, str, Optional[str]], None], pin: Optional[str] = None,
                     max_wait: float = 600) -> dict:
        d = self.discovery()
        if not d.get("device_authorization_endpoint"):
            raise IdError("the provider doesn't offer the device flow")
        start = self.http("POST", d["device_authorization_endpoint"],
                          {"client_id": self.config.client_id, "scope": " ".join(self.config.scopes)},
                          timeout=self.config.timeout)
        if not start.get("device_code") or not start.get("user_code"):
            raise IdError(start.get("error_description") or "the provider didn't start a device sign-in")
        show(start.get("verification_uri", ""), start["user_code"], start.get("verification_uri_complete"))
        interval = max(1, int(start.get("interval", 5)))
        deadline = self.clock() + min(max_wait, float(start.get("expires_in", max_wait)))
        while self.clock() < deadline:
            self.sleep(interval)
            tokens = self.http("POST", d["token_endpoint"],
                               {"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                "device_code": start["device_code"], "client_id": self.config.client_id},
                               timeout=self.config.timeout)
            err = tokens.get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            if err:
                raise IdError({"access_denied": "the sign-in was refused",
                               "expired_token": "the code expired: start again"}.get(err, err))
            return self._finish(tokens, None, pin)
        raise IdError("the code expired before anyone signed in: start again")

    # ---- authorization code + PKCE, loopback redirect (RFC 8252) ----

    def browser_login(self, pin: Optional[str] = None, max_wait: float = 300) -> dict:
        d = self.discovery()
        if not d.get("authorization_endpoint"):
            raise IdError("the provider publishes no authorization endpoint")
        verifier = b64url(secrets.token_bytes(32))
        challenge = b64url(hashlib.sha256(verifier.encode()).digest())
        state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        got: Dict[str, str] = {}
        done = threading.Event()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
                if urllib.parse.urlsplit(self.path).path != "/callback" or not q:
                    self.send_response(404)
                    self.end_headers()
                    return
                got.update(q)
                done.set()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<p>Signed in. You can close this page and go back to PRIMERS OS.</p>")

            def log_message(self, *a):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        redirect = f"http://127.0.0.1:{server.server_address[1]}/callback"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = d["authorization_endpoint"] + "?" + urllib.parse.urlencode({
                "response_type": "code", "client_id": self.config.client_id, "redirect_uri": redirect,
                "scope": " ".join(self.config.scopes), "state": state, "nonce": nonce,
                "code_challenge": challenge, "code_challenge_method": "S256"})
            self.open_browser(url)
            if not done.wait(max_wait):
                raise IdError("nobody finished signing in in the browser")
        finally:
            server.shutdown()
            server.server_close()
        if not hmac.compare_digest(got.get("state", ""), state):
            raise IdError("the reply doesn't belong to this sign-in")
        if got.get("error") or not got.get("code"):
            raise IdError(got.get("error_description") or got.get("error") or "no sign-in code came back")
        tokens = self.http("POST", d["token_endpoint"],
                           {"grant_type": "authorization_code", "code": got["code"], "redirect_uri": redirect,
                            "client_id": self.config.client_id, "code_verifier": verifier},
                           timeout=self.config.timeout)
        return self._finish(tokens, nonce, pin)

    def login(self, show: Callable[[str, str, Optional[str]], None], pin: Optional[str] = None) -> dict:
        """The device flow when the provider has it, else the browser."""
        if self.discovery().get("device_authorization_endpoint"):
            return self.device_login(show, pin)
        return self.browser_login(pin)

    # ---- offline ----

    def offline_login(self, pin: str) -> dict:
        s = self.store.load()
        if not s or s.get("issuer") != self.config.issuer:
            raise IdError("nobody has signed in with Primers ID on this account yet: sign in online first")
        if not s.get("pin_hash"):
            raise IdError("no offline PIN was chosen: sign in online with --pin")
        if s.get("pin_failures", 0) >= MAX_PIN_FAILURES:
            raise IdError("offline sign-in is locked after too many wrong PINs: sign in online")
        if self.clock() > s.get("offline_until", 0):
            raise IdError("offline sign-in has expired: sign in online again")
        if not hmac.compare_digest(pin_hash(pin, bytes.fromhex(s["pin_salt"])), s["pin_hash"]):
            s["pin_failures"] = s.get("pin_failures", 0) + 1
            self.store.save(s)
            left = MAX_PIN_FAILURES - s["pin_failures"]
            raise IdError("wrong PIN" + (f" ({left} tries left)" if left > 0 else "; offline sign-in is now locked"))
        s.update(pin_failures=0, mode="offline", offline_at=int(self.clock()))
        self.store.save(s)
        return s

    def status(self) -> Optional[dict]:
        s = self.store.load()
        if not s or s.get("issuer") != self.config.issuer:
            return None
        return {k: v for k, v in s.items() if k not in ("refresh_token", "pin_hash", "pin_salt")}

    def logout(self) -> bool:
        s = self.store.load()
        if s and s.get("refresh_token"):
            with contextlib.suppress(IdError):
                endpoint = self.discovery().get("revocation_endpoint")
                if endpoint:
                    self.http("POST", endpoint, {"token": s["refresh_token"], "token_type_hint": "refresh_token",
                                                 "client_id": self.config.client_id}, timeout=self.config.timeout)
        return self.store.clear()


def _open_browser(url: str) -> None:
    import subprocess
    for cmd in (["lite-bee", url], ["xdg-open", url]):
        with contextlib.suppress(OSError):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return
    print(f"Open this address in a browser to sign in:\n  {url}")
