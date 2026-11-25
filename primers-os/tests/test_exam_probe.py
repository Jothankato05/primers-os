"""primers-exam probe: from what the exam site loaded to the start command."""

import json
import os
import subprocess

import pytest

from core import exam_mode as em
from core import exam_probe as ep
from test_exam_mode import exam  # noqa: F401  (fixture)
from test_lab_mode import enabled, lab  # noqa: F401  (fixtures)

REPORT = {
    "start": "https://cbt.uni.edu.ng/login/index.php",
    "main_host": "cbt.uni.edu.ng",
    "hosts": {
        "cbt.uni.edu.ng": {"schemes": ["https"], "ports": [443], "requests": 42, "first": "https://cbt.uni.edu.ng/"},
        "cdn.jsdelivr.net": {"schemes": ["https"], "ports": [443], "requests": 3,
                             "first": "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"},
        "media.uni.edu.ng": {"schemes": ["https"], "ports": [8443], "requests": 2,
                             "first": "https://media.uni.edu.ng:8443/v.mp4"},
        "v6only.uni.edu.ng": {"schemes": ["http"], "ports": [80], "requests": 1, "first": "http://v6only.uni.edu.ng/"},
        "gone.example": {"schemes": ["https"], "ports": [443], "requests": 1, "first": "https://gone.example/x.js"},
    },
    "other_schemes": ["data"],
    "failed": [{"uri": "https://gone.example/x.js", "error": "Could not resolve host"}],
}
ADDRS = {"cbt.uni.edu.ng": (["196.46.20.10"], ["2001:db8::10"]),
         "cdn.jsdelivr.net": (["151.101.1.229"], []),
         "media.uni.edu.ng": (["196.46.20.12"], []),
         "v6only.uni.edu.ng": ([], ["2001:db8::66"]),
         "gone.example": ([], [])}


def analysed(closed=()):
    return ep.analyse(REPORT, resolve=lambda h: ADDRS[h], connect=lambda a, p: (a, p) not in closed)


def test_findings_put_the_exam_site_first_and_resolve_both_families():
    r = analysed()
    assert [f.host for f in r.findings][0] == "cbt.uni.edu.ng" and r.findings[0].main
    v6 = next(f for f in r.findings if f.host == "v6only.uni.edu.ng")
    assert v6.v6 == ["2001:db8::66"] and not v6.v4 and v6.reachable == {80: True}
    assert not next(f for f in r.findings if f.host == "gone.example").resolved


def test_the_start_command_lists_every_other_server_with_its_unusual_ports():
    r = analysed()
    assert r.allow_args() == ["cdn.jsdelivr.net", "gone.example", "media.uni.edu.ng:8443", "v6only.uni.edu.ng"]
    assert r.command() == ("sudo primers-exam start https://cbt.uni.edu.ng/login/index.php "
                           "--allow cdn.jsdelivr.net --allow gone.example --allow media.uni.edu.ng:8443 "
                           "--allow v6only.uni.edu.ng")


def test_the_report_explains_what_will_and_wont_work():
    text = ep.format_result(analysed(closed={("196.46.20.12", 8443)}))
    assert "It used 5 servers:" in text
    assert "gone.example can't be found from this PC" in text
    assert "v6only.uni.edu.ng has only IPv6 addresses" in text
    assert "media.uni.edu.ng didn't answer on port 8443" in text
    assert "--allow media.uni.edu.ng:8443" in text
    assert "v6only.uni.edu.ng is used over plain http" in text
    assert "1 load(s) failed" in text
    assert "Start the exam with:\n  sudo primers-exam start" in text


def test_an_exam_site_with_one_server_needs_no_allow():
    r = ep.analyse({"start": "http://cbt.primers.test:8765/exam.html", "main_host": "cbt.primers.test",
                    "hosts": {"cbt.primers.test": {"schemes": ["http"], "ports": [8765], "requests": 3}}},
                   resolve=lambda h: (["10.0.2.2"], []), connect=lambda a, p: True)
    assert r.allow_args() == []
    assert r.command() == "sudo primers-exam start http://cbt.primers.test:8765/exam.html"


def test_an_ipv6_literal_server_is_bracketed():
    r = ep.analyse({"start": "https://cbt.uni.edu.ng/", "main_host": "cbt.uni.edu.ng",
                    "hosts": {"cbt.uni.edu.ng": {"ports": [443]}, "2001:db8::7": {"ports": [8443]}}},
                   resolve=ep.system_resolve, connect=lambda a, p: True)
    assert r.allow_args() == ["[2001:db8::7]:8443"]


