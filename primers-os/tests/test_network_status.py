import pytest

from core import network_status as ns


@pytest.mark.parametrize("out, value", [
    ("u 4\n", 4), ("u 1", 1), ('s "802-3-ethernet"\n', "802-3-ethernet"),
    ('s ""', ""), ("", None), ("garbage", None), ("u x", None), ("b true", None),
])
def test_parse_busctl_value(out, value):
    assert ns.parse_busctl_value(out) == value


@pytest.mark.parametrize("code, metered", [(0, False), (1, True), (2, False), (3, True), (4, False), (None, False)])
def test_metered_states(code, metered):
    st = ns.NetworkStatus(code, 4, "gsm")
    assert st.metered is metered
    assert st.background_downloads_paused is metered


def test_override_and_labels():
    st = ns.NetworkStatus(1, 4, "gsm", override=True)
    assert st.metered and not st.background_downloads_paused
    assert st.connection_text == "Mobile data" and st.connectivity_text == "full"
    assert ns.NetworkStatus(None, None, None).available is False
    assert ns.NetworkStatus(2, 4, "802-11-wireless").connection_text == "Wi-Fi"


def test_read_status_without_networkmanager(monkeypatch):
    monkeypatch.setattr(ns.shutil, "which", lambda _: None)
    st = ns.read_status()
    assert not st.available and not st.background_downloads_paused


def test_datasaver_command(shell, capsys, monkeypatch):
    monkeypatch.setattr(ns, "read_status", lambda: ns.NetworkStatus(3, 4, "gsm"))
    shell.execute("datasaver")
    out = capsys.readouterr().out
    assert "DATA SAVER" in out and "paused" in out and "Mobile data" in out
    monkeypatch.setattr(ns, "read_status", lambda: ns.NetworkStatus(2, 4, "802-3-ethernet"))
    shell.execute("am I on a metered connection?")
    out = capsys.readouterr().out
    assert "normal" in out and "Ethernet" in out
