import os
import subprocess

import pytest

from core import exam_mode as em
from core import lab_mode as lm
from test_lab_mode import FakeSystem, enabled, lab  # noqa: F401  (fixtures)

UID = os.getuid()


class Net:
    """Fake resolvectl/nft/usermod/systemctl/loginctl on top of the lab test double."""

    def __init__(self, fake: FakeSystem, hosts=None):
        self.fake = fake
        self.hosts = hosts if hosts is not None else {
            "cbt.uni.edu.ng": ["196.46.20.10", "2001:db8::10"], "cdn.uni.edu.ng": ["196.46.20.11"]}
        self.table = False
        self.rules = []
        self.nft_fails = False
        self.shells = {"lab": "/bin/bash"}
        self.sessions = {}            # id -> {"Class": ..., "Type": ..., "TTY": ...}
        self.gettys = ["getty@tty1.service", "getty@tty2.service"]
        self.grub_dir = None          # set by the fixture: like /etc/grub.d
        self.grub_cfg = None
        self.grub_fails = False

    def update_grub(self, argv):
        """grub-mkconfig, simplified: every executable script in grub.d, in
        order, its output into grub.cfg (the real 09_primers_exam runs)."""
        self.fake.calls.append(argv)
        if self.grub_fails:
            return subprocess.CompletedProcess(argv, 1, "", "grub-mkconfig failed")
        out = "# grub.cfg header\n"
        for name in sorted(os.listdir(self.grub_dir)):
            path = os.path.join(self.grub_dir, name)
            if os.access(path, os.X_OK):
                r = subprocess.run(["sh", path], capture_output=True, text=True)
                if r.returncode != 0:
                    return subprocess.CompletedProcess(argv, 1, "", f"{name}: {r.stderr}")
                out += r.stdout
        with open(self.grub_cfg, "w") as f:
            f.write(out)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def run(self, argv):
        argv = list(argv)
        ok = lambda out="": subprocess.CompletedProcess(argv, 0, out, "")  # noqa: E731
        if argv[0] == "update-grub":
            return self.update_grub(argv)
        if argv[0] == "resolvectl":
            ips = self.hosts.get(argv[-1], [])
            out = "".join(f"{argv[-1]}: {ip:<30} -- link: ens3\n" if i == 0 else f"{' ' * 16}{ip:<30} -- link: ens3\n"
                          for i, ip in enumerate(ips))
            return subprocess.CompletedProcess(argv, 0 if out else 1, out, "" if out else "resolve call failed")
        if argv[:2] == ["getent", "passwd"]:
            shell = self.shells.get(argv[2])
            return ok(f"{argv[2]}:x:1000:1000::/home/{argv[2]}:{shell}\n") if shell else \
                subprocess.CompletedProcess(argv, 2, "", "")
        if argv[0] == "usermod" and argv[1] == "--shell":
            self.fake.calls.append(argv)
            self.shells[argv[3]] = argv[2]
            return ok()
        if argv[0] == "loginctl":
            self.fake.calls.append(argv)
            if argv[1] == "list-sessions":
                return ok("".join(f"{sid} 1000 someone seat0\n" for sid in self.sessions))
            if argv[1] == "show-session":
                props = self.sessions.get(argv[2], {})
                if "--value" in argv:
                    return ok(props.get(argv[4], "") + "\n")
                return ok("".join(f"{k}={v}\n" for k, v in props.items()))
        if argv[:2] == ["systemctl", "list-units"]:
            self.fake.calls.append(argv)
            return ok("".join(f"{u} loaded active running Getty\n" for u in self.gettys))
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
    r = lab.root
    (r / "etc").mkdir(exist_ok=True)
    (r / "etc/hosts").write_text("127.0.0.1 localhost\n10.0.0.9 intranet.uni.edu.ng\n")
    paths = em.ExamPaths(conf=str(r / "etc/primers/exam.conf"), pkla=str(r / "polkit/60-primers-exam.paths.pkla"),
                         rules=str(r / "run/primers-exam.nft"), xorg=str(r / "xorg.conf.d/90-primers-exam.conf"),
                         sysctl=str(r / "sysctl.d/90-primers-exam.conf"), hosts=str(r / "etc/hosts"),
                         state=str(r / "var/lib/primers/exam"), exam_shell="/usr/lib/primers/exam-shell",
                         lightdm=str(r / "lightdm"), log=str(r / "var/log/primers/exam.jsonl"),
                         boot_id=str(r / "boot_id"), grub_script=str(r / "grub.d/09_primers_exam"),
                         grub_default=str(r / "default/grub.d/90-primers-exam.cfg"),
                         grub_cfg=str(r / "boot/grub/grub.cfg"), cmdline=str(r / "cmdline"),
                         greeter_state=str(r / "lightdm-greeter/state"))
    (r / "boot_id").write_text("b0a7-1d\n")
    (r / "cmdline").write_text("BOOT_IMAGE=/boot/vmlinuz root=UUID=1234 ro quiet splash\n")
    (r / "grub.d").mkdir()
    net.grub_dir, net.grub_cfg = str(r / "grub.d"), paths.grub_cfg
    (r / "lightdm/lightdm.conf.d").mkdir(parents=True)
    (r / "lightdm/lightdm.conf").write_text("[Seat:*]\nautologin-user=staff\nautologin-user-timeout=0\n")
    (r / "lightdm/lightdm.conf.d/50-primers.conf").write_text("[Seat:*]\ngreeter-session=lightdm-gtk-greeter\n")
    e = em.ExamMode(lab, paths=paths, run=net.run, log=lab.fake.logs.append, is_root=lambda: True)
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
    assert em.read_config(exam.paths.conf).url == "https://cbt.uni.edu.ng/test"
    rules = exam.net.rules[-1]
    assert f"meta skuid {UID} jump exam" in rules
    assert "elements = { 196.46.20.10, 196.46.20.11 }" in rules and "elements = { 2001:db8::10 }" in rules
    assert "tcp dport { 80, 443 } accept" in rules and "counter reject" in rules
    pkla = open(exam.paths.pkla).read()
    assert "Identity=unix-user:lab" in pkla and "Action=*" in pkla and "ResultActive=no" in pkla
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
    assert not os.path.exists(exam.paths.conf) and not exam.net.table


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
    assert not os.path.exists(exam.paths.conf)


