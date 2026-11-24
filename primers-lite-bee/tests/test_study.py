import os
import time

import pytest

from litebee import pages, study, urls


@pytest.fixture
def gate(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    os.makedirs(tmp_path / "state" / "primers")
    os.makedirs(tmp_path / "config" / "primers")
    g = study.StudyGate()

    def start(minutes=25):
        now = int(time.time())
        with open(g.state, "w") as f:
            f.write(f"started={now}\nuntil={now + minutes * 60}\nminutes={minutes}\n")
    g.start = start
    return g


@pytest.mark.parametrize("uri, site", [
    ("https://www.youtube.com/watch?v=x", "youtube.com"), ("https://m.facebook.com/", "facebook.com"),
    ("http://youtu.be/abc", "youtu.be"), ("https://x.com/home", "x.com"),
    ("https://www.sportybet.com/ng/", "sportybet.com"),
    ("https://notyoutube.com/", None), ("https://youtube.com.evil.example/", None),
    ("https://en.m.wikipedia.org/wiki/Physics", None), ("bee:home", None), ("file:///x", None), ("", None),
])
def test_paused_site(uri, site):
    assert study.paused_site(uri, study.DEFAULT_SITES) == site


def test_nothing_is_paused_without_a_session(gate):
    assert gate.check("https://www.youtube.com/") is None


def test_sites_are_paused_during_a_session_and_open_after(gate):
    gate.start(25)
    assert gate.check("https://www.youtube.com/") == "youtube.com"
    assert gate.check("https://en.wikipedia.org/") is None
    with open(gate.state, "w") as f:
        f.write(f"started=1\nuntil={int(time.time()) - 1}\nminutes=25\n")
    assert gate.check("https://www.youtube.com/") is None


def test_users_can_add_and_allow_sites(gate):
    gate.start()
    with open(gate.sites_file, "w") as f:
        f.write("# my distractions\nnews.ycombinator.com\n-youtube.com  # lectures\n.Chess.com\n")
    assert gate.check("https://news.ycombinator.com/") == "news.ycombinator.com"
    assert gate.check("https://www.chess.com/play") == "chess.com"
    assert gate.check("https://www.youtube.com/watch?v=lecture") is None
    assert gate.check("https://www.tiktok.com/") == "tiktok.com"


def test_damaged_session_file_pauses_nothing(gate):
    with open(gate.state, "w") as f:
        f.write("until=later\n")
    assert gate.check("https://www.youtube.com/") is None


def test_study_page(gate):
    until = int(time.time()) + 18 * 60
    html_text = pages.study_paused("youtube.com", until)
    assert "Study Mode is on" in html_text and "<b>youtube.com</b>" in html_text
    assert "18 minutes" in html_text
    assert "<script" not in pages.study_paused("<script>", until).replace("&lt;script&gt;", "")
    assert "session is over" in pages.study_paused("youtube.com", None)
    uri = pages.study_uri("youtube.com")
    assert uri == "bee:study?site=youtube.com" and urls.query_param(uri, "site") == "youtube.com"
    assert urls.query_param("bee:study", "site") == ""
