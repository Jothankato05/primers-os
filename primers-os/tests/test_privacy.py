"""Privacy: the notice (NDPA 2023), the logs' retention (90 days by default,
configurable), exporting the logs, and what the image ships."""

import csv
import hashlib
import io
import json
import os
import stat
import threading
from datetime import datetime, timedelta, timezone

import pytest

from core import exam_log, fleet, logfiles, privacy

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OVERLAYS = os.path.join(REPO, "primers-distro", "overlays")
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


def exam_line(when: datetime, message: str) -> str:
    return exam_log.Record(when.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), message, 0, "root", 1, "b").to_json() + "\n"


def fleet_line(when: datetime, event: str, **fields) -> str:
    return json.dumps({"time": when.isoformat(timespec="seconds"), "event": event, **fields}) + "\n"


# ---------------- settings ----------------

def test_defaults_are_90_days_and_no_institution(tmp_path):
    conf = privacy.PrivacyConfig.load(str(tmp_path / "missing.conf"))
    assert (conf.exam_log_days, conf.fleet_log_days, conf.controller) == (90, 90, "")


def test_settings_round_trip(tmp_path):
    path = str(tmp_path / "privacy.conf")
    privacy.PrivacyConfig("Veritas University", "dpo@veritas.example", "Dr A. B.", 30, 180).save(path)
    conf = privacy.PrivacyConfig.load(path)
    assert (conf.controller, conf.contact, conf.dpo, conf.exam_log_days, conf.fleet_log_days) == \
        ("Veritas University", "dpo@veritas.example", "Dr A. B.", 30, 180)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644


@pytest.mark.parametrize("value", ["0", "-3", "3651", "ninety", "1.5"])
def test_retention_days_must_be_sensible(tmp_path, value):
    path = tmp_path / "privacy.conf"
    path.write_text(f"[retention]\nexam_log_days = {value}\n")
    with pytest.raises(privacy.PrivacyError, match="days"):
        privacy.PrivacyConfig.load(str(path))


def test_the_image_ships_the_defaults():
    with open(os.path.join(OVERLAYS, "etc/primers/privacy.conf"), encoding="utf-8") as f:
        assert f.read() == privacy.PrivacyConfig().text()
    with open(os.path.join(OVERLAYS, "etc/systemd/journald.conf.d/90-primers-retention.conf"), encoding="utf-8") as f:
        assert f.read() == privacy.journald_dropin(90)
    with open(os.path.join(OVERLAYS, "etc/firefox/policies/policies.json"), encoding="utf-8") as f:
        policies = json.load(f)["policies"]
    assert policies["DisableTelemetry"] is True and policies["DisableFirefoxStudies"] is True
    with open(os.path.join(OVERLAYS, "etc/systemd/system/primers-privacy-retention.timer"), encoding="utf-8") as f:
        timer = f.read()
    assert "OnCalendar=daily" in timer and "Persistent=true" in timer


def test_the_desktop_shows_the_notice_at_sign_in_and_in_the_menu():
    with open(os.path.join(OVERLAYS, "etc/skel/.config/openbox/autostart"), encoding="utf-8") as f:
        assert "primers-privacy notice --first-run" in f.read()
    with open(os.path.join(OVERLAYS, "etc/skel/.config/openbox/menu.xml"), encoding="utf-8") as f:
        assert '<item label="Privacy notice"><action name="Execute"><command>primers-privacy notice</command>' in f.read()


# ---------------- the notice ----------------

def test_the_notice_covers_what_the_ndpa_asks_for():
    text = privacy.notice(privacy.PrivacyConfig("Veritas University", "privacy@veritas.example", "Dr A. B.", 60, 30))
    flat = " ".join(text.split())
    for must in ("Nigeria Data Protection Act 2023", "Veritas University", "privacy@veritas.example", "Dr A. B.",
                 "data controller", "Lawful basis", "Kept for 60 days", "Kept for 30 days", "at most 60 days",
                 "give you a copy", "correct it", "delete it", "object", "portable", "consented",
                 "Nigeria Data Protection Commission", "ndpc.gov.ng", "under 18", "WHO CAN SEE IT",
                 "not the answers you give", "Firefox's telemetry is turned off", privacy.NOTICE_VERSION):
        assert must in flat, must
    assert max(len(line) for line in text.splitlines()) <= 76


