"""Exam Mode across power cuts and reboots (ADR 0004): the durable exam log,
the order exam.conf and the locks are written and removed in, and the boot
menu lock."""

import json
import os
import subprocess
from datetime import datetime, timezone

import pytest

from core import exam_log as el
from core import exam_mode as em
from test_exam_mode import exam  # noqa: F401  (fixture)
from test_lab_mode import enabled, lab  # noqa: F401  (fixtures)

LINUX_10 = r"""#!/bin/sh
cat <<'EOF'
function gfxmode {
	set gfxpayload="${1}"
	if [ "${1}" = "keep" ]; then
		set vt_handoff=vt.handoff=7
	else
		set vt_handoff=
	fi
}
if [ "${recordfail}" != 1 ]; then
  set linux_gfx_mode=keep
else
  set linux_gfx_mode=text
fi
export linux_gfx_mode
menuentry 'PRIMERS OS GNU/Linux' --class primers --class gnu-linux --class gnu --class os $menuentry_id_option 'gnulinux-simple-1234' {
	recordfail
	load_video
	gfxmode $linux_gfx_mode
	if [ "${initrdfail}" = 1 ]; then echo 'initrd failed before'; fi
	insmod ext2
	search --no-floppy --fs-uuid --set=root 1234
	linux	/boot/vmlinuz-6.8.0-149-generic root=UUID=1234 ro  quiet splash $vt_handoff
	initrd	/boot/initrd.img-6.8.0-149-generic
}
menuentry 'PRIMERS OS GNU/Linux, with Linux 6.8.0-149-generic (recovery mode)' --class primers --class gnu-linux --class gnu --class os $menuentry_id_option 'gnulinux-6.8.0-149-generic-recovery-1234' {
	recordfail
	linux	/boot/vmlinuz-6.8.0-149-generic root=UUID=1234 ro recovery nomodeset
	initrd	/boot/initrd.img-6.8.0-149-generic
}
EOF
"""


def installed(exam, linux_10=LINUX_10):
    """Make the fixture look like an installed system with a boot menu."""
    r = os.path.dirname(exam.paths.grub_script)
    with open(os.path.join(r, "10_linux"), "w") as f:
        f.write(linux_10)
    os.chmod(os.path.join(r, "10_linux"), 0o755)
    os.makedirs(os.path.dirname(exam.paths.grub_cfg), exist_ok=True)
    assert exam.run(["update-grub"]).returncode == 0       # a normal grub.cfg first
    return exam


def grub_calls(exam):
    return [c for c in exam.lab.fake.calls if c[0] == "update-grub"]


# ---------------- durable log ----------------

def test_log_append_is_durable_and_survives_a_torn_line(tmp_path):
    log = el.ExamLog(str(tmp_path / "log/exam.jsonl"), str(tmp_path / "boot_id"))
    log.log("exam started: https://cbt.uni.edu.ng/", uid=0, user="root")
    # A power cut in the middle of the next write leaves half a line
    with open(log.path, "a") as f:
        f.write('{"time": "2026-11-25T09:00:01.000000Z", "mess')
    log.log("lab: exam session started (lab)", uid=1001, user="lab")
    records, damaged = log.records()
    assert [r.message for r in records] == ["exam started: https://cbt.uni.edu.ng/",
                                            "lab: exam session started (lab)"]
    assert damaged == 1
    assert oct(os.stat(log.path).st_mode & 0o777) == "0o640"


def test_exam_start_and_stop_are_in_the_durable_log(exam):
    exam.log = exam._log                       # the real logger, not the test list
    sent = []
    exam.syslog = sent.append
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/test")
    exam.stop()
    records, _ = exam.examlog.records()
    assert [r.message.split(":")[0] for r in records] == ["exam started", "exam stopped"]
    assert all(r.uid == os.getuid() and r.boot == "b0a7-1d" for r in records)
    assert sent == [r.message for r in records]              # the journal gets them too
    # After the exam, `primers-exam log` shows the exam that just ended
    assert "exam started: https://cbt.uni.edu.ng/test" in exam.journal()
    assert "exam stopped" in exam.journal()


def test_log_shows_the_current_exam_by_default(exam):
    log = exam.examlog
    log.append(el.Record("2026-11-20T09:00:00.000000Z", "exam started: https://old.uni.edu.ng/"))
    log.append(el.Record("2026-11-20T11:00:00.000000Z", "old exam page"))
    log.append(el.Record("2026-11-25T09:00:00.000000Z", "exam started: https://cbt.uni.edu.ng/"))
    log.append(el.Record("2026-11-25T09:05:00.000000Z", "blocked: https://google.com/", 1001, "lab"))
    shown = exam.journal()
    assert "blocked: https://google.com/" in shown and "old exam page" not in shown
    assert "old exam page" in exam.journal(everything=True)
    assert "old exam page" in exam.journal(since="2026-11-20")
    with pytest.raises(em.ExamError, match="can't read the time"):
        exam.journal(since="last tuesday")


