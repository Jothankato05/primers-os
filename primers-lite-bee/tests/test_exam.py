import pytest

from litebee import exam, pages

CONF = """# Exam Mode, written by primers-exam.
EXAM_URL=https://cbt.veritas.edu.ng/start
ALLOW=cbt.veritas.edu.ng cdn.example.com 10.0.0.5
PORTS=80,443
STARTED=2026-11-24 09:00:00 UTC
"""


def test_parse_conf():
    policy = exam.parse(CONF)
    assert policy.url == "https://cbt.veritas.edu.ng/start"
    assert policy.hosts == {"cbt.veritas.edu.ng", "cdn.example.com", "10.0.0.5"}
    assert policy.main_host == "cbt.veritas.edu.ng"


@pytest.mark.parametrize("text", [
    "", "EXAM_URL=ftp://x.com/\nALLOW=x.com\n", "EXAM_URL=https://a.com/\nALLOW=\n",
    "EXAM_URL=https://a.com/\nALLOW=b.com\n",            # the exam host itself must be allowed
    "EXAM_URL=https://a.com/\nALLOW=a.com bad_host!\n", "ALLOW=a.com\n",
])
def test_damaged_or_missing_conf_means_no_exam(text):
    assert exam.parse(text) is None


@pytest.mark.parametrize("uri, ok", [
    ("https://cbt.veritas.edu.ng/q/12", True), ("http://cbt.veritas.edu.ng/", True),
    ("https://CDN.example.com/app.js", True), ("http://10.0.0.5:8080/x", True), ("about:blank", True),
    ("https://evil.cbt.veritas.edu.ng/", False), ("https://cbt.veritas.edu.ng.evil.com/", False),
    ("https://www.google.com/search?q=answer", False), ("file:///etc/passwd", False),
    ("bee:home", False), ("data:text/html,<h1>notes</h1>", False), ("javascript:alert(1)", False),
    ("https://user@www.google.com/", False),
])
def test_only_exam_servers_are_allowed(uri, ok):
    assert exam.parse(CONF).allows(uri) is ok


def test_load_uses_env_override_and_handles_missing(tmp_path, monkeypatch):
    path = tmp_path / "exam.conf"
    monkeypatch.setenv("PRIMERS_EXAM_CONF", str(path))
    assert exam.load() is None
    path.write_text(CONF)
    assert exam.load().main_host == "cbt.veritas.edu.ng"


def test_exam_error_page_escapes():
    page = pages.exam_error('https://cbt.x/"><script>', "<b>timeout</b>")
    assert "<script>" not in page and "&lt;b&gt;timeout&lt;/b&gt;" in page and "invigilator" in page


def test_exam_error_page_links_back_to_the_exam():
    page = pages.exam_error("http://cbt.x/q2", "refused", "http://cbt.x/start")
    assert 'href="http://cbt.x/start">Back to the exam' in page and 'href="http://cbt.x/q2">Try again' in page
    assert "Back to the exam" not in pages.exam_error("http://cbt.x/start", "refused", "http://cbt.x/start")
