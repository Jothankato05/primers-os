"""
primers-exam — Exam Mode for computer-based tests (installed as /usr/bin/primers-exam).

  sudo primers-exam start URL [--allow HOST]...   start an exam on this PC
  sudo primers-exam stop                          end it
       primers-exam status                        is an exam running?
  sudo primers-exam log [--since TIME]            what happened during the exam

Needs Lab Mode. While an exam runs, signing in to the shared lab account
opens only the exam site, full screen, and that account can reach only the
exam server(s). USB drives are blocked and activity is logged. Use --allow
for any other server the exam site loads from (e.g. a CDN or login server).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import exam_mode  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="primers-exam",
                                description="Exam Mode: lock the lab account to an exam site.")
    sub = p.add_subparsers(dest="command", required=True)
    st = sub.add_parser("start", help="start an exam")
    st.add_argument("url", help="exam site, e.g. https://cbt.example.edu.ng")
    st.add_argument("--allow", action="append", default=[], metavar="HOST",
                    help="another server the exam site needs (repeatable)")
    sub.add_parser("stop", help="end the exam")
    sub.add_parser("status", help="show whether an exam is running")
    lg = sub.add_parser("log", help="show the exam log")
    lg.add_argument("--since", help="e.g. today, '2026-11-24 09:00' or --since=-2h")
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
    return 0 if st["firewall"] and st["usb_blocked"] else 1


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    exam = exam_mode.ExamMode()
    if args.command == "status":
        return print_status(exam)
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
        elif args.command == "log":
            sys.stdout.write(exam.journal(args.since) or "No exam activity logged.\n")
    except exam_mode.ExamError as e:
        print(f"primers-exam: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
