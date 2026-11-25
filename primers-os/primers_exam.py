"""
primers-exam — Exam Mode for computer-based tests (installed as /usr/bin/primers-exam).

       primers-exam probe URL                     which servers does the exam site need?
  sudo primers-exam start URL [--allow HOST[:PORT]]...   start an exam on this PC
  sudo primers-exam stop                          end it
       primers-exam status                        is an exam running?
  sudo primers-exam log [--since TIME | --all]    what happened during the exam

Needs Lab Mode. While an exam runs, signing in to the shared lab account
opens only the exam site, full screen, and that account can reach only the
exam server(s). USB drives are blocked and activity is logged. Use --allow
for any other server the exam site loads from (e.g. a CDN or login server).

An exam survives a power cut or a restart: the PC comes back with the exam
on, and the log (/var/log/primers/exam.jsonl) keeps everything up to the cut.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import exam_log, exam_mode, exam_probe  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="primers-exam",
                                description="Exam Mode: lock the lab account to an exam site.")
    sub = p.add_subparsers(dest="command", required=True)
    st = sub.add_parser("start", help="start an exam")
    st.add_argument("url", help="exam site, e.g. https://cbt.example.edu.ng")
    st.add_argument("--allow", action="append", default=[], metavar="HOST[:PORT]",
                    help="another server the exam site needs, with its port if not 80/443 (repeatable); "
                         "'primers-exam probe URL' finds them")
    pr = sub.add_parser("probe", help="open the exam site, sign in and go through a practice exam: "
                                      "lists every server it needs and the start command")
    pr.add_argument("url", help="exam site, e.g. https://cbt.example.edu.ng")
    pr.add_argument("--seconds", type=int, default=0, help="close the probe window by itself after this long")
    pr.add_argument("--json", action="store_true", help="machine-readable output")
    sub.add_parser("stop", help="end the exam")
    sub.add_parser("status", help="show whether an exam is running")
    lg = sub.add_parser("log", help="show the exam log")
    when = lg.add_mutually_exclusive_group()
    when.add_argument("--since", help="from this time (UTC), e.g. 2026-11-24 or '2026-11-24 09:00'")
    when.add_argument("--all", action="store_true", help="every exam on this PC")
    lg.add_argument("--export", metavar="DIR", help="copy it (JSON lines and CSV, with SHA256SUMS) into a new folder")
    # Run by the primers-exam-log service and the primers-exam-refresh timer, not by people
    sub.add_parser("log-writer", help=argparse.SUPPRESS)
    sub.add_parser("refresh", help=argparse.SUPPRESS)
    return p


def print_status(exam: exam_mode.ExamMode) -> int:
    st = exam.status()
    if st["active"] is None:
        print(f"Exam Mode: unknown ({st['error']})")
        return 1
    if not st["active"]:
        print("Exam Mode: off")
        return 0
    print("Exam Mode: ON")
    print(f"  Exam:       {st['url']}")
    print(f"  Servers:    {', '.join(st['allow'])} (ports {', '.join(map(str, st['ports']))})")
    print(f"  Started:    {st['started']}")
    if st["firewall"] is None:
        print("  Firewall and USB block: run 'sudo primers-exam status' to check")
        return 0
    print(f"  Firewall:   {'active' if st['firewall'] else 'NOT ACTIVE'}")
    print(f"  USB drives: {'blocked' if st['usb_blocked'] else 'NOT BLOCKED'}")
    print(f"  Consoles:   {'locked (no Ctrl+Alt+F1..F12, no SysRq)' if st['consoles_locked'] else 'NOT LOCKED'}")
    menu = {"locked": "locked (no editing, recovery mode or other systems)",
            "live": "not lockable in a live session (install PRIMERS OS on exam PCs)",
            "unlocked": "NOT LOCKED"}[st["boot_menu"]]
    print(f"  Boot menu:  {menu}")
    return 0 if st["firewall"] and st["usb_blocked"] and st["consoles_locked"] \
        and st["boot_menu"] != "unlocked" else 1


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    exam = exam_mode.ExamMode()
    if args.command == "status":
        return print_status(exam)
    if args.command == "probe":
        try:
            result = exam_probe.probe(args.url, args.seconds)
        except exam_probe.ProbeError as e:
            print(f"primers-exam probe: {e}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"url": result.url, "command": result.command(), "allow": result.allow_args(),
                              "servers": [vars(f) | {"resolved": f.resolved} for f in result.findings],
                              "failed": result.failed}, indent=2, default=list))
        else:
            sys.stdout.write(exam_probe.format_result(result))
        return 0 if result.findings and all(f.resolved for f in result.findings) else 1
    if os.geteuid() != 0:
        sys.exit("primers-exam: this needs administrator rights. Run it with sudo.")
    try:
        if args.command == "start":
            conf, warnings = exam.start(args.url, args.allow)
            for w in warnings:
                print("warning: " + w, file=sys.stderr)
            print(f"Exam Mode is on: {conf.url}")
            print("Candidates sign in to the shared lab account and see only the exam.")
            print("End it with: sudo primers-exam stop")
        elif args.command == "stop":
            for w in exam.stop():
                print("warning: " + w, file=sys.stderr)
            print("Exam Mode is off. The lab account is back to normal.")
        elif args.command == "log" and args.export:
            return _export_log(exam, args)
        elif args.command == "log":
            sys.stdout.write(exam.journal(args.since, args.all) or "No exam activity logged.\n")
        elif args.command == "refresh":
            exam.refresh(addresses_only=True)
        elif args.command == "log-writer":
            conf = exam.config()
            started = exam_log.parse_time(conf.started) if conf and conf.started else None
            return exam_log.run_writer(exam.examlog, started)
    except exam_mode.ExamError as e:
        print(f"primers-exam: {e}", file=sys.stderr)
        return 1
    return 0


def _export_log(exam, args) -> int:
    """primers-exam log --export DIR: the same records as the log shows (the
    last exam, --since or --all), copied for an appeal, an auditor or an
    access request (core.privacy)."""
    from core import privacy
    if args.all:
        since = None
    elif args.since:
        since = exam_log.parse_time(args.since)
        if since is None:
            raise exam_mode.ExamError(f"can't read the time {args.since!r} (e.g. 2026-11-24 09:00)")
    else:
        since = exam.examlog.last_exam_start()
    try:
        conf = privacy.PrivacyConfig.load()
        owner = (int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"])) if "SUDO_UID" in os.environ else None
        files = privacy.export(args.export, conf, since, ("exam",), exam_log_path=exam.examlog.path, owner=owner)
    except (privacy.PrivacyError, OSError, ValueError) as e:
        raise exam_mode.ExamError(str(e))
    print(f"Exported to {args.export}: " + ", ".join(os.path.basename(f) for f in files))
    print(f"Check them with: (cd {args.export} && sha256sum -c SHA256SUMS)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
