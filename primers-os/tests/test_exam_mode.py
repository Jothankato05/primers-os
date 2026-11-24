import os
import subprocess

import pytest

from core import exam_mode as em
from core import lab_mode as lm
from test_lab_mode import FakeSystem, enabled, lab  # noqa: F401  (fixtures)

UID = os.getuid()


class Net:
    """Fake getent/nft on top of the lab test double."""

    def __init__(self, fake: FakeSystem, hosts=None):
        self.fake = fake
        self.hosts = hosts if hosts is not None else {
            "cbt.uni.edu.ng": ["196.46.20.10", "2001:db8::10"], "cdn.uni.edu.ng": ["196.46.20.11"]}
        self.table = False
        self.rules = []
        self.nft_fails = False

    def run(self, argv):
        argv = list(argv)
        if argv[0] == "getent":
            out = "".join(f"{ip}      STREAM {argv[2]}\n{ip}      DGRAM\n" for ip in self.hosts.get(argv[2], []))
            return subprocess.CompletedProcess(argv, 0 if out else 2, out, "")
        if argv[0] == "nft":
            self.fake.calls.append(argv)
            if argv[1] == "-f":
                if self.nft_fails:
                    return subprocess.CompletedProcess(argv, 1, "", "Error: syntax error")
                self.rules.append(open(argv[2]).read())
                self.table = True
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv[1] == "list":
                return subprocess.CompletedProcess(argv, 0 if self.table else 1, "", "")
            if argv[1] == "delete":
                self.table = False
                return subprocess.CompletedProcess(argv, 0, "", "")
        return self.fake.run(argv)


@pytest.fixture
def exam(lab):  # noqa: F811
    net = Net(lab.fake)
    e = em.ExamMode(lab, conf=str(lab.root / "etc/primers/exam.conf"),
                    pkla=str(lab.root / "polkit/60-primers-exam.pkla"),
                    rules_file=str(lab.root / "run/primers-exam.nft"), run=net.run, log=lab.fake.logs.append,
                    is_root=lambda: True)
    e.net = net
    return e


def test_exam_needs_lab_mode(exam):
    with pytest.raises(em.ExamError, match="turn on Lab Mode first"):
        exam.start("https://cbt.uni.edu.ng/")
    assert exam.status() == {"active": False}


def test_start_locks_the_lab_account_to_the_exam_servers(exam):
    home = enabled(exam.lab)
    (home / "notes.txt").write_text("cheat sheet")
    conf, warnings = exam.start("https://cbt.uni.edu.ng/test", ["CDN.uni.edu.ng."])
    assert warnings == []
    assert conf.allow == ["cbt.uni.edu.ng", "cdn.uni.edu.ng"] and conf.ports == [80, 443]
    assert em.read_config(exam.conf_path).url == "https://cbt.uni.edu.ng/test"
    rules = exam.net.rules[-1]
    assert f"meta skuid {UID} jump exam" in rules
    assert "elements = { 196.46.20.10, 196.46.20.11 }" in rules and "elements = { 2001:db8::10 }" in rules
    assert "tcp dport { 80, 443 } accept" in rules and "counter reject" in rules
    pkla = open(exam.pkla).read()
    assert "Identity=unix-user:lab" in pkla and "filesystem-mount" in pkla and "ResultActive=no" in pkla
    assert not (home / "notes.txt").exists()                       # open lab sessions were ended
    assert "(exam-start)" in open(os.path.join(exam.lab.paths.state, "last-reset")).read()
    st = exam.status()
    assert st["active"] and st["firewall"] and st["usb_blocked"]
    assert any(line.startswith("exam started: https://cbt.uni.edu.ng/test") for line in exam.lab.fake.logs)


def test_local_server_with_port(exam):
    enabled(exam.lab)
    conf, _ = exam.start("http://10.0.2.2:8765/exam.html")
    assert conf.ports == [80, 443, 8765] and conf.allow == ["10.0.2.2"]
    assert "elements = { 10.0.2.2 }" in exam.net.rules[-1]
    assert "tcp dport { 80, 443, 8765 }" in exam.net.rules[-1]


def test_unknown_server_is_refused(exam):
    enabled(exam.lab)
    with pytest.raises(em.ExamError, match="can't find the exam server"):
        exam.start("https://nowhere.invalid/")
    assert not os.path.exists(exam.conf_path) and not exam.net.table


def test_extra_server_not_found_is_a_warning(exam):
    enabled(exam.lab)
    _, warnings = exam.start("https://cbt.uni.edu.ng/", ["missing.uni.edu.ng"])
    assert warnings == ["not found, so not reachable during the exam: missing.uni.edu.ng"]


@pytest.mark.parametrize("url, allow", [
    ("ftp://cbt.uni.edu.ng/", []), ("cbt.uni.edu.ng", []), ("https://bad_host/", []),
    ("https://cbt.uni.edu.ng:99999/", []), ("https://cbt.uni.edu.ng/", ["bad host"]),
])
def test_bad_addresses(exam, url, allow):
    enabled(exam.lab)
    with pytest.raises(em.ExamError):
        exam.start(url, allow)
    assert not os.path.exists(exam.conf_path)


def test_firewall_failure_rolls_everything_back(exam):
    enabled(exam.lab)
    exam.net.nft_fails = True
    with pytest.raises(em.ExamError, match="could not set up the exam firewall"):
        exam.start("https://cbt.uni.edu.ng/")
    assert not os.path.exists(exam.conf_path) and not os.path.exists(exam.pkla)


