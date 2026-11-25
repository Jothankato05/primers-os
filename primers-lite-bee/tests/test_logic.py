import json
import os
import stat
from datetime import date

import pytest

from litebee import filters, network, pages, storage, urls
from litebee.datameter import DataMeter, fmt_bytes, fmt_naira
from litebee.modes import MODES, auto_mode_for, resolve
from litebee.network import ConnectionInfo
from litebee.session import Session, Settings


# ── connection detection ─────────────────────────────────────────────

NMCLI = """wlp2s0:wifi:connected:Campus WiFi
enp3s0:ethernet:unavailable:
cdc-wdm0:gsm:connected:MTN NG
lo:loopback:connected (externally):lo
p2p-dev-wlp2s0:wifi-p2p:disconnected:
"""


def test_parse_nmcli_devices():
    devs = network.parse_nmcli_devices(NMCLI)
    assert devs[0] == {"device": "wlp2s0", "type": "wifi", "state": "connected", "connection": "Campus WiFi"}
    assert devs[2]["type"] == "gsm"
    escaped = network.parse_nmcli_devices("wlan0:wifi:connected:My\\:Net\n")
    assert escaped[0]["connection"] == "My:Net"


@pytest.mark.parametrize("value, gen", [
    ("gsm, edge", "2g"), ("gprs", "2g"), ("umts, hsdpa", "3g"), ("lte", "4g"),
    ("gsm|umts|lte", "4g"), ("5gnr", "5g"), ("", None), ("unknown", None),
])
def test_generation_from_access_tech(value, gen):
    assert network.generation_from_access_tech(value) == gen


def test_pick_connection_prefers_wired_then_wifi():
    devs = network.parse_nmcli_devices(NMCLI)
    conn = network.pick_connection(devs, {"wlp2s0": False, "cdc-wdm0": True}, "4g")
    assert conn.kind == "wifi" and not conn.metered
    only_mobile = [d for d in devs if d["type"] == "gsm"]
    conn = network.pick_connection(only_mobile, {}, "2g")
    assert conn == ConnectionInfo("mobile", "2g", True, "MTN NG")
    assert network.pick_connection([], {}, None).kind == "none"


def test_parse_metered_and_mmcli():
    assert network.parse_metered("yes (guessed)\n")
    assert not network.parse_metered("no")
    kv = network.parse_mmcli_keyvalue("modem.generic.access-technologies.value[1] : lte\n")
    assert kv["modem.generic.access-technologies.value[1]"] == "lte"


def test_detect_never_raises(monkeypatch):
    monkeypatch.setattr(network.shutil, "which", lambda _: None)
    assert network.detect().kind == "unknown"


# ── modes ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("conn, mode", [
    (ConnectionInfo("ethernet"), "full"),
    (ConnectionInfo("wifi"), "full"),
    (ConnectionInfo("wifi", metered=True), "lite"),       # phone hotspot
    (ConnectionInfo("mobile", "4g", True), "lite"),
    (ConnectionInfo("mobile", "3g", True), "lite"),
    (ConnectionInfo("mobile", "2g", True), "ultra"),
    (ConnectionInfo("none"), "lite"),
    (None, "lite"),
])
def test_auto_mode(conn, mode):
    assert auto_mode_for(conn).key == mode
    assert resolve("auto", conn).key == mode


def test_manual_mode_wins():
    assert resolve("ultra", ConnectionInfo("ethernet")).key == "ultra"
    assert resolve("bogus", ConnectionInfo("ethernet")).key == "full"


# ── content blocking ─────────────────────────────────────────────────

def test_filters_valid_and_mode_specific():
    full = filters.build_rules(MODES["full"])
    ultra = filters.build_rules(MODES["ultra"])
    for rules in (full, ultra):
        json.loads(json.dumps(rules))
        for r in rules:
            assert r["action"]["type"] == "block" and "url-filter" in r["trigger"]
    full_types = {t for r in full for t in r["trigger"].get("resource-type", [])}
    ultra_types = {t for r in ultra for t in r["trigger"].get("resource-type", [])}
    assert "image" not in full_types
    assert {"image", "font", "media", "script"} <= ultra_types
    assert len([r for r in full if "resource-type" not in r["trigger"]]) == len(filters.TRACKER_DOMAINS)
    assert filters.filter_id(MODES["lite"]) != filters.filter_id(MODES["ultra"])


def test_tracker_pattern_matches_subdomains_only():
    import re
    pat = re.compile(filters._domain_pattern("doubleclick.net"))
    assert pat.search("https://ad.doubleclick.net/x")
    assert pat.search("http://doubleclick.net/")
    assert not pat.search("https://notdoubleclick.net.example.com/")