def test_start_refuses_when_the_log_cant_be_written(exam):
    enabled(exam.lab)
    os.makedirs(os.path.dirname(exam.paths.log))
    os.makedirs(exam.paths.log)                 # a directory where the file should be
    with pytest.raises(em.ExamError, match="can't write the exam log"):
        exam.start("https://cbt.uni.edu.ng/test")
    assert exam.config() is None


def _entry(uid, message, cursor, usec=1764061200000000):
    return json.dumps({"_UID": str(uid), "MESSAGE": message, "__CURSOR": cursor, "_PID": "77",
                       "__REALTIME_TIMESTAMP": str(usec), "_BOOT_ID": "b0a7-1d"})


def test_writer_copies_the_candidates_entries_once(tmp_path):
    log = el.ExamLog(str(tmp_path / "exam.jsonl"), str(tmp_path / "boot_id"))
    users = {1001: "lab"}.get
    lines = [_entry(0, "exam started: https://cbt.uni.edu.ng/", "c1"),      # root: already logged
             _entry(1001, "blocked: https://google.com/", "c2"),
             "not json",
             _entry(1001, "blocked: https://google.com/", "c2"),            # seen again: skipped
             json.dumps({"_UID": "1001", "MESSAGE": [104, 105], "__CURSOR": "c3",
                         "__REALTIME_TIMESTAMP": "1764061201000000"})]       # bytes message
    seen = set()
    assert el.copy_entries(lines, log, seen, users) == 2
    records, _ = log.records()
    assert [(r.user, r.message, r.cursor) for r in records] == [
        ("lab", "blocked: https://google.com/", "c2"), ("lab", "hi", "c3")]
    assert records[0].time == "2025-11-25T09:00:00.000000Z"

    # Restarted (after a crash or a power cut): resumes a second before the
    # last copied entry, and doesn't copy it twice
    start, seen = el.follow_start(log, None)
    assert start == datetime(2025, 11, 25, 9, 0, 0, tzinfo=timezone.utc)
    assert seen == {"c2", "c3"}
    assert el.copy_entries([_entry(1001, "hi", "c3", 1764061201000000),
                            _entry(1001, "exam finished by the candidate (lab)", "c4", 1764061202000000)],
                           log, seen, users) == 1
    cmd = el.follow_command(start)
    assert cmd[:6] == ["journalctl", "--follow", "--output=json", "--no-pager", "--identifier", "primers-exam"]
    assert cmd[-1] == "2025-11-25 09:00:00 UTC"


def test_writer_starts_from_the_exam_start_when_nothing_was_copied(tmp_path):
    log = el.ExamLog(str(tmp_path / "exam.jsonl"))
    started = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)
    assert el.follow_start(log, started) == (started, set())


def test_run_writer_copies_until_journalctl_stops(tmp_path):
    log = el.ExamLog(str(tmp_path / "exam.jsonl"))

    class Proc:
        def __init__(self, argv, **kw):
            self.argv = argv
            self.stdout = iter([_entry(1001, "exam session started (lab)", "c9") + "\n"])

        def terminate(self):
            pass

        def wait(self):
            return 0

    assert el.run_writer(log, None, popen=Proc) == 1     # non-zero: systemd restarts it
    assert [r.message for r in log.records()[0]] == ["exam session started (lab)"]


# ---------------- power cut while an exam starts or stops ----------------

def test_power_cut_while_starting_comes_back_with_the_exam_on(exam, monkeypatch):
    enabled(exam.lab)
    real_lock = exam._lock

    def power_cut(*a):
        raise SystemExit("power cut")              # not an error the code handles
    monkeypatch.setattr(exam, "_lock", power_cut)
    with pytest.raises(SystemExit):
        exam.start("https://cbt.uni.edu.ng/test")
    assert exam.config() is not None                # exam.conf was written first
    # Boot: the Lab Mode boot service refreshes the exam and every lock is back
    monkeypatch.setattr(exam, "_lock", real_lock)
    assert exam.refresh() is True
    st = exam.status()
    assert st["firewall"] and st["usb_blocked"] and st["consoles_locked"]


def test_power_cut_while_stopping_leaves_an_exam_that_can_be_stopped(exam, monkeypatch):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/test")
    real = exam._remove_firewall

    def power_cut():
        raise SystemExit("power cut")
    monkeypatch.setattr(exam, "_remove_firewall", power_cut)
    with pytest.raises(SystemExit):
        exam.stop()
    assert exam.status()["active"] is True          # exam.conf goes last
    monkeypatch.setattr(exam, "_remove_firewall", real)
    assert exam.refresh() is True                   # boot: locked again
    exam.stop()
    assert exam.status() == {"active": False}
    assert not exam.firewall_active()


def test_atomic_write_fsyncs_file_and_directory(tmp_path, monkeypatch):
    from core import lab_mode as lm
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(os.readlink(f"/proc/self/fd/{fd}")), real(fd)))
    lm._atomic_write(str(tmp_path / "etc/exam.conf"), "URL=x\n")
    assert any(p.startswith(str(tmp_path / "etc/exam.conf.tmp")) for p in synced)
    assert str(tmp_path / "etc") in synced