def test_the_notice_says_when_no_institution_is_set():
    flat = " ".join(privacy.notice(privacy.PrivacyConfig()).split())
    assert "Not set on this computer: ask the lab administrator." in flat


def test_the_short_notice_for_the_lab_account():
    text = privacy.short_notice(privacy.PrivacyConfig(exam_log_days=45))
    assert "45 days" in text and "System › Privacy notice" in text


def test_the_documentation_carries_the_notice_as_shipped():
    with open(os.path.join(REPO, "docs", "privacy.md"), encoding="utf-8") as f:
        doc = f.read()
    assert privacy.notice(privacy.PrivacyConfig()) in doc


def test_acknowledged_per_version(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert not privacy.acknowledged()
    privacy.acknowledge()
    assert privacy.acknowledged()
    assert stat.S_IMODE(os.stat(privacy.acknowledged_path()).st_mode) == 0o600
    monkeypatch.setattr(privacy, "NOTICE_VERSION", "2027-01-01")      # a new notice: shown again
    assert not privacy.acknowledged()


def test_live_session_detection(tmp_path):
    cmdline = tmp_path / "cmdline"
    cmdline.write_text("BOOT_IMAGE=/casper/vmlinuz boot=casper quiet splash\n")
    assert privacy.live_session(str(cmdline))
    cmdline.write_text("BOOT_IMAGE=/vmlinuz root=UUID=x ro quiet splash\n")
    assert not privacy.live_session(str(cmdline))


# ---------------- retention ----------------

def test_prune_removes_old_records_and_keeps_the_rest(tmp_path):
    path = tmp_path / "exam.jsonl"
    path.write_text(exam_line(NOW - timedelta(days=100), "exam started: old")
                    + '{"time": "2026-08-17T10:00:00.0000'          # torn by a power cut, with the old one
                    + "\n" + exam_line(NOW - timedelta(days=95), "visited old")
                    + exam_line(NOW - timedelta(days=10), "exam started: recent")
                    + '{"torn\n'                                    # goes with the recent one
                    + exam_line(NOW - timedelta(days=1), "visited recent"))
    os.chmod(path, 0o640)
    kept, removed = logfiles.prune(str(path), NOW - timedelta(days=90))
    assert (kept, removed) == (3, 3)
    records, damaged = exam_log.ExamLog(str(path)).records()
    assert [r.message for r in records] == ["exam started: recent", "visited recent"] and damaged == 1
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o640
    assert not os.path.exists(f"{path}.prune")


def test_prune_leaves_the_file_alone_when_nothing_is_old(tmp_path):
    path = tmp_path / "exam.jsonl"
    path.write_text(exam_line(NOW - timedelta(days=1), "visited"))
    inode = os.stat(path).st_ino
    assert logfiles.prune(str(path), NOW - timedelta(days=90)) == (1, 0)
    assert os.stat(path).st_ino == inode
    assert logfiles.prune(str(tmp_path / "missing.jsonl"), NOW) == (0, 0)


def test_prune_refuses_a_symlink(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_text(exam_line(NOW - timedelta(days=200), "x"))
    os.symlink(target, tmp_path / "exam.jsonl")
    with pytest.raises(OSError):
        logfiles.prune(str(tmp_path / "exam.jsonl"), NOW)
    assert target.read_text().count("\n") == 1


def test_no_record_is_lost_while_the_log_is_pruned(tmp_path):
    log = exam_log.ExamLog(str(tmp_path / "exam.jsonl"), boot_id_path=str(tmp_path / "none"))
    with open(log.path, "w") as f:
        for i in range(300):
            f.write(exam_line(NOW - timedelta(days=200), f"old {i}"))
    stop = threading.Event()

    def prune_forever():
        while not stop.is_set():
            logfiles.prune(log.path, datetime.now(timezone.utc) - timedelta(days=90))

    t = threading.Thread(target=prune_forever)
    t.start()
    try:
        for i in range(200):
            log.log(f"new {i}")
    finally:
        stop.set()
        t.join()
    logfiles.prune(log.path, datetime.now(timezone.utc) - timedelta(days=90))
    records, damaged = log.records()
    assert [r.message for r in records] == [f"new {i}" for i in range(200)] and damaged == 0


def test_fleet_log_entries_are_pruned_by_their_own_days(tmp_path):
    exam, fl = tmp_path / "exam.jsonl", tmp_path / "fleet.jsonl"
    exam.write_text(exam_line(NOW - timedelta(days=40), "visited"))
    fl.write_text(fleet_line(NOW - timedelta(days=40), "command", command="status")
                  + fleet_line(NOW - timedelta(days=5), "command", command="exam-stop"))
    conf = privacy.PrivacyConfig(exam_log_days=90, fleet_log_days=30)
    done = privacy.apply_retention(conf, NOW, str(exam), str(fl), str(tmp_path / "no-exam.conf"))
    assert done["exam"] == {"kept": 1, "removed": 0, "days": 90}
    assert done["fleet"] == {"kept": 1, "removed": 1, "days": 30}
    assert "exam-stop" in fl.read_text() and "status" not in fl.read_text()


def test_the_exam_log_is_left_alone_while_an_exam_is_running(tmp_path):
    exam, fl, conf_file = tmp_path / "exam.jsonl", tmp_path / "fleet.jsonl", tmp_path / "exam.conf"
    exam.write_text(exam_line(NOW - timedelta(days=200), "exam started: a long one"))
    fl.write_text(fleet_line(NOW - timedelta(days=200), "command"))
    conf_file.write_text("URL=https://cbt.example\n")
    done = privacy.apply_retention(privacy.PrivacyConfig(), NOW, str(exam), str(fl), str(conf_file))
    assert "skipped" in done["exam"] and "a long one" in exam.read_text()
    assert done["fleet"]["removed"] == 1


def test_appends_from_fleet_and_exam_log_use_the_lock(tmp_path):
    paths = fleet.FleetPaths(root=str(tmp_path / "fleet"), log=str(tmp_path / "fleet.jsonl"))
    fleet.log_event(paths, "command", command="ping")
    assert os.path.exists(str(tmp_path / "fleet.jsonl.lock"))
    exam_log.ExamLog(str(tmp_path / "exam.jsonl"), boot_id_path=str(tmp_path / "none")).log("hello")
    assert os.path.exists(str(tmp_path / "exam.jsonl.lock"))


def test_times_in_both_logs_formats():
    assert logfiles.parse_time("2026-11-25T09:30:00.123456Z") == datetime(2026, 11, 25, 9, 30, 0, 123456,
                                                                          tzinfo=timezone.utc)
    assert logfiles.parse_time("2026-11-25T10:30:00+01:00") == datetime(2026, 11, 25, 9, 30, tzinfo=timezone.utc)
    assert logfiles.parse_time("garbage") is None and logfiles.parse_time("") is None


def test_the_journal_follows_the_exam_log(tmp_path):
    path = str(tmp_path / "journald.conf.d" / "90-primers-retention.conf")
    assert privacy.write_journald(30, path) is True
    assert privacy.write_journald(30, path) is False                    # unchanged: no journald restart
    assert privacy.journald_days(path) == 30
    assert "MaxRetentionSec=30day" in open(path).read()


# ---------------- export ----------------

def test_export_writes_jsonl_csv_and_checksums(tmp_path):
    exam, fl = tmp_path / "exam.jsonl", tmp_path / "fleet.jsonl"
    exam.write_text(exam_line(NOW - timedelta(days=3), "exam started: https://cbt.example")
                    + "{torn\n" + exam_line(NOW - timedelta(days=2), "=HYPERLINK(\"http://x\")"))
    fl.write_text(fleet_line(NOW - timedelta(days=2), "command", command="exam-start", peer="10.0.0.5"))
    dest = tmp_path / "out"
    files = privacy.export(str(dest), privacy.PrivacyConfig(), None, exam_log_path=str(exam), fleet_log_path=str(fl))
    names = sorted(os.path.basename(f) for f in files)
    assert names == ["README.txt", "SHA256SUMS", "exam.csv", "exam.jsonl", "fleet.csv", "fleet.jsonl"]
    assert stat.S_IMODE(os.stat(dest).st_mode) == 0o700
    assert all(stat.S_IMODE(os.stat(f).st_mode) == 0o600 for f in files)
    for line in (dest / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((dest / name).read_bytes()).hexdigest() == digest
    rows = list(csv.reader(io.StringIO((dest / "exam.csv").read_text())))
    assert rows[0] == ["time", "user", "uid", "pid", "boot", "message"] and len(rows) == 3
    assert rows[2][5].startswith("'=")                                  # not run as a formula
    fleet_rows = list(csv.reader(io.StringIO((dest / "fleet.csv").read_text())))
    assert fleet_rows[0][:2] == ["time", "event"] and "peer" in fleet_rows[0]
    readme = (dest / "README.txt").read_text()
    assert "2 records" in readme and "personal data" in readme


def test_export_since_and_exam_only(tmp_path):
    exam = tmp_path / "exam.jsonl"
    exam.write_text(exam_line(NOW - timedelta(days=30), "old exam") + exam_line(NOW - timedelta(days=1), "new exam"))
    dest = tmp_path / "out"
    privacy.export(str(dest), privacy.PrivacyConfig(), NOW - timedelta(days=7), ("exam",),
                   exam_log_path=str(exam), fleet_log_path=str(tmp_path / "none"))
    assert sorted(os.listdir(dest)) == ["README.txt", "SHA256SUMS", "exam.csv", "exam.jsonl"]
    assert "new exam" in (dest / "exam.jsonl").read_text() and "old exam" not in (dest / "exam.jsonl").read_text()


def test_export_never_writes_into_an_existing_folder(tmp_path):
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "something").write_text("x")
    with pytest.raises(privacy.PrivacyError, match="already exists"):
        privacy.export(str(dest), privacy.PrivacyConfig(), exam_log_path=str(tmp_path / "e"),
                       fleet_log_path=str(tmp_path / "f"))
    os.symlink(tmp_path, tmp_path / "link")
    with pytest.raises(privacy.PrivacyError, match="already exists"):
        privacy.export(str(tmp_path / "link"), privacy.PrivacyConfig(), exam_log_path=str(tmp_path / "e"),
                       fleet_log_path=str(tmp_path / "f"))


# ---------------- the commands ----------------

@pytest.fixture
def cli(tmp_path, monkeypatch):
    import primers_privacy
    monkeypatch.setattr(privacy, "CONF_PATH", str(tmp_path / "privacy.conf"))
    monkeypatch.setattr(privacy, "EXAM_LOG", str(tmp_path / "exam.jsonl"))
    monkeypatch.setattr(privacy, "FLEET_LOG", str(tmp_path / "fleet.jsonl"))
    monkeypatch.setattr(privacy, "EXAM_CONF", str(tmp_path / "exam.conf"))
    monkeypatch.setattr(privacy, "JOURNALD_DROPIN", str(tmp_path / "journald.conf"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    restarts = []
    monkeypatch.setattr(primers_privacy, "_restart_journald", lambda: restarts.append(1))
    monkeypatch.setattr(primers_privacy.os, "geteuid", lambda: 0)
    primers_privacy.restarts = restarts
    return primers_privacy


def fake_zenity(tmp_path, monkeypatch, rc):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    z = bindir / "zenity"
    z.write_text(f"#!/bin/sh\necho \"$@\" > {tmp_path}/zenity.args\nexit {rc}\n")
    z.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("DISPLAY", ":99")


def test_first_sign_in_shows_the_notice_until_it_is_confirmed(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(privacy, "live_session", lambda cmdline="": False)
    fake_zenity(tmp_path, monkeypatch, 1)                               # "Later"
    assert cli.main(["notice", "--first-run"]) == 0
    assert "--checkbox=I have read this privacy notice" in (tmp_path / "zenity.args").read_text()
    assert not privacy.acknowledged()
    fake_zenity(tmp_path, monkeypatch, 0)                               # ticked and OK
    cli.main(["notice", "--first-run"])
    assert privacy.acknowledged()
    os.unlink(tmp_path / "zenity.args")
    cli.main(["notice", "--first-run"])                                 # not shown again
    assert not (tmp_path / "zenity.args").exists()


def test_first_sign_in_skips_the_live_usb_and_no_desktop(cli, tmp_path, monkeypatch):
    fake_zenity(tmp_path, monkeypatch, 0)
    monkeypatch.setattr(privacy, "live_session", lambda cmdline="": True)
    cli.main(["notice", "--first-run"])
    assert not (tmp_path / "zenity.args").exists() and not privacy.acknowledged()
    monkeypatch.setattr(privacy, "live_session", lambda cmdline="": False)
    monkeypatch.delenv("DISPLAY")
    cli.main(["notice", "--first-run"])
    assert not privacy.acknowledged()


def test_notice_from_the_menu_and_as_text(cli, tmp_path, monkeypatch, capsys):
    fake_zenity(tmp_path, monkeypatch, 0)
    assert cli.main(["notice"]) == 0
    args = (tmp_path / "zenity.args").read_text()
    assert "--text-info" in args and "--checkbox" not in args
    assert cli.main(["notice", "--text"]) == 0
    assert "PRIMERS OS PRIVACY NOTICE" in capsys.readouterr().out


def test_retention_and_controller_commands(cli, tmp_path, capsys):
    (tmp_path / "exam.jsonl").write_text(exam_line(datetime.now(timezone.utc) - timedelta(days=40), "old")
                                         + exam_line(datetime.now(timezone.utc), "new"))
    assert cli.main(["retention", "--days", "30"]) == 0
    assert "30 days" in capsys.readouterr().out
    assert privacy.PrivacyConfig.load(privacy.CONF_PATH).exam_log_days == 30
    assert privacy.journald_days(privacy.JOURNALD_DROPIN) == 30 and cli.restarts == [1]
    assert "old" not in (tmp_path / "exam.jsonl").read_text()
    assert cli.main(["retention", "--days", "5000"]) == 1
    assert cli.main(["controller", "--name", "Veritas University", "--contact", "dpo@veritas.example"]) == 0
    assert cli.main(["status", "--json"]) == 0
    st = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert st["controller"] == "Veritas University" and st["exam_log_days"] == 30 and st["journal_days"] == 30
    assert st["exam_log"]["records"] == 1
    assert cli.main(["prune"]) == 0 and cli.restarts == [1]              # the journal limit was already right


def test_commands_that_change_things_need_root(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)
    for argv in (["retention", "--days", "30"], ["prune"], ["export", "/tmp/x"],
                 ["controller", "--name", "a", "--contact", "b"]):
        assert cli.main(argv) == 1
    assert "sudo" in capsys.readouterr().err


def test_export_command_gives_the_files_to_whoever_ran_sudo(cli, tmp_path, monkeypatch, capsys):
    (tmp_path / "exam.jsonl").write_text(exam_line(NOW, "exam started"))
    owned = []
    monkeypatch.setattr(privacy.os, "chown", lambda path, uid, gid: owned.append((path, uid, gid)))
    monkeypatch.setenv("SUDO_UID", "1000")
    monkeypatch.setenv("SUDO_GID", "1000")
    assert cli.main(["export", str(tmp_path / "out"), "--exam-only"]) == 0
    assert "sha256sum -c SHA256SUMS" in capsys.readouterr().out
    assert len(owned) == 5 and all(o[1:] == (1000, 1000) for o in owned)
    assert cli.main(["export", str(tmp_path / "out2"), "--since", "yesterday-ish"]) == 1


def test_exam_log_export(tmp_path, monkeypatch, capsys):
    import primers_exam
    from core import exam_mode
    log = exam_log.ExamLog(str(tmp_path / "exam.jsonl"), boot_id_path=str(tmp_path / "none"))
    with open(log.path, "w") as f:
        f.write(exam_line(NOW - timedelta(days=3), "exam started: https://old.example")
                + exam_line(NOW - timedelta(days=1), "exam started: https://cbt.example")
                + exam_line(NOW - timedelta(hours=20), "visited https://cbt.example/q1"))

    class Exam:
        examlog = log
    monkeypatch.setattr(exam_mode, "ExamMode", lambda *a, **k: Exam())
    monkeypatch.setattr(primers_exam.os, "geteuid", lambda: 0)
    monkeypatch.setattr(privacy, "CONF_PATH", str(tmp_path / "privacy.conf"))
    assert primers_exam.main(["log", "--export", str(tmp_path / "last")]) == 0
    text = (tmp_path / "last" / "exam.jsonl").read_text()
    assert "cbt.example/q1" in text and "old.example" not in text            # the last exam, as 'log' shows
    assert primers_exam.main(["log", "--all", "--export", str(tmp_path / "all")]) == 0
    assert "old.example" in (tmp_path / "all" / "exam.jsonl").read_text()


def test_lab_notice_carries_the_short_privacy_notice():
    import primers_lab
    assert "exam log" in primers_lab._privacy_layer() and "Privacy notice" in primers_lab._privacy_layer()


def test_brain_privacy_command(capsys):
    from ai.command_interpreter.interpreter import CommandInterpreter
    ci = CommandInterpreter()
    for phrase in ("privacy", "privacy notice", "what does this pc record about me?"):
        assert ci.parse(phrase).action == "privacy", phrase
