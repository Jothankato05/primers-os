import os
import signal
import stat
import subprocess

import pytest

from core import lab_mode as lm

UID, GID = os.getuid(), os.getgid()


class FakeSystem:
    """Records system commands; runs the real find/rm so wiping is real."""

    def __init__(self, root):
        self.root = root
        self.calls = []
        self.accounts = {}
        self.killed = []
        self.logs = []

    def run(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        if argv[0] in ("find", "rm"):
            return subprocess.run(argv, capture_output=True, text=True)
        if argv[0] == "useradd":
            name = argv[-1]
            self.accounts[name] = lm.Account(name, UID, GID, argv[argv.index("--home-dir") + 1],
                                             lm.GECOS, [name])
        if argv[0] == "userdel":
            self.accounts.pop(argv[-1], None)
        if argv[:3] == ["usermod", "--append", "--groups"] and argv[-1] in self.accounts:
            self.accounts[argv[-1]].groups.append(argv[3])
        if argv[:2] == ["gpasswd", "--delete"] and argv[2] in self.accounts:
            groups = self.accounts[argv[2]].groups
            if argv[3] in groups:
                groups.remove(argv[3])
        return subprocess.CompletedProcess(argv, 0, "", "")

    def lookup(self, name):
        return self.accounts.get(name)

    def kill(self, pid, sig):
        self.killed.append((pid, sig))
        os.unlink(os.path.join(self.root, "proc", str(pid), "status"))

    def commands(self, name):
        return [c for c in self.calls if c[0] == name]


@pytest.fixture
def lab(tmp_path, monkeypatch):
    # tests run as an ordinary user: allow its UID as the "lab" UID
    monkeypatch.setattr(lm, "UID_MIN", 0)
    r = tmp_path
    for d in ("home", "tmp", "proc", "nm", "crontabs", "linger", "mail", "run"):
        (r / d).mkdir()
    skel = r / "skel"
    (skel / ".config" / "openbox").mkdir(parents=True)
    (skel / ".bashrc").write_text("# bashrc\n")
    (skel / ".config" / "openbox" / "autostart").write_text("tint2 &\n")
    os.chmod(skel / ".config" / "openbox" / "autostart", 0o755)
    os.symlink(".bashrc", skel / ".link")
    os.chmod(skel, 0o755)  # the template must not be group/world-writable, whatever the umask
    (r / "mountinfo").write_text("22 1 8:1 / / rw - ext4 /dev/sda1 rw\n")
    paths = lm.Paths(
        conf=str(r / "etc/primers/lab.conf"), state=str(r / "state"),
        lightdm=str(r / "etc/lightdm/lightdm.conf.d/60-primers-lab.conf"),
        home_root=str(r / "home"), default_template=str(skel), lab_template=str(r / "no-lab-skel"),
        tmp_dirs=(str(r / "tmp"),), nm_connections=str(r / "nm"), crontabs=str(r / "crontabs"),
        linger=str(r / "linger"), mail=str(r / "mail"), proc=str(r / "proc"),
        mountinfo=str(r / "mountinfo"), lock=str(r / "run/lock"))
    fake = FakeSystem(str(r))
    mode = lm.LabMode(paths, run=fake.run, lookup=fake.lookup, log=fake.logs.append,
                      kill=fake.kill, sleep=lambda s: None, trusted_uid=UID)
    mode.fake = fake
    mode.root = r
    return mode


def enabled(lab):
    lab.enable("lab")
    lab.fake.calls.clear()
    return lab.root / "home" / "lab"


def fake_process(lab, pid, uid, state="S (sleeping)"):
    d = lab.root / "proc" / str(pid)
    d.mkdir()
    (d / "status").write_text(f"Name:\tx\nState:\t{state}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")


# ------------------------------------------------------------------ #

def test_enable_creates_account_hooks_and_fresh_home(lab):
    conf = lab.enable()
    assert conf == lm.LabConfig("lab", UID, str(lab.root / "skel"))
    assert lm.read_config(lab.paths.conf) == conf
    useradd = lab.fake.commands("useradd")[0]
    assert "--comment" in useradd and lm.GECOS in useradd and useradd[-1] == "lab"
    assert ["usermod", "--lock", "lab"] in lab.fake.calls
    # no passwordless sign-in until LightDM restarts with the wipe hooks loaded
    assert "nopasswdlogin" not in lab.fake.accounts["lab"].groups
    assert lab.status()["sign_in_ready"] is False
    assert ["systemctl", "enable", lm.UNIT] in lab.fake.calls
    snippet = open(lab.paths.lightdm).read()
    assert "session-setup-script=/usr/bin/primers-lab hook session-setup" in snippet
    assert "session-cleanup-script=/usr/bin/primers-lab hook session-cleanup" in snippet
    home = lab.root / "home" / "lab"
    assert sorted(os.listdir(home)) == [".bashrc", ".config", ".link"]
    assert stat.S_IMODE(os.stat(home).st_mode) == 0o700
    assert "(enabled)" in open(os.path.join(lab.paths.state, "last-reset")).read()


def test_reset_wipes_everything_and_never_follows_links(lab):
    home = enabled(lab)
    outside = lab.root / "precious.txt"
    outside.write_text("not the lab's")
    (home / "Documents" / "deep" / "er").mkdir(parents=True)
    (home / "Documents" / "deep" / "er" / "essay.odt").write_text("student work")
    (home / "-rf").write_text("tricky name")
    (home / ".bashrc").write_text("modified by student")
    os.symlink(str(outside), home / "escape")
    os.symlink(str(lab.root), home / "Documents" / "rootlink")
    lab.reset()
    assert sorted(os.listdir(home)) == [".bashrc", ".config", ".link"]
    assert (home / ".bashrc").read_text() == "# bashrc\n"
    assert os.path.islink(home / ".link") and os.readlink(home / ".link") == ".bashrc"
    assert stat.S_IMODE(os.stat(home / ".config/openbox/autostart").st_mode) == 0o755
    assert outside.read_text() == "not the lab's"
    assert (lab.root / "skel" / ".bashrc").exists()


def test_reset_stops_the_lab_users_processes_only(lab):
    enabled(lab)
    fake_process(lab, 4242, UID)
    fake_process(lab, 4343, UID, state="Z (zombie)")
    fake_process(lab, 1, UID + 1 if UID != 0 else 5000)
    lab.reset()
    assert lab.fake.killed == [(4242, signal.SIGKILL)]
    assert ["systemctl", "stop", f"user@{UID}.service"] in lab.fake.calls


def test_reset_fails_if_processes_survive(lab):
    enabled(lab)
    fake_process(lab, 4242, UID)
    lab.kill = lambda pid, sig: None
    with pytest.raises(lm.LabError, match="still running"):
        lab.reset()


def test_reset_cleans_up_outside_home(lab):
    enabled(lab)
    r = lab.root
    (r / "tmp" / "lab-download").mkdir()
    (r / "tmp" / "lab-download" / "file").write_text("x")
    (r / "tmp" / "loose").write_text("x")
    (r / "crontabs" / "lab").write_text("* * * * * evil\n")
    (r / "linger" / "lab").write_text("")
    (r / "mail" / "lab").write_text("old mail")
    (r / "nm" / "lab-wifi.nmconnection").write_text(
        "[connection]\nid=Lab WiFi\npermissions=user:lab:;\n[wifi]\nssid=x\n")
    (r / "nm" / "shared.nmconnection").write_text(
        "[connection]\nid=Shared\npermissions=user:lab:;user:alice:;\n")
    (r / "nm" / "campus.nmconnection").write_text("[connection]\nid=Campus\n")
    lab.reset()
    assert os.listdir(r / "tmp") == []  # every entry there belongs to the test UID
    assert not (r / "crontabs" / "lab").exists() and not (r / "linger" / "lab").exists()
    assert (r / "mail" / "lab").read_text() == ""
    assert sorted(os.listdir(r / "nm")) == ["campus.nmconnection", "shared.nmconnection"]
    assert ["nmcli", "connection", "reload"] in lab.fake.calls


def test_reset_unmounts_mounts_inside_home(lab):
    home = enabled(lab)
    (lab.root / "mountinfo").write_text(
        "22 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
        f"40 22 0:50 / {home}/usb rw - vfat /dev/sdb1 rw\n"
        f"41 40 0:51 / {home}/usb/my\\040stick rw - fuse x rw\n"
        f"42 22 0:52 / {home} rw - tmpfs tmpfs rw\n")
    lab.reset()
    umounts = lab.fake.commands("umount")
    assert umounts == [["umount", "--lazy", "--", f"{home}/usb/my stick"],
                       ["umount", "--lazy", "--", f"{home}/usb"]]


@pytest.mark.parametrize("change, message", [
    (dict(groups=["lab", "sudo"]), "admin groups: sudo"),
    (dict(home="/root"), "home folder is /root"),
    (dict(uid=UID + 7), "Lab Mode was set up for UID"),
])
def test_reset_refuses_an_account_that_is_not_safe_to_wipe(lab, change, message):
    home = enabled(lab)
    (home / "essay.odt").write_text("must survive")
    acct = lab.fake.accounts["lab"]
    for key, value in change.items():
        setattr(acct, key, value)
    with pytest.raises(lm.LabError, match=message):
        lab.reset()
    assert (home / "essay.odt").read_text() == "must survive"


def test_account_problems_uses_ordinary_uid_range():
    acct = lm.Account("lab", 0, 0, "/home/lab", lm.GECOS, ["lab"])
    assert any("ordinary user" in p for p in lm.account_problems(acct, None, "/home"))
    acct.uid, acct.home = 1001, "/nonexistent-home-root/lab"
    assert lm.account_problems(acct, None, "/nonexistent-home-root") == []
    acct.uid = 65534
    assert any("ordinary user" in p for p in lm.account_problems(acct, None, "/nonexistent-home-root"))


def test_template_must_not_be_writable_by_others(lab):
    os.chmod(lab.root / "skel", 0o777)
    with pytest.raises(lm.LabError, match="not writable by other users"):
        lab.enable()
    assert not os.path.exists(lab.paths.conf)


def test_enable_refuses_someone_elses_account(lab):
    lab.fake.accounts["lab"] = lm.Account("lab", UID, GID, str(lab.root / "home/lab"), "Lab Tech", ["lab"])
    with pytest.raises(lm.LabError, match="already exists"):
        lab.enable()
    assert not os.path.exists(lab.paths.conf) and not lab.fake.commands("usermod")


def test_enable_refuses_a_second_lab_account(lab):
    enabled(lab)
    with pytest.raises(lm.LabError, match="already on for account 'lab'"):
        lab.enable("lab2")


@pytest.mark.parametrize("name", ["Lab", "lab user", "../etc", "-lab", ""])
def test_enable_rejects_bad_names(lab, name):
    with pytest.raises(lm.LabError, match="not a valid account name"):
        lab.enable(name)


def test_boot_grants_passwordless_sign_in_only_with_the_wipe_hooks(lab):
    enabled(lab)
    assert lab.hook("boot", None) == 0
    assert ["usermod", "--append", "--groups", "nopasswdlogin", "lab"] in lab.fake.calls
    assert lab.status()["sign_in_ready"] is True

    os.unlink(lab.paths.lightdm)                       # someone removed the LightDM hooks
    assert lab.hook("boot", None) == 0
    assert ["gpasswd", "--delete", "lab", "nopasswdlogin"] in lab.fake.calls
    assert lab.status()["sign_in_ready"] is False
    assert any("can't sign in" in line for line in lab.fake.logs)


def test_later_boots_start_no_programs_with_nothing_to_do(lab):
    """At boot nothing of the lab account runs and passwordless sign-in was
    granted at an earlier boot: no systemctl, groupadd or usermod to load
    from a cold disk, but the wipe itself still happens, and is timed."""
    home = enabled(lab)
    assert lab.hook("boot", None) == 0                  # the first boot grants passwordless sign-in
    (home / "left-behind.txt").write_text("a student's file")
    lab.fake.calls.clear()
    assert lab.hook("boot", None) == 0                  # a later boot
    names = [c[0] for c in lab.fake.calls]
    assert not {"systemctl", "groupadd", "usermod"} & set(names)
    assert "find" in names and not (home / "left-behind.txt").exists()
    assert lab.status()["sign_in_ready"] is True
    assert any(line.startswith("reset lab account 'lab' (boot) in ") and "stop " in line and "home " in line
               for line in lab.fake.logs)


def test_the_lab_hook_loads_exam_mode_only_during_an_exam(tmp_path, monkeypatch):
    import primers_lab
    from core import exam_mode
    assert primers_lab.EXAM_CONF == exam_mode.ExamPaths().conf

    class Lab:
        def is_lab_session(self, user=None):
            return True
    refreshed = []

    class Exam:
        def __init__(self, lab):
            pass

        def refresh(self):
            refreshed.append(1)
    monkeypatch.setattr(exam_mode, "ExamMode", Exam)
    monkeypatch.setattr(primers_lab, "EXAM_CONF", str(tmp_path / "exam.conf"))
    assert primers_lab.exam_hook(Lab(), "boot", None) == 0 and refreshed == []     # no exam
    (tmp_path / "exam.conf").write_text("URL=https://cbt.example\n")
    assert primers_lab.exam_hook(Lab(), "boot", None) == 0 and refreshed == [1]    # an exam: locks refreshed


def test_failed_boot_reset_revokes_passwordless_sign_in(lab):
    enabled(lab)
    lab.hook("boot", None)
    lab.fake.calls.clear()
    os.chmod(lab.root / "skel", 0o777)                 # template no longer trusted: reset fails
    assert lab.hook("boot", None) == 1
    assert ["gpasswd", "--delete", "lab", "nopasswdlogin"] in lab.fake.calls
    assert lab.status()["sign_in_ready"] is False


def test_hooks_ignore_everyone_but_the_lab_account(lab):
    enabled(lab)
    assert lab.hook("session-setup", "alice") == 0
    assert lab.hook("session-cleanup", None) == 0
    assert lab.fake.calls == []


def test_hooks_reset_the_lab_account(lab):
    home = enabled(lab)
    for event in lm.HOOK_EVENTS:
        (home / "left-behind").write_text("x")
        assert lab.hook(event, "lab") == 0
        assert not (home / "left-behind").exists()
        assert f"({event})" in open(os.path.join(lab.paths.state, "last-reset")).read()


def test_hooks_fail_closed_when_the_account_is_unsafe(lab):
    enabled(lab)
    lab.fake.accounts["lab"].groups.append("sudo")
    assert lab.hook("session-setup", "lab") == 1      # LightDM refuses the session
    assert lab.hook("boot", None) == 1
    assert lab.hook("session-cleanup", "lab") == 0    # nothing to refuse after logout
    assert any("not reset" in line for line in lab.fake.logs)


def test_damaged_config_blocks_only_the_lab_account(lab):
    enabled(lab)
    with open(lab.paths.conf, "w") as f:
        f.write("LAB_USER=lab\n")
    lab.fake.accounts["alice"] = lm.Account("alice", UID, GID, "/home/alice", "Alice", ["alice"])
    assert lab.hook("session-setup", "lab") == 1
    assert lab.hook("session-setup", "alice") == 0
    assert lab.status()["enabled"] is None


def test_hooks_do_nothing_when_lab_mode_is_off(lab):
    assert lab.hook("session-setup", "lab") == 0
    assert lab.hook("boot", None) == 0
    assert lab.fake.calls == []


def test_disable_deletes_the_account_and_hooks(lab):
    home = enabled(lab)
    (home / "file").write_text("x")
    assert lab.disable() == []
    assert ["userdel", "lab"] in lab.fake.calls
    assert ["systemctl", "disable", lm.UNIT] in lab.fake.calls
    assert not home.exists()
    assert not os.path.exists(lab.paths.conf) and not os.path.exists(lab.paths.lightdm)
    assert lab.status() == {"enabled": False}
    with pytest.raises(lm.LabError, match="already off"):
        lab.disable()


def test_disable_never_deletes_an_account_that_changed(lab):
    home = enabled(lab)
    (home / "file").write_text("keep")
    lab.fake.accounts["lab"].groups.append("sudo")
    warnings = lab.disable()
    assert warnings and "left account 'lab' in place" in warnings[0]
    assert ["gpasswd", "--delete", "lab", "nopasswdlogin"] in lab.fake.calls
    assert not lab.fake.commands("userdel") and (home / "file").read_text() == "keep"


def test_status_and_lab_session(lab):
    assert lab.status() == {"enabled": False}
    assert not lab.is_lab_session("lab")
    enabled(lab)
    st = lab.status()
    assert st["enabled"] and st["user"] == "lab" and st["account_exists"] and st["login_hooks"]
    assert st["last_reset"].endswith("(enabled)")
    assert lab.is_lab_session("lab") and not lab.is_lab_session("alice")


@pytest.mark.parametrize("text, private", [
    ("[connection]\npermissions=user:lab:;\n", True),
    ("[connection]\npermissions=user:lab;\n", True),
    ("[connection]\npermissions=user:lab:;user:bob:;\n", False),
    ("[connection]\npermissions=\n", False),
    ("[connection]\nid=x\n", False),
    ("[wifi]\npermissions=user:lab:;\n", False),
    ("[connection]\npermissions=user:labx:;\n", False),
])
def test_connection_only_for(text, private):
    assert lm._connection_only_for(text, "lab") is private


def test_config_round_trip_and_damage(tmp_path):
    path = str(tmp_path / "lab.conf")
    assert lm.read_config(path) is None
    lm.write_config(path, lm.LabConfig("lab", 1001, "/etc/skel"))
    assert lm.read_config(path) == lm.LabConfig("lab", 1001, "/etc/skel")
    with open(path, "w") as f:
        f.write("LAB_USER=../../etc\nLAB_UID=1001\n")
    with pytest.raises(lm.LabError):
        lm.read_config(path)


# ------------------------------------------------------------------ #
#  CLI and Brain
# ------------------------------------------------------------------ #

def test_cli_status_when_off(capsys, monkeypatch):
    import primers_lab
    monkeypatch.setattr(lm.LabMode, "status", lambda self: {"enabled": False})
    assert primers_lab.main(["status"]) == 0
    assert "Lab Mode: off" in capsys.readouterr().out


@pytest.mark.skipif(os.geteuid() == 0, reason="needs an unprivileged user")
def test_cli_changes_need_root():
    import primers_lab
    with pytest.raises(SystemExit) as e:
        primers_lab.main(["enable"])
    assert "sudo" in str(e.value)


def test_brain_lab_command(shell, capsys, monkeypatch):
    monkeypatch.setattr(lm.LabMode, "status", lambda self: {"enabled": False})
    shell.execute("lab")
    assert "Lab Mode is off" in capsys.readouterr().out

    monkeypatch.setattr(lm.LabMode, "status", lambda self: {
        "enabled": True, "user": "lab", "template": "/etc/skel", "last_reset": "today (boot)",
        "account_exists": True, "login_hooks": True})
    monkeypatch.setattr(lm.LabMode, "is_lab_session", lambda self, user=None: True)
    shell.execute("will my files be deleted?")
    out = capsys.readouterr().out
    assert "shared lab account" in out and "deleted when you sign out" in out


def test_interpreter_understands_lab_questions():
    from ai.command_interpreter.interpreter import CommandInterpreter
    ci = CommandInterpreter()
    for text in ("lab", "lab mode", "is this a lab computer?", "will my files be deleted?"):
        assert ci.parse(text).action == "lab", text