def test_nothing_loaded_says_so():
    assert "Nothing was loaded" in ep.format_result(ep.ProbeResult("https://x.example/", [], [], []))


def test_run_passes_the_report_back_and_cleans_up(tmp_path):
    seen = {}

    def fake(argv):
        seen["argv"] = argv
        path = argv[argv.index("--probe-report") + 1]
        with open(path, "w") as f:
            json.dump(REPORT, f)
        return subprocess.CompletedProcess(argv, 0)
    report = ep.run("https://cbt.uni.edu.ng/login/index.php", 30, runner=fake)
    assert report["main_host"] == "cbt.uni.edu.ng"
    assert seen["argv"][:3] == ["lite-bee", "--probe", "https://cbt.uni.edu.ng/login/index.php"]
    assert seen["argv"][-2:] == ["--probe-seconds", "30"]
    assert not os.path.exists(seen["argv"][4])          # the temporary report is removed


def test_run_reports_a_window_that_said_nothing():
    with pytest.raises(ep.ProbeError, match="didn't report anything"):
        ep.run("https://cbt.uni.edu.ng/", runner=lambda argv: subprocess.CompletedProcess(argv, 1))
    with pytest.raises(ep.ProbeError, match="not a web address"):
        ep.run("file:///etc/passwd", runner=lambda argv: subprocess.CompletedProcess(argv, 0))


@pytest.mark.parametrize("entry,want", [
    ("cdn.uni.edu.ng", ("cdn.uni.edu.ng", None)),
    ("CDN.uni.edu.ng.", ("cdn.uni.edu.ng", None)),
    ("media.uni.edu.ng:8443", ("media.uni.edu.ng", 8443)),
    ("196.46.20.12", ("196.46.20.12", None)),
    ("196.46.20.12:8080", ("196.46.20.12", 8080)),
    ("2001:db8::7", ("2001:db8::7", None)),
    ("[2001:db8::7]:8443", ("2001:db8::7", 8443)),
    ("[2001:db8::7]", ("2001:db8::7", None)),
])
def test_parse_allow(entry, want):
    assert em.parse_allow(entry) == want


@pytest.mark.parametrize("entry", ["cdn.uni.edu.ng:0", "cdn.uni.edu.ng:70000", "cdn.uni.edu.ng:http",
                                   "[2001:db8::7]x", "bad host", "-x.example"])
def test_parse_allow_refuses(entry):
    with pytest.raises(em.ExamError):
        em.parse_allow(entry)


def test_start_with_a_server_on_another_port_opens_that_port(exam):  # noqa: F811
    enabled(exam.lab)
    exam.net.hosts["media.uni.edu.ng"] = ["196.46.20.12"]
    conf, _ = exam.start("https://cbt.uni.edu.ng/test", ["media.uni.edu.ng:8443"])
    assert conf.allow == ["cbt.uni.edu.ng", "media.uni.edu.ng"]
    assert conf.ports == [80, 443, 8443]
    assert "8443" in exam.net.rules[-1]


def test_probe_cli_prints_the_command_and_json(monkeypatch, capsys):
    import primers_exam
    monkeypatch.setattr(ep, "probe", lambda url, seconds=0: analysed())
    assert primers_exam.main(["probe", "https://cbt.uni.edu.ng/login/index.php"]) == 1   # gone.example
    out = capsys.readouterr().out
    assert "sudo primers-exam start https://cbt.uni.edu.ng/login/index.php --allow cdn.jsdelivr.net" in out
    assert primers_exam.main(["probe", "https://cbt.uni.edu.ng/login/index.php", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["allow"][0] == "cdn.jsdelivr.net" and data["servers"][0]["host"] == "cbt.uni.edu.ng"


def test_refresh_cli_follows_addresses_quietly_when_no_exam(monkeypatch):
    import primers_exam
    seen = []
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(em.ExamMode, "refresh", lambda self, addresses_only=False: seen.append(addresses_only) or False)
    assert primers_exam.main(["refresh"]) == 0
    assert seen == [True]


def test_refresh_units_run_only_during_an_exam():
    here = os.path.join(os.path.dirname(__file__), "..", "..", "primers-distro", "overlays", "etc", "systemd", "system")
    service = open(os.path.join(here, "primers-exam-refresh.service")).read()
    timer = open(os.path.join(here, "primers-exam-refresh.timer")).read()
    assert "ConditionPathExists=/etc/primers/exam.conf" in service
    assert "ExecStart=/usr/bin/primers-exam refresh" in service
    assert "OnUnitActiveSec=5min" in timer and "WantedBy=timers.target" in timer