def test_only_one_exam_at_a_time(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    with pytest.raises(em.ExamError, match="already running"):
        exam.start("https://cbt.uni.edu.ng/other")


def test_stop_undoes_everything(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    assert exam.stop() == []
    assert not os.path.exists(exam.conf_path) and not os.path.exists(exam.pkla) and not exam.net.table
    assert ["nft", "delete", "table", "inet", "primers_exam"] in exam.lab.fake.calls
    assert "(exam-stop)" in open(os.path.join(exam.lab.paths.state, "last-reset")).read()
    with pytest.raises(em.ExamError, match="no exam is running"):
        exam.stop()


def test_refresh(exam):
    enabled(exam.lab)
    assert exam.refresh() is False
    exam.start("https://cbt.uni.edu.ng/")
    exam.net.hosts["cbt.uni.edu.ng"] = ["196.46.20.99"]          # the server moved
    assert exam.refresh() is True
    assert "elements = { 196.46.20.99 }" in exam.net.rules[-1]

    exam.net.hosts = {}                                         # offline: keep the last good rules
    count = len(exam.net.rules)
    assert exam.refresh() is True and len(exam.net.rules) == count
    assert any("keeping the previous firewall" in line for line in exam.lab.fake.logs)

    exam.net.table = False                                      # after a reboot, offline: block all
    assert exam.refresh() is True
    assert "elements" not in exam.net.rules[-1] and "counter reject" in exam.net.rules[-1]


def test_refresh_fails_closed_when_the_account_is_unsafe(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    exam.lab.fake.accounts["lab"].groups.append("sudo")
    with pytest.raises(em.ExamError, match="won't use account"):
        exam.refresh()


def test_nft_ruleset_only_touches_the_exam_account():
    rules = em.nft_ruleset(1001, em.Addresses(), [443, 80, 443])
    assert rules.splitlines()[:3] == ["table inet primers_exam", "delete table inet primers_exam",
                                      "table inet primers_exam {"]
    assert "meta skuid 1001 jump exam" in rules and "policy accept" in rules
    assert 'oifname "lo" accept' in rules and "tcp dport { 80, 443 }" in rules
    assert "elements" not in rules


def test_parse_getent_and_config_damage(tmp_path):
    got = em.parse_getent("196.46.20.10    STREAM cbt\n196.46.20.10    DGRAM\n2001:db8::1 RAW\n\n")
    assert got.v4 == {"196.46.20.10"} and got.v6 == {"2001:db8::1"}
    path = tmp_path / "exam.conf"
    assert em.read_config(str(path)) is None
    path.write_text("EXAM_URL=https://a.b/\nALLOW=a.b\nPORTS=80,443,99999\n")
    with pytest.raises(em.ExamError, match="damaged"):
        em.read_config(str(path))


def test_lab_hook_refreshes_the_exam_firewall(monkeypatch):
    import primers_lab
    calls = []

    class FakeExam:
        fail = False

        def __init__(self, lab):
            pass

        def refresh(self):
            calls.append("refresh")
            if FakeExam.fail:
                raise em.ExamError("nft missing")
            return True

        def log(self, message):
            calls.append(message)

    class FakeLab:
        def is_lab_session(self, user=None):
            return user == "lab"

    monkeypatch.setattr(em, "ExamMode", FakeExam)
    assert primers_lab.exam_hook(FakeLab(), "session-setup", "alice") == 0 and calls == []
    assert primers_lab.exam_hook(FakeLab(), "session-cleanup", "lab") == 0 and calls == []
    assert primers_lab.exam_hook(FakeLab(), "session-setup", "lab") == 0 and calls == ["refresh"]
    FakeExam.fail = True
    assert primers_lab.exam_hook(FakeLab(), "boot", None) == 1
    assert "exam firewall not in place" in calls[-1]


def test_cli_status_off(capsys, monkeypatch):
    import primers_exam
    monkeypatch.setattr(em.ExamMode, "status", lambda self: {"active": False})
    assert primers_exam.main(["status"]) == 0
    assert "Exam Mode: off" in capsys.readouterr().out


def test_brain_exam_command(shell, capsys, monkeypatch):
    monkeypatch.setattr(em.ExamMode, "status", lambda self: {"active": False})
    shell.execute("is exam mode on?")
    assert "No exam is running" in capsys.readouterr().out
    monkeypatch.setattr(em.ExamMode, "status", lambda self: {
        "active": True, "url": "https://cbt.uni.edu.ng/", "allow": ["cbt.uni.edu.ng"], "ports": [80, 443],
        "started": "2026-11-24 09:00:00 UTC", "firewall": True, "usb_blocked": True})
    shell.execute("exam")
    out = capsys.readouterr().out
    assert "EXAM MODE" in out and "https://cbt.uni.edu.ng/" in out and "firewall active" in out


def test_status_without_root_says_unknown_not_off(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    exam.is_root = lambda: False
    st = exam.status()
    assert st["active"] and st["firewall"] is None and st["usb_blocked"] is None


def test_cli_status_unknown_without_root(capsys, monkeypatch):
    import primers_exam
    monkeypatch.setattr(em.ExamMode, "status", lambda self: {
        "active": True, "url": "https://cbt.uni.edu.ng/", "allow": ["cbt.uni.edu.ng"], "ports": [80, 443],
        "started": "now", "firewall": None, "usb_blocked": None})
    assert primers_exam.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "Exam Mode: ON" in out and "sudo primers-exam status" in out and "NOT ACTIVE" not in out