# ---------------- boot menu ----------------

def test_grub_password_hash_format():
    h = em.grub_password_hash(b"secret", b"\x01" * 64)
    assert h.startswith("grub.pbkdf2.sha512.10000." + "01" * 64 + ".")
    assert len(h.rsplit(".", 1)[1]) == 128
    with pytest.raises(em.ExamError):
        em.grub_script_text("grub.pbkdf2.sha512.10000.XYZ\nset superusers=")


def test_boot_menu_is_locked_during_an_exam_on_an_installed_system(exam):
    installed(exam)
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/test")
    cfg = open(exam.paths.grub_cfg).read()
    head, rest = cfg.split("password_pbkdf2 primers-exam grub.pbkdf2.sha512.10000.", 1)
    assert 'set superusers="primers-exam"' in head
    entries = [line for line in cfg.splitlines() if line.startswith("menuentry ")]
    # The normal entry comes first and boots without the password; nothing else does
    assert entries[0].startswith("menuentry 'PRIMERS OS GNU/Linux' --unrestricted --class primers")
    assert all("--unrestricted" not in e for e in entries[1:])
    assert sum("--unrestricted" in e for e in entries) == 1
    # Its body came through whole (braces in ${...} don't end it early)
    block = cfg[cfg.index(entries[0]):].split("\n}\n", 1)[0]
    assert block.endswith("initrd\t/boot/initrd.img-6.8.0-149-generic")
    assert "recovery" not in block
    assert open(exam.paths.grub_default).read() == em.GRUB_DEFAULT_TEXT
    assert "GRUB_DISABLE_RECOVERY=true" in em.GRUB_DEFAULT_TEXT
    assert exam.status()["boot_menu"] == "locked"
    # The password is random: a second exam gets another one
    first_hash = rest.split()[0]
    exam.stop()
    exam.start("https://cbt.uni.edu.ng/test")
    assert first_hash not in open(exam.paths.grub_cfg).read()


def test_grub_cfg_passes_grub_script_check(exam):
    import shutil
    check = shutil.which("grub-script-check")
    if not check:
        pytest.skip("grub-script-check not installed")
    installed(exam)
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/test")
    r = subprocess.run([check, exam.paths.grub_cfg], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_refresh_doesnt_rerun_update_grub_when_the_lock_is_in_place(exam):
    installed(exam)
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/test")
    before = len(grub_calls(exam))
    exam.refresh()
    assert len(grub_calls(exam)) == before
    os.unlink(exam.paths.grub_script)               # lock removed behind our back
    exam.refresh()
    assert len(grub_calls(exam)) == before + 1
    assert exam.status()["boot_menu"] == "locked"


def test_stop_unlocks_the_boot_menu(exam):
    installed(exam)
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/test")
    exam.stop()
    cfg = open(exam.paths.grub_cfg).read()
    assert "superusers" not in cfg and "--unrestricted" not in cfg
    assert not os.path.exists(exam.paths.grub_script)
    assert not os.path.exists(exam.paths.grub_default)


def test_boot_menu_lock_failure_rolls_the_exam_back(exam):
    installed(exam)
    enabled(exam.lab)
    exam.net.grub_fails = True
    with pytest.raises(em.ExamError, match="lock the boot menu"):
        exam.start("https://cbt.uni.edu.ng/test")
    assert exam.config() is None
    assert not os.path.exists(exam.paths.grub_script)
    assert not exam.firewall_active()


def test_a_10_linux_the_lock_doesnt_understand_fails_loudly(exam):
    installed(exam, "#!/bin/sh\necho \"menuentry 'Odd' {\"\necho '}'\n")
    enabled(exam.lab)
    with pytest.raises(em.ExamError, match="lock the boot menu"):
        exam.start("https://cbt.uni.edu.ng/test")
    assert exam.config() is None


def test_live_session_boot_menu_is_left_alone(exam):
    installed(exam)
    with open(exam.paths.cmdline, "w") as f:
        f.write("BOOT_IMAGE=/casper/vmlinuz boot=casper quiet splash\n")
    enabled(exam.lab)
    before = len(grub_calls(exam))
    exam.start("https://cbt.uni.edu.ng/test")
    assert len(grub_calls(exam)) == before
    assert exam.status()["boot_menu"] == "live"
    assert not os.path.exists(exam.paths.grub_script)


def test_exam_log_writer_is_started_with_the_exam(exam):
    enabled(exam.lab)
    exam.start("https://cbt.uni.edu.ng/test")
    assert ["systemctl", "start", "primers-exam-log.service"] in exam.lab.fake.calls


def test_update_grub_gets_minutes_not_seconds(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen[argv[0]] = kw["timeout"]
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    em._default_run(["update-grub"])
    em._default_run(["nft", "list", "tables"])
    assert seen == {"update-grub": 600, "nft": 30}
