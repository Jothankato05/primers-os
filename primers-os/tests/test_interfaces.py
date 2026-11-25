import json
import urllib.request

import pytest

from interface.voice.listener import VoiceListener, strip_wake_word

flask = pytest.importorskip("flask")

from interface.gui.dashboard import DashboardServer, create_app  # noqa: E402


@pytest.mark.parametrize("text, expected", [
    ("primers system status", "system status"),
    ("Primers, show me processes.", "show me processes"),
    ("primers", None),
    ("hey there", None),
    ("", None),
])
def test_wake_word(text, expected):
    assert strip_wake_word(text) == expected


def test_voice_dispatches_to_callback():
    got = []
    v = VoiceListener(on_command=got.append)
    assert v.handle_transcript("primers what is 2 plus 2") == "what is 2 plus 2"
    assert v.handle_transcript("unrelated chatter") is None
    assert got == ["what is 2 plus 2"]


@pytest.fixture
def app(shell):
    shell.sm.refresh(interval=0.05)
    return create_app(shell.sm, shell.pm, shell.se, shell.kernel, shell.gpa, shell.settings)


def test_dashboard_api(app):
    c = app.test_client()
    st = c.get("/api/status", headers={"Host": "localhost:5000"}).get_json()
    assert isinstance(st["cpu"], float) and isinstance(st["memory_percent"], float)
    assert st["version"] == "1.0.0-genesis"
    procs = c.get("/api/processes", headers={"Host": "127.0.0.1"}).get_json()
    assert procs and {"pid", "name", "cpu", "memory", "status"} <= set(procs[0])
    assert c.get("/api/gpa").get_json() == {"cgpa": 0.0, "credits": 0.0}
    assert isinstance(c.get("/api/threats").get_json(), list)
    assert isinstance(c.get("/api/network").get_json(), list)


def test_dashboard_security_headers_and_host_check(app):
    c = app.test_client()
    r = c.get("/", headers={"Host": "localhost"})
    assert r.status_code == 200
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"
    assert b"innerHTML" not in r.data          # rendering never parses data as HTML
    assert c.get("/api/status", headers={"Host": "evil.example:5000"}).status_code == 403
    assert c.get("/api/status", headers={"Host": "[::1]:5000"}).status_code == 200


def test_dashboard_server_start_stop(app):
    srv = DashboardServer(app, "127.0.0.1", 0)
    srv.start()
    try:
        assert srv.running
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/api/status", timeout=5) as r:
            assert json.load(r)["version"] == "1.0.0-genesis"
    finally:
        srv.stop()
    assert not srv.running


def test_shell_gui_start_stop(shell, capsys, monkeypatch):
    monkeypatch.setattr(shell.settings, "GUI_PORT", 0)
    shell.execute("gui start")
    assert shell.gui_active
    shell.execute("gui stop")
    assert not shell.gui_active
    out = capsys.readouterr().out
    assert "started" in out and "stopped" in out
