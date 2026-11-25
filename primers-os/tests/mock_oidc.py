"""
A small OpenID Connect provider for tests (never for real use).

It does what primers-id needs from Primers ID: discovery, JWKS (an RSA key
made at start), the authorization endpoint (signs the test person in at
once and redirects back), the device flow (approved through
POST /test/approve), the token endpoint (authorization code with PKCE,
device code, refresh token) and revocation. It can also misbehave on
purpose (set .tamper) to check that primers-id refuses bad tokens.

  python3 mock_oidc.py --port 8790 --issuer http://10.0.2.2:8790    (the VM test)
"""

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class MockProvider:
    def __init__(self, issuer: str = "", client_id: str = "primers-os", host: str = "127.0.0.1", port: int = 0,
                 device_flow: bool = True, person: dict = None):
        self.client_id = client_id
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = secrets.token_hex(4)
        self.person = person or {"sub": "pid-0001", "name": "Ada Okafor", "email": "ada@student.example.edu.ng"}
        self.device_flow = device_flow
        self.codes, self.devices, self.refresh, self.revoked = {}, {}, {}, []
        self.tamper = None            # None | "issuer" | "audience" | "signature" | "expired" | "nonce" | "none-alg"
        self.requests = []
        provider = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _send(self, status, obj=None, headers=None):
                self.send_response(status)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                body = json.dumps(obj).encode() if obj is not None else b""
                if obj is not None:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _form(self):
                n = int(self.headers.get("Content-Length") or 0)
                return dict(urllib.parse.parse_qsl(self.rfile.read(n).decode()))

            def do_GET(self):  # noqa: N802
                parts = urllib.parse.urlsplit(self.path)
                provider.requests.append(("GET", parts.path))
                if parts.path == "/.well-known/openid-configuration":
                    return self._send(200, provider.discovery())
                if parts.path == "/jwks":
                    return self._send(200, provider.jwks())
                if parts.path == "/authorize":
                    q = dict(urllib.parse.parse_qsl(parts.query))
                    return self._send(302, headers={"Location": provider.authorize(q)})
                self._send(404, {"error": "not_found"})

            def do_POST(self):  # noqa: N802
                path = urllib.parse.urlsplit(self.path).path
                form = self._form()
                provider.requests.append(("POST", path))
                if path == "/token":
                    status, obj = provider.token(form)
                    return self._send(status, obj)
                if path == "/device" and provider.device_flow:
                    return self._send(200, provider.device_start(form))
                if path == "/revoke":
                    provider.revoked.append(form.get("token"))
                    return self._send(200, {})
                if path == "/test/approve":
                    ok = provider.approve(form.get("user_code", ""), form.get("deny") == "1")
                    return self._send(200 if ok else 404, {"approved": ok})
                self._send(404, {"error": "not_found"})

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer((host, port), Handler)
        self.port = self.server.server_address[1]
        self.issuer = (issuer or f"http://{host}:{self.port}").rstrip("/")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    # ---- documents ----

    def discovery(self):
        d = {"issuer": self.issuer, "authorization_endpoint": self.issuer + "/authorize",
             "token_endpoint": self.issuer + "/token", "jwks_uri": self.issuer + "/jwks",
             "revocation_endpoint": self.issuer + "/revoke", "response_types_supported": ["code"],
             "id_token_signing_alg_values_supported": ["RS256"], "code_challenge_methods_supported": ["S256"]}
        if self.device_flow:
            d["device_authorization_endpoint"] = self.issuer + "/device"
        return d

    def jwks(self):
        n = self.key.public_key().public_numbers()
        return {"keys": [{"kty": "RSA", "kid": self.kid, "use": "sig", "alg": "RS256",
                          "n": b64url(n.n.to_bytes((n.n.bit_length() + 7) // 8, "big")),
                          "e": b64url(n.e.to_bytes(3, "big"))}]}

    def id_token(self, nonce=None):
        now = int(time.time())
        claims = {"iss": self.issuer, "aud": self.client_id, "sub": self.person["sub"], "iat": now, "exp": now + 600,
                  "name": self.person["name"], "email": self.person["email"]}
        if nonce:
            claims["nonce"] = nonce
        header = {"alg": "RS256", "kid": self.kid, "typ": "JWT"}
        if self.tamper == "issuer":
            claims["iss"] = "https://evil.example"
        elif self.tamper == "audience":
            claims["aud"] = "another-app"
        elif self.tamper == "expired":
            claims["exp"] = now - 3600
        elif self.tamper == "nonce" and nonce:
            claims["nonce"] = "something-else"
        elif self.tamper == "none-alg":
            header = {"alg": "none", "typ": "JWT"}
        signing = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(claims).encode())}"
        sig = self.key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
        if self.tamper == "signature":
            sig = bytes([sig[0] ^ 1]) + sig[1:]
        if self.tamper == "none-alg":
            sig = b""
        return f"{signing}.{b64url(sig)}"

    def _tokens(self, nonce=None):
        refresh = secrets.token_urlsafe(24)
        self.refresh[refresh] = True
        return {"access_token": secrets.token_urlsafe(24), "token_type": "Bearer", "expires_in": 600,
                "refresh_token": refresh, "id_token": self.id_token(nonce)}

    # ---- endpoints ----

    def authorize(self, q):
        redirect = q.get("redirect_uri", "")
        if q.get("client_id") != self.client_id or q.get("code_challenge_method") != "S256" \
                or not redirect.startswith("http://127.0.0.1:"):
            return redirect + "?" + urllib.parse.urlencode({"error": "invalid_request", "state": q.get("state", "")})
        code = secrets.token_urlsafe(16)
        self.codes[code] = {"challenge": q.get("code_challenge"), "redirect": redirect, "nonce": q.get("nonce")}
        return redirect + "?" + urllib.parse.urlencode({"code": code, "state": q.get("state", "")})

    def device_start(self, form):
        device_code, user_code = secrets.token_urlsafe(16), "-".join(secrets.token_hex(2).upper() for _ in range(2))
        self.devices[device_code] = {"user_code": user_code, "state": "pending"}
        return {"device_code": device_code, "user_code": user_code, "verification_uri": self.issuer + "/activate",
                "verification_uri_complete": self.issuer + "/activate?code=" + user_code,
                "expires_in": 300, "interval": 1}

    def approve(self, user_code, deny=False):
        for d in self.devices.values():
            if d["user_code"] == user_code and d["state"] == "pending":
                d["state"] = "denied" if deny else "approved"
                return True
        return False

    def token(self, form):
        if form.get("client_id") != self.client_id:
            return 400, {"error": "invalid_client"}
        grant = form.get("grant_type")
        if grant == "authorization_code":
            c = self.codes.pop(form.get("code", ""), None)
            if not c or c["redirect"] != form.get("redirect_uri"):
                return 400, {"error": "invalid_grant"}
            if b64url(hashlib.sha256(form.get("code_verifier", "").encode()).digest()) != c["challenge"]:
                return 400, {"error": "invalid_grant", "error_description": "PKCE verification failed"}
            return 200, self._tokens(c["nonce"])
        if grant == "urn:ietf:params:oauth:grant-type:device_code":
            d = self.devices.get(form.get("device_code", ""))
            if not d:
                return 400, {"error": "expired_token"}
            if d["state"] == "pending":
                return 400, {"error": "authorization_pending"}
            if d["state"] == "denied":
                return 400, {"error": "access_denied"}
            del self.devices[form["device_code"]]
            return 200, self._tokens()
        if grant == "refresh_token" and self.refresh.pop(form.get("refresh_token", ""), None):
            return 200, self._tokens()
        return 400, {"error": "unsupported_grant_type"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--issuer", default="")
    ap.add_argument("--client-id", default="primers-os")
    args = ap.parse_args()
    p = MockProvider(args.issuer, args.client_id, args.host, args.port)
    print(f"mock OIDC provider {p.issuer} on {args.host}:{p.port}", flush=True)
    threading.Event().wait()
