"""
primers-privacy — the privacy notice, how long logs are kept, and exporting
them (installed as /usr/bin/primers-privacy).

  primers-privacy notice                 show the privacy notice (a window on the desktop)
  primers-privacy status [--json]        what is kept, for how long, and who is responsible
  sudo primers-privacy retention [--days N] [--fleet-days N]
                                         show or change how long the logs are kept (default 90 days)
  sudo primers-privacy controller --name NAME --contact CONTACT [--dpo DPO]
                                         the institution responsible, shown in the notice
  sudo primers-privacy export DIR [--since TIME] [--exam-only]
                                         copy the logs (JSON lines and CSV, with SHA256SUMS)
  sudo primers-privacy prune             remove records older than the retention time (daily timer)

Settings: /etc/primers/privacy.conf. See /usr/share/doc/primers/privacy.md.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import exam_log, privacy  # noqa: E402

TITLE = "PRIMERS OS privacy notice"


def _need_root() -> None:
    if os.geteuid() != 0:
        raise privacy.PrivacyError("this needs administrator rights: run it with sudo")


def _desktop() -> bool:
    return bool(os.environ.get("DISPLAY") and shutil.which("zenity"))


def _show(text: str, first_run: bool) -> int:
    """The notice in a window when there is a desktop, else on the terminal.
    zenity's exit code: 0 when the person ticked "I have read" and pressed
    OK (first run), 1 for "Later" or closing the window."""
    if not _desktop():
        print(text)
        return 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="primers-privacy-", suffix=".txt") as f:
        f.write(text)
        f.flush()
        cmd = ["zenity", "--text-info", f"--title={TITLE}", f"--filename={f.name}", "--width=700",
               "--height=560", "--font=Monospace 10"]
        if first_run:
            cmd += ["--checkbox=I have read this privacy notice", "--ok-label=OK", "--cancel-label=Later"]
        else:
            cmd += ["--ok-label=OK", "--cancel-label=Close"]
        return subprocess.run(cmd, check=False).returncode


def _owner():
    """Export files belong to the person who ran sudo, so they can copy them."""
    try:
        return int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"])
    except (KeyError, ValueError):
        return None


def _restart_journald() -> None:
    subprocess.run(["systemctl", "restart", "systemd-journald.service"], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _print_status(st: dict) -> None:
    print(f"Privacy notice version {st['notice_version']}")
    print(f"Responsible institution: {st['controller'] or 'not set (sudo primers-privacy controller)'}")
    if st["contact"]:
        print(f"Contact: {st['contact']}")
    if st["dpo"]:
        print(f"Data protection officer: {st['dpo']}")
    print(f"Exam log: kept {st['exam_log_days']} days; {st['exam_log']['records']} records"
          + (f", oldest {st['exam_log']['oldest']}" if st['exam_log']['oldest'] else ""))
    print(f"Lab control log: kept {st['fleet_log_days']} days; {st['fleet_log']['records']} records"
          + (f", oldest {st['fleet_log']['oldest']}" if st['fleet_log']['oldest'] else ""))
    print("System journal: " + (f"kept at most {st['journal_days']} days" if st["journal_days"]
                                 else "no limit set by PRIMERS OS"))


def _apply(conf):
    return privacy.apply_retention(conf, exam_log_path=privacy.EXAM_LOG, fleet_log_path=privacy.FLEET_LOG,
                                   exam_conf=privacy.EXAM_CONF)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="primers-privacy", description="The privacy notice and the logs' retention.")
    sub = p.add_subparsers(dest="command", required=True)
    nt = sub.add_parser("notice", help="show the privacy notice")
    nt.add_argument("--first-run", action="store_true", help=argparse.SUPPRESS)   # desktop autostart
    nt.add_argument("--text", action="store_true", help="print it, even on the desktop")
    nt.add_argument("--short", action="store_true", help=argparse.SUPPRESS)       # the lab notice's layer
    st = sub.add_parser("status", help="what is kept and for how long")
    st.add_argument("--json", action="store_true")
    rt = sub.add_parser("retention", help="show or change how long the logs are kept")
    rt.add_argument("--days", help="days the exam log keeps records (also the journal's limit)")
    rt.add_argument("--fleet-days", help="days the lab control log keeps records")
    ct = sub.add_parser("controller", help="the institution responsible for this PC's data")
    ct.add_argument("--name", required=True)
    ct.add_argument("--contact", required=True, help="an email address, phone number or office")
    ct.add_argument("--dpo", default="", help="the data protection officer")
    ex = sub.add_parser("export", help="copy the logs for a request or an audit")
    ex.add_argument("dest", help="a new folder")
    ex.add_argument("--since", help="only records from this time (UTC), e.g. 2026-11-24")
    ex.add_argument("--exam-only", action="store_true", help="only the exam log")
    sub.add_parser("prune", help="remove records older than the retention time")
    args = p.parse_args(argv)

    try:
        conf = privacy.PrivacyConfig.load(privacy.CONF_PATH)
        if args.command == "notice":
            if args.short:
                print(privacy.short_notice(conf))
                return 0
            if args.first_run:
                from core import lab_mode
                if privacy.acknowledged() or privacy.live_session() or not _desktop() \
                        or lab_mode.LabMode().is_lab_session():
                    return 0          # seen; the live USB; no desktop; the lab account (its notice has the short one)
                if _show(privacy.notice(conf), first_run=True) == 0:
                    privacy.acknowledge()
                return 0
            if args.text:
                print(privacy.notice(conf))
                return 0
            _show(privacy.notice(conf), first_run=False)
            return 0
        if args.command == "status":
            s = privacy.status(conf, privacy.EXAM_LOG, privacy.FLEET_LOG, privacy.JOURNALD_DROPIN)
            if args.json:
                print(json.dumps(s, indent=2, sort_keys=True))
            else:
                _print_status(s)
            return 0
        if args.command == "retention":
            if args.days is None and args.fleet_days is None:
                print(f"The exam log keeps records for {conf.exam_log_days} days, the lab control log "
                      f"for {conf.fleet_log_days} days.")
                return 0
            _need_root()
            if args.days is not None:
                conf.exam_log_days = privacy._days(args.days, "--days")
            if args.fleet_days is not None:
                conf.fleet_log_days = privacy._days(args.fleet_days, "--fleet-days")
            conf.save(privacy.CONF_PATH)
            if privacy.write_journald(conf.exam_log_days, privacy.JOURNALD_DROPIN):
                _restart_journald()
            done = _apply(conf)
            print(f"The exam log now keeps records for {conf.exam_log_days} days, the lab control log "
                  f"for {conf.fleet_log_days} days (the journal: {conf.exam_log_days} days).")
            if "skipped" in done["exam"]:
                print("An exam is running: older exam records are removed after it ends.")
            return 0
        if args.command == "controller":
            _need_root()
            conf.controller, conf.contact, conf.dpo = (privacy._clean(args.name), privacy._clean(args.contact),
                                                       privacy._clean(args.dpo))
            if not conf.controller or not conf.contact:
                raise privacy.PrivacyError("the name and the contact can't be empty")
            conf.save(privacy.CONF_PATH)
            print(f"The privacy notice now names {conf.controller} ({conf.contact}).")
            return 0
        if args.command == "export":
            _need_root()
            since = None
            if args.since:
                since = exam_log.parse_time(args.since)
                if since is None:
                    raise privacy.PrivacyError(f"can't read the time {args.since!r} (e.g. 2026-11-24 09:00)")
            which = ("exam",) if args.exam_only else ("exam", "fleet")
            files = privacy.export(args.dest, conf, since, which, exam_log_path=privacy.EXAM_LOG,
                                   fleet_log_path=privacy.FLEET_LOG, owner=_owner())
            print(f"Exported to {args.dest}: " + ", ".join(os.path.basename(f) for f in files))
            print(f"Check them with: (cd {args.dest} && sha256sum -c SHA256SUMS)")
            print("These files are personal data: keep them safe and delete them when no longer needed.")
            return 0
        if args.command == "prune":
            _need_root()
            if privacy.write_journald(conf.exam_log_days, privacy.JOURNALD_DROPIN):
                _restart_journald()
            done = _apply(conf)
            for name, r in done.items():
                if "skipped" in r:
                    print(f"{name} log: kept as it is ({r['skipped']})")
                else:
                    print(f"{name} log: {r['removed']} old lines removed, {r['kept']} kept ({r['days']} days)")
            return 0
    except (privacy.PrivacyError, OSError) as e:
        print(f"primers-privacy: {e}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
