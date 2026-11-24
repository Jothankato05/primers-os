"""
primers-study — Study Mode focus timer (installed as /usr/bin/primers-study).

  primers-study start [MINUTES]   start a session (default 25 minutes)
  primers-study stop              end it early
  primers-study status            minutes left

During a session Primers Lite Bee pauses distracting sites and the panel
shows the time left; a notice appears when it ends. Same as `study` in the
PRIMERS Brain.
"""

import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import study_mode  # noqa: E402


def spawn_end_notice() -> None:
    """Detached helper that shows the 'session complete' notice."""
    subprocess.Popen([sys.executable, "-I", os.path.abspath(__file__), "wait"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)


def notify_done(session: study_mode.Session) -> None:
    text = (f"Well done: {session.minutes} minutes of focus.\n\n"
            "Take a short break. Paused sites are open again.")
    if os.environ.get("DISPLAY") and shutil.which("zenity"):
        subprocess.run(["zenity", "--info", "--title=Study session complete", "--no-wrap",
                        "--text=" + text], check=False)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="primers-study", description="Study Mode focus timer.")
    sub = p.add_subparsers(dest="command", required=True)
    st = sub.add_parser("start", help="start a study session")
    st.add_argument("minutes", nargs="?", type=int, default=study_mode.DEFAULT_MINUTES)
    sub.add_parser("stop", help="end the session early")
    sub.add_parser("status", help="show the time left")
    sub.add_parser("wait", help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    if args.command == "start":
        try:
            session = study_mode.start(args.minutes)
        except ValueError as e:
            print(f"primers-study: {e}", file=sys.stderr)
            return 2
        spawn_end_notice()
        print(f"Study Mode on for {session.minutes} min. Distracting sites are paused in Lite Bee.")
    elif args.command == "stop":
        session = study_mode.stop()
        print("Study Mode ended early." if session else "Study Mode is not running.")
    elif args.command == "status":
        session = study_mode.current()
        if session:
            print(f"Study Mode: {study_mode.format_left(session.remaining())} left "
                  f"of {session.minutes} min")
        else:
            print("Study Mode: off")
    elif args.command == "wait":
        study_mode.wait_for_end(on_done=notify_done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