def test_firewall_failure_rolls_everything_back(exam):
    enabled(exam.lab)
    exam.net.nft_fails = True
    with pytest.raises(em.ExamError, match="could not set up the exam firewall"):
        exam.start("https://cbt.uni.edu.ng/")
    assert not os.path.exists(exam.paths.conf) and not os.path.exists(exam.paths.pkla)


def test_only_one_exam_at_a_time(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    with pytest.raises(em.ExamError, match="already running"):
        exam.start("https://cbt.uni.edu.ng/other")


def test_stop_undoes_everything(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    assert exam.stop() == []
    assert not os.path.exists(exam.paths.conf) and not os.path.exists(exam.paths.pkla) and not exam.net.table
    assert ["nft", "delete", "table", "inet", "primers_exam"] in exam.lab.fake.calls
    assert "(exam-stop)" in open(os.path.join(exam.lab.paths.state, "last-reset")).read()
    with pytest.raises(em.ExamError, match="no exam is running"):
        exam.stop()


def allow4(rules: str) -> str:
    line = next(l for l in rules.splitlines() if "set allow4" in l)
    return line.split("elements = {", 1)[1].split("}", 1)[0].strip() if "elements" in line else ""


def test_refresh(exam):
    enabled(exam.lab)
    now = [1_000_000.0]
    exam.clock = lambda: now[0]
    assert exam.refresh() is False
    exam.start("https://cbt.uni.edu.ng/")
    exam.net.hosts["cbt.uni.edu.ng"] = ["196.46.20.99"]          # the server moved
    now[0] += 300
    assert exam.refresh() is True
    # New connections go to the new address; the old one stays allowed for a while
    assert "196.46.20.99\tcbt.uni.edu.ng" in open(exam.paths.hosts).read()
    assert "196.46.20.10" not in open(exam.paths.hosts).read()
    assert allow4(exam.net.rules[-1]) == "196.46.20.10, 196.46.20.99"
    assert any("cbt.uni.edu.ng moved: now also 196.46.20.99" in line for line in exam.lab.fake.logs)

    now[0] += em.ADDRESS_GRACE                                  # an hour later: only the new one
    assert exam.refresh() is True
    assert allow4(exam.net.rules[-1]) == "196.46.20.99"

    exam.net.hosts = {}                                         # offline: keep the last good addresses
    assert exam.refresh() is True
    assert allow4(exam.net.rules[-1]) == "196.46.20.99"
    assert any("last known addresses" in line for line in exam.lab.fake.logs)

    exam.net.table = False                                      # power cut, offline: still the last ones
    assert exam.refresh() is True
    assert allow4(exam.net.rules[-1]) == "196.46.20.99"
    assert "196.46.20.99\tcbt.uni.edu.ng" in open(exam.paths.hosts).read()


def test_refresh_with_nothing_known_blocks_everything(exam):
    enabled(exam.lab)
    now = [1_000_000.0]
    exam.clock = lambda: now[0]
    exam.start("https://cbt.uni.edu.ng/")
    exam.net.hosts = {}
    with open(exam.paths.hosts, "w") as f:                      # pinned block lost
        f.write("127.0.0.1 localhost\n")
    now[0] += em.ADDRESS_GRACE + 1                              # and nothing seen recently
    assert exam.refresh() is True
    assert "elements" not in exam.net.rules[-1] and "counter reject" in exam.net.rules[-1]


def test_the_timer_refresh_only_touches_addresses(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    applied = len(exam.net.rules)
    calls = len(exam.lab.fake.calls)
    assert exam.refresh(addresses_only=True) is True
    assert len(exam.net.rules) == applied                      # nothing changed: firewall left alone
    assert not [c for c in exam.lab.fake.calls[calls:] if c[0] in ("usermod", "sysctl", "update-grub")
                or c[:2] == ["systemctl", "mask"]]
    exam.net.hosts["cbt.uni.edu.ng"] = ["196.46.20.99"]
    assert exam.refresh(addresses_only=True) is True
    assert len(exam.net.rules) == applied + 1
    assert allow4(exam.net.rules[-1]) == "196.46.20.10, 196.46.20.99"
    exam.net.table = False                                      # firewall gone: put back
    assert exam.refresh(addresses_only=True) is True
    assert len(exam.net.rules) == applied + 2


def test_addresses_per_server_are_capped(exam):
    enabled(exam.lab)
    now = [1_000_000.0]
    exam.clock = lambda: now[0]
    exam.start("https://cbt.uni.edu.ng/")
    for i in range(40):                                         # a CDN rotating through many addresses
        exam.net.hosts["cbt.uni.edu.ng"] = [f"196.46.21.{i}"]
        now[0] += 60
        exam.refresh(addresses_only=True)
    got = allow4(exam.net.rules[-1]).split(", ")
    assert len(got) == em.MAX_ADDRESSES_PER_HOST and "196.46.21.39" in got and "196.46.21.0" not in got


def test_stop_forgets_the_addresses(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    assert os.path.exists(exam._seen_path())
    exam.stop()
    assert not os.path.exists(exam._seen_path())


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
    assert "oifname" not in rules and "tcp dport { 80, 443 }" in rules   # not even loopback (no DNS)
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


# ------------------------------------------------------------------ #
#  Escape routes (ADR 0003)
# ------------------------------------------------------------------ #

def test_start_locks_consoles_sysrq_and_shell(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    xorg = open(exam.paths.xorg).read()
    assert 'Option "DontVTSwitch" "true"' in xorg and 'Option "DontZap" "true"' in xorg
    assert open(exam.paths.sysctl).read().splitlines()[-1] == "kernel.sysrq = 0"
    calls = exam.lab.fake.calls
    assert ["sysctl", "-q", "-w", "kernel.sysrq=0"] in calls
    assert ["systemctl", "mask", "getty@.service", "autovt@.service"] in calls
    assert ["usermod", "--shell", "/usr/lib/primers/exam-shell", "lab"] in calls
    assert exam.net.shells["lab"] == "/usr/lib/primers/exam-shell"
    assert exam.status()["consoles_locked"] is True


def test_only_idle_consoles_are_stopped(exam):
    enabled(exam.lab)
    exam.net.sessions = {"c2": {"Class": "user", "Type": "tty", "TTY": "tty2"}}   # staff on tty2
    exam.start("https://cbt.uni.edu.ng/")
    calls = exam.lab.fake.calls
    assert ["systemctl", "stop", "getty@tty1.service"] in calls
    assert ["systemctl", "stop", "getty@tty2.service"] not in calls


STOP_DM = ["systemctl", "stop", "display-manager.service"]
START_DM = ["systemctl", "start", "display-manager.service"]


def test_login_screen_restarts_locked_unless_someone_is_on_the_desktop(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    calls = exam.lab.fake.calls
    assert STOP_DM in calls and START_DM in calls and calls.index(STOP_DM) < calls.index(START_DM)
    exam.stop()
    exam.lab.fake.calls.clear()
    exam.net.sessions = {"5": {"Class": "user", "Type": "x11", "TTY": "", "State": "closing"}}
    exam.start("https://cbt.uni.edu.ng/")                       # a session that is ending doesn't count
    assert START_DM in exam.lab.fake.calls
    exam.stop()
    exam.lab.fake.calls.clear()
    exam.net.sessions = {"5": {"Class": "user", "Type": "x11", "TTY": "", "State": "active"}}
    _, warnings = exam.start("https://cbt.uni.edu.ng/")
    assert STOP_DM not in exam.lab.fake.calls and START_DM not in exam.lab.fake.calls
    assert any("sign out of the desktop" in w for w in warnings)


def test_starting_an_exam_loads_the_exam_browser_into_memory(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    assert ["systemctl", "start", "--no-block", "primers-exam-prewarm.service"] in exam.lab.fake.calls
    unit = open(os.path.join(os.path.dirname(__file__), "..", "..", "primers-distro", "overlays", "etc", "systemd",
                             "system", "primers-exam-prewarm.service")).read()
    assert "ConditionPathExists=/etc/primers/exam.conf" in unit and "IOSchedulingClass=idle" in unit
    assert "After=display-manager.service" in unit and "Nice=19" in unit


def test_the_login_screen_offers_the_lab_account_during_an_exam(exam):
    """It remembers the last account chosen (often the administrator's):
    candidates mustn't have to pick theirs. Written while it is stopped, so
    its own save on stopping can't overwrite it; again at boot."""
    enabled(exam.lab)
    state = exam.paths.greeter_state
    os.makedirs(os.path.dirname(state))
    with open(state, "w") as f:
        f.write("[greeter]\nlast-user=labadmin\nlast-session=openbox\n")
    seen = []
    real_run = exam.run

    def run(argv, *a, **kw):
        if argv[:2] == ["systemctl", "start"] and "display-manager" in argv[-1]:
            seen.append(open(state).read())
        return real_run(argv, *a, **kw)
    exam.run = run
    exam.start("https://cbt.uni.edu.ng/")
    assert seen and "last-user=lab\n" in seen[0] and "last-session=openbox" in seen[0]
    with open(state, "w") as f:
        f.write("[greeter]\nlast-user=labadmin\n")            # someone else used the PC meanwhile
    assert exam.refresh()                                       # the boot refresh
    assert open(state).read() == "[greeter]\nlast-user=lab\n"


@pytest.mark.parametrize("old,want", [
    ("", "[greeter]\nlast-user=lab\n"),
    ("[greeter]\nlast-user=labadmin\nlast-session=openbox\n", "[greeter]\nlast-user=lab\nlast-session=openbox\n"),
    ("[other]\nx=1\n", "[other]\nx=1\n[greeter]\nlast-user=lab\n"),
    ("[greeter]\nlast-session=openbox\n[other]\nx=1\n", "[greeter]\nlast-session=openbox\nlast-user=lab\n[other]\nx=1\n"),
])
def test_greeter_state_text(old, want):
    assert em.greeter_state_text(old, "lab") == want


def test_exam_servers_are_pinned_so_the_lab_account_needs_no_dns(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/", ["intranet.uni.edu.ng", "10.0.2.2"])
    hosts = open(exam.paths.hosts).read()
    outside, block = em.split_hosts(hosts)
    assert "10.0.0.9 intranet.uni.edu.ng" in outside          # the administrator's entries stay
    assert "196.46.20.10\tcbt.uni.edu.ng" in block and "2001:db8::10\tcbt.uni.edu.ng" in block
    assert "10.0.0.9\tintranet.uni.edu.ng" in block            # names only in /etc/hosts work too
    assert "10.0.2.2" not in block                              # addresses need no pin
    assert "10.0.2.2" in exam.net.rules[-1] and "10.0.0.9" in exam.net.rules[-1]


def test_refresh_follows_a_moved_server_not_its_own_pin(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    exam.net.hosts["cbt.uni.edu.ng"] = ["196.46.20.77"]
    exam.refresh()
    block = em.split_hosts(open(exam.paths.hosts).read())[1]
    assert "196.46.20.77\tcbt.uni.edu.ng" in block and "196.46.20.10" not in block


def test_stop_undoes_every_lock(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/")
    exam.stop()
    for path in (exam.paths.xorg, exam.paths.sysctl, exam.paths.pkla, exam.paths.conf):
        assert not os.path.exists(path), path
    calls = exam.lab.fake.calls
    assert ["systemctl", "unmask", "getty@.service", "autovt@.service"] in calls
    assert ["sysctl", "-q", "--system"] in calls
    assert exam.net.shells["lab"] == "/bin/bash"
    assert open(exam.paths.hosts).read() == "127.0.0.1 localhost\n10.0.0.9 intranet.uni.edu.ng\n"


def test_failed_start_leaves_nothing_locked(exam):
    enabled(exam.lab)
    exam.net.nft_fails = True
    with pytest.raises(em.ExamError):
        exam.start("https://cbt.uni.edu.ng/")
    for path in (exam.paths.xorg, exam.paths.sysctl, exam.paths.pkla, exam.paths.conf):
        assert not os.path.exists(path), path
    assert exam.net.shells["lab"] == "/bin/bash"


@pytest.mark.parametrize("output, v4, v6", [
    ("cbt.x: 196.46.20.10                  -- link: ens3\n      2001:db8::10 -- link: ens3\n",
     {"196.46.20.10"}, {"2001:db8::10"}),
    ("cbt.x: resolve call failed: 'cbt.x' not found\n", set(), set()),
    ("", set(), set()),
])
def test_parse_resolvectl(output, v4, v6):
    got = em.parse_resolvectl(output)
    assert (got.v4, got.v6) == (v4, v6)


def test_hosts_text_round_trip():
    original = "127.0.0.1 localhost\n"
    pinned = em.hosts_text(original, {"b.x": em.Addresses({"1.2.3.4"}), "a.x": em.Addresses(set(), {"::1"})})
    assert em.split_hosts(pinned) == (original, "::1\ta.x\n1.2.3.4\tb.x\n")
    assert em.hosts_text(pinned, {}) == original
    assert em.hosts_text("127.0.0.1 localhost", {}) == "127.0.0.1 localhost\n"


def test_automatic_sign_in_is_suspended_during_the_exam(exam):
    enabled(exam.lab)
    conf = exam.lab.root / "lightdm/lightdm.conf"
    exam.start("https://cbt.uni.edu.ng/")
    text = conf.read_text()
    assert "#primers-exam# autologin-user=staff" in text and "\nautologin-user=staff" not in text
    assert "autologin-user-timeout=0" in text
    exam.stop()
    assert conf.read_text() == "[Seat:*]\nautologin-user=staff\nautologin-user-timeout=0\n"


@pytest.mark.parametrize("line, kept", [
    ("autologin-user=lab", True), ("autologin-user=", True), ("#autologin-user=staff", True),
    ("autologin-user = staff", False), ("autologin-user=staff", False),
])
def test_suspend_autologin(line, kept):
    out = em.suspend_autologin(line + "\n", "lab")
    assert (out == line + "\n") is kept
    assert em.restore_autologin(out) == line + "\n"