# ── data meter ───────────────────────────────────────────────────────

def test_data_meter_totals_and_persistence(isolated_home):
    m = DataMeter()
    m.add(5 * 1024 * 1024)
    m.add(1024, when=date(2020, 1, 1))
    m.add(-5)
    assert m.today() == 5 * 1024 * 1024
    assert m.session == 5 * 1024 * 1024 + 1024
    m.save()
    path = storage.data_file("data-usage.json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    again = DataMeter()
    assert again.today() == 5 * 1024 * 1024 and again.month(date(2020, 1, 5)) == 1024
    assert "5.0 MB today" == again.label()


def test_data_meter_cost_only_when_price_set():
    m = DataMeter(naira_per_gb=1000)
    m.add(512 * 1024 * 1024)
    assert m.cost(m.today()) == pytest.approx(500)
    assert "₦500" in m.label()
    assert DataMeter().cost(10) is None


def test_formatting():
    assert fmt_bytes(512) == "512 B"
    assert fmt_bytes(1536) == "1.5 KB"
    assert fmt_bytes(3 * 1024 ** 3) == "3.0 GB"
    assert fmt_naira(2.5) == "₦2.50"
    assert fmt_naira(1500) == "₦1,500"


# ── address bar ──────────────────────────────────────────────────────

@pytest.mark.parametrize("text, expected", [
    ("primersgroup.ng", "https://primersgroup.ng"),
    ("velaji.vercel.app/path?x=1", "https://velaji.vercel.app/path?x=1"),
    ("https://example.com", "https://example.com"),
    ("http://example.com", "http://example.com"),
    ("localhost:8000", "http://localhost:8000"),
    ("192.168.0.1", "http://192.168.0.1"),
    ("bee:saved", "bee:saved"),
    ("", "bee:home"),
    ("how to cook jollof rice", "https://lite.duckduckgo.com/lite/?q=how+to+cook+jollof+rice"),
    ("python", "https://lite.duckduckgo.com/lite/?q=python"),
])
def test_to_url(text, expected):
    assert urls.to_url(text) == expected


def test_script_urls_are_never_loaded():
    for bad in ("javascript:alert(1)", "JavaScript:fetch('//x')", "data:text/html,<script>x</script>"):
        assert urls.to_url(bad).startswith("https://lite.duckduckgo.com/")


def test_search_form():
    assert urls.search_form() == ("https://lite.duckduckgo.com/lite/", "q")
    assert urls.search_form("wikipedia") == ("https://en.m.wikipedia.org/w/index.php", "search")


# ── session & settings ───────────────────────────────────────────────

def test_session_roundtrip_and_validation(isolated_home):
    Session(["https://a.example", "https://b.example"], 1).save()
    s = Session.load()
    assert s.tabs == ["https://a.example", "https://b.example"] and s.active == 1
    with open(storage.data_file("session.json"), "w") as f:
        f.write('{"tabs": [1, "", "https://ok.example"], "active": 9}')
    s = Session.load()
    assert s.tabs == ["https://ok.example"] and s.active == 0
    with open(storage.data_file("session.json"), "w") as f:
        f.write("garbage")
    assert Session.load().tabs == []


def test_settings_roundtrip_and_validation(isolated_home):
    st = Settings.load()
    assert st.mode == "auto"
    st.mode, st.naira_per_gb = "ultra", 700.0
    st.save()
    assert Settings.load().mode == "ultra" and Settings.load().naira_per_gb == 700.0
    with open(storage.data_file("settings.json"), "w") as f:
        f.write('{"mode": "turbo", "naira_per_gb": 900, "zoom": "big"}')
    st = Settings.load()
    assert st.mode == "auto" and st.naira_per_gb == 900.0 and st.zoom == 1.0


# ── built-in pages ───────────────────────────────────────────────────

def test_pages_escape_everything():
    evil = '<script>alert("x")</script>'
    home = pages.home(MODES["lite"], ConnectionInfo("wifi", name=evil), evil, "auto",
                      "https://lite.duckduckgo.com/lite/", 2)
    err = pages.error(f'https://x.example/{evil}', evil, MODES["full"], offline=True)
    saved = pages.saved_list([{"id": "1-x", "title": evil, "url": evil, "saved": evil}])
    tls = pages.tls_error(evil, evil)
    for page in (home, err, saved, tls):
        assert "<script>alert" not in page
    assert "switch to Ultra" in err and "offline" in err
    assert "Nothing saved yet" in pages.saved_list([])
