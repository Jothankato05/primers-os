"""Primers ID: OIDC sign-in against a mock provider over real HTTP, token
checks, offline sign-in, and moving providers by configuration only."""

import json
import os
import stat
import threading
import urllib.request

import pytest

from core import primers_id as pid
from mock_oidc import MockProvider


@pytest.fixture
def provider():
    p = MockProvider()
    yield p
    p.close()


def make(provider, tmp_path, **kw):
    conf = pid.IdConfig(provider.issuer, provider.client_id, offline_days=kw.pop("offline_days", 14))
    return pid.PrimersID(conf, pid.Store(str(tmp_path / "id")), **kw)


def approve_when_shown(provider):
    """What the person does on their phone: type the code at the provider."""
    def show(uri, code, complete):
        threading.Timer(0.2, lambda: provider.approve(code)).start()
    return show


def follow_redirect(url):
    """What the browser does: open the provider's page, follow it back to this PC."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(url, timeout=5)
    except urllib.error.HTTPError as e:
        urllib.request.urlopen(e.headers["Location"], timeout=5).read()


# ---------------- configuration ----------------

def test_config_is_the_only_thing_that_names_the_provider(tmp_path):
    path = tmp_path / "id.conf"
    path.write_text("[primers-id]\nissuer = https://id.primersgroup.ng/\nclient_id = primers-os\noffline_days = 7\n")
    conf = pid.IdConfig.load(str(path))
    assert (conf.issuer, conf.client_id, conf.offline_days) == ("https://id.primersgroup.ng", "primers-os", 7)
    assert conf.scopes == ["openid", "profile", "email"]


@pytest.mark.parametrize("text,err", [
    ("", "isn't set up"),
    ("[primers-id]\nissuer = http://id.example\nclient_id = x\n", "https"),
    ("[primers-id]\nissuer = https://id.example\n", "client_id"),
])
def test_config_refuses_what_it_should(tmp_path, text, err):
    path = tmp_path / "id.conf"
    if text:
        path.write_text(text)
    with pytest.raises(pid.IdError, match=err):
        pid.IdConfig.load(str(path))


def test_plain_http_only_for_this_pc_or_when_a_test_says_so(tmp_path):
    path = tmp_path / "id.conf"
    path.write_text("[primers-id]\nissuer = http://127.0.0.1:8790\nclient_id = x\n")
    assert pid.IdConfig.load(str(path)).issuer == "http://127.0.0.1:8790"
    path.write_text("[primers-id]\nissuer = http://10.0.2.2:8790\nclient_id = x\nallow_http = true\n")
    assert pid.IdConfig.load(str(path)).issuer == "http://10.0.2.2:8790"


# ---------------- online sign-in ----------------

def test_device_flow_signs_in_and_keeps_the_session_private(provider, tmp_path):
    p = make(provider, tmp_path, sleep=lambda s: __import__("time").sleep(0.2))
    s = p.login(approve_when_shown(provider), pin="2468")
    assert s["sub"] == "pid-0001" and s["name"] == "Ada Okafor" and s["mode"] == "online"
    st = p.status()
    assert st["email"] == "ada@student.example.edu.ng"
    assert "refresh_token" not in st and "pin_hash" not in st          # never shown
    assert stat.S_IMODE(os.stat(p.store.path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(p.store.dir).st_mode) == 0o700
    assert "2468" not in open(p.store.path).read()                     # only a scrypt hash of the PIN


def test_browser_flow_with_pkce_when_there_is_no_device_flow(tmp_path):
    provider = MockProvider(device_flow=False)
    try:
        p = make(provider, tmp_path, open_browser=lambda url: threading.Thread(
            target=follow_redirect, args=(url,), daemon=True).start())
        s = p.login(lambda *a: pytest.fail("no device flow here"))
        assert s["sub"] == "pid-0001"
        assert ("GET", "/authorize") in provider.requests and ("POST", "/token") in provider.requests
    finally:
        provider.close()


def test_a_denied_device_sign_in_is_reported(provider, tmp_path):
    p = make(provider, tmp_path, sleep=lambda s: __import__("time").sleep(0.2))
    with pytest.raises(pid.IdError, match="refused"):
        p.device_login(lambda uri, code, c: threading.Timer(0.2, lambda: provider.approve(code, deny=True)).start())
    assert p.status() is None


@pytest.mark.parametrize("tamper,message", [
    ("issuer", "another issuer"), ("audience", "another application"), ("signature", "signature is wrong"),
    ("expired", "expired"), ("none-alg", "isn't accepted"),
])
def test_bad_id_tokens_are_refused(provider, tmp_path, tamper, message):
    provider.tamper = tamper
    p = make(provider, tmp_path, sleep=lambda s: __import__("time").sleep(0.2))
    with pytest.raises(pid.IdError, match=message):
        p.login(approve_when_shown(provider))
    assert p.status() is None                                           # nothing kept


def test_a_token_for_another_sign_in_is_refused(tmp_path):
    provider = MockProvider(device_flow=False)
    provider.tamper = "nonce"
    try:
        p = make(provider, tmp_path, open_browser=lambda url: threading.Thread(
            target=follow_redirect, args=(url,), daemon=True).start())
        with pytest.raises(pid.IdError, match="doesn't match this sign-in"):
            p.login(lambda *a: None)
    finally:
        provider.close()


def test_a_provider_claiming_another_name_is_refused(provider, tmp_path):
    conf = pid.IdConfig(provider.issuer + "/other", provider.client_id)
    p = pid.PrimersID(conf, pid.Store(str(tmp_path / "id")),
                      http=lambda m, url, data=None, timeout=10: json.loads(json.dumps(provider.discovery())))
    with pytest.raises(pid.IdError, match="another issuer"):
        p.discovery()


def test_unreachable_provider_says_so(tmp_path):
    p = pid.PrimersID(pid.IdConfig("http://127.0.0.1:9", "primers-os", timeout=2), pid.Store(str(tmp_path / "id")))
    with pytest.raises(pid.Unreachable):
        p.login(lambda *a: None)


# ---------------- offline sign-in ----------------

def online(provider, tmp_path, clock, pin="2468"):
    p = make(provider, tmp_path, clock=clock, sleep=lambda s: __import__("time").sleep(0.2))
    p.login(approve_when_shown(provider), pin=pin)
    return p


def test_offline_sign_in_with_the_pin_within_the_window(provider, tmp_path):
    import time as t
    now = [t.time()]
    p = online(provider, tmp_path, lambda: now[0])
    now[0] += 13 * 86400
    s = p.offline_login("2468")
    assert s["mode"] == "offline" and s["sub"] == "pid-0001"


def test_offline_sign_in_ends_after_the_window(provider, tmp_path):
    import time as t
    now = [t.time()]
    p = online(provider, tmp_path, lambda: now[0])
    now[0] += 15 * 86400
    with pytest.raises(pid.IdError, match="expired"):
        p.offline_login("2468")


def test_wrong_pins_lock_offline_sign_in_until_the_next_online_one(provider, tmp_path):
    import time as t
    now = [t.time()]
    p = online(provider, tmp_path, lambda: now[0])
    for _ in range(pid.MAX_PIN_FAILURES):
        with pytest.raises(pid.IdError, match="wrong PIN"):
            p.offline_login("0000")
    with pytest.raises(pid.IdError, match="locked"):
        p.offline_login("2468")
    p.login(approve_when_shown(provider))                               # online again: unlocked, PIN kept
    assert p.offline_login("2468")["mode"] == "offline"


def test_offline_needs_an_earlier_online_sign_in_and_a_pin(provider, tmp_path):
    p = make(provider, tmp_path, sleep=lambda s: __import__("time").sleep(0.2))
    with pytest.raises(pid.IdError, match="sign in online first"):
        p.offline_login("2468")
    p.login(approve_when_shown(provider))
    with pytest.raises(pid.IdError, match="no offline PIN"):
        p.offline_login("2468")


def test_pins_must_be_digits(provider, tmp_path):
    p = make(provider, tmp_path, sleep=lambda s: __import__("time").sleep(0.2))
    with pytest.raises(pid.IdError, match="4 digits"):
        p.login(approve_when_shown(provider), pin="12a")


# ---------------- moving providers, signing out ----------------

def test_another_provider_is_a_configuration_change_only(tmp_path):
    first, second = MockProvider(), MockProvider(person={"sub": "real-42", "name": "Ada", "email": "a@x"})
    try:
        store = str(tmp_path / "id")
        for prov in (first, second):
            conf_file = tmp_path / "id.conf"
            conf_file.write_text(f"[primers-id]\nissuer = {prov.issuer}\nclient_id = primers-os\n")
            p = pid.PrimersID(pid.IdConfig.load(str(conf_file)), pid.Store(store),
                              sleep=lambda s: __import__("time").sleep(0.2))
            assert p.login(approve_when_shown(prov))["issuer"] == prov.issuer
        assert p.status()["sub"] == "real-42"
    finally:
        first.close()
        second.close()


def test_sign_out_forgets_the_session_and_revokes_the_refresh_token(provider, tmp_path):
    p = make(provider, tmp_path, sleep=lambda s: __import__("time").sleep(0.2))
    p.login(approve_when_shown(provider))
    refresh = json.load(open(p.store.path))["refresh_token"]
    assert p.logout() and p.status() is None
    assert provider.revoked == [refresh]


# ---------------- the command ----------------

def test_cli_signs_in_shows_status_offline_and_out(provider, tmp_path, monkeypatch, capsys):
    import io
    import time
    import primers_id_cli as cli
    conf = tmp_path / "id.conf"
    conf.write_text(f"[primers-id]\nissuer = {provider.issuer}\nclient_id = primers-os\n")
    original = pid.IdConfig.load.__func__
    monkeypatch.setattr(pid.IdConfig, "load", classmethod(lambda cls, path=None: original(cls, str(conf))))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    def approve_soon():
        time.sleep(1.5)
        for d in list(provider.devices.values()):
            provider.approve(d["user_code"])
    threading.Thread(target=approve_soon, daemon=True).start()
    monkeypatch.setattr("sys.stdin", io.StringIO("2468\n"))
    assert cli.main(["login", "--pin-stdin"]) == 0
    out = capsys.readouterr().out
    assert "enter the code" in out and "Signed in as Ada Okafor" in out
    assert cli.main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["sub"] == "pid-0001"
    monkeypatch.setattr("sys.stdin", io.StringIO("2468\n"))
    assert cli.main(["login", "--offline", "--pin-stdin"]) == 0
    assert "offline, with your PIN" in capsys.readouterr().out
    assert cli.main(["logout"]) == 0 and cli.main(["status"]) == 1


def test_cli_points_to_offline_sign_in_when_the_provider_is_unreachable(tmp_path, monkeypatch, capsys):
    import io
    import primers_id_cli as cli
    conf = tmp_path / "id.conf"
    conf.write_text("[primers-id]\nissuer = http://127.0.0.1:9\nclient_id = primers-os\ntimeout = 2\n")
    original = pid.IdConfig.load.__func__
    monkeypatch.setattr(pid.IdConfig, "load", classmethod(lambda cls, path=None: original(cls, str(conf))))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    store = pid.Store(str(tmp_path / "data" / "primers" / "id"))
    salt = b"0123456789abcdef"
    store.save({"issuer": "http://127.0.0.1:9", "sub": "pid-0001", "pin_salt": salt.hex(),
                "pin_hash": pid.pin_hash("2468", salt), "offline_until": 4102444800})
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    assert cli.main(["login", "--pin-stdin"]) == 2
    assert "primers-id login --offline" in capsys.readouterr().err
