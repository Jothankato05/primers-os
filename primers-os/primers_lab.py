"""
primers-lab — Lab Mode for shared computers (installed as /usr/bin/primers-lab).

  sudo primers-lab enable [--user NAME] [--template DIR]
  sudo primers-lab disable
       primers-lab status
  sudo primers-lab reset

The lab account (default "lab") signs in without a password and is never an
administrator. Everything in its home folder is deleted and rebuilt from the
template (/etc/primers/lab-skel if it exists, otherwise /etc/skel) when a
session starts, when it ends, and at every boot.

Called by the system, not by people:
  primers-lab hook session-setup|session-cleanup|boot   (LightDM, systemd)
  primers-lab notice                                    (desktop autostart)
"""

import time

STARTED = time.monotonic()      # before the imports below: how long the boot hook really takes

import argparse  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import lab_mode  # noqa: E402

NOTICE = ("This is a shared lab computer.\n\n"
          "Everything you save in this account (documents, downloads, browser history "
          "and saved passwords) is deleted when you sign out.\n\n"
          "Save your work to a USB stick or online before you leave.")


def _privacy_layer() -> str:
    """The privacy notice's short layer: the lab account sees it at every sign-in."""
    from core import privacy
    try:
        conf = privacy.PrivacyConfig.load()
    except privacy.PrivacyError:
        conf = privacy.PrivacyConfig()
    return privacy.short_notice(conf)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="primers-lab",
        description="Lab Mode: a shared, passwordless account that is wiped at every sign-out.")
    sub = p.add_subparsers(dest="command", required=True)
    en = sub.add_parser("enable", help="create the lab account and turn Lab Mode on")
    en.add_argument("--user", default=lab_mode.DEFAULT_USER, help="account name (default: lab)")
    en.add_argument("--template", help="folder copied into the fresh home "
                                       "(default: /etc/primers/lab-skel, else /etc/skel)")
    sub.add_parser("disable", help="turn Lab Mode off and delete the lab account")
    sub.add_parser("status", help="show whether Lab Mode is on")
    sub.add_parser("reset", help="wipe the lab account now")
    sub.add_parser("notice", help="show the shared-computer notice (lab session only)")
    hk = sub.add_parser("hook", help=argparse.SUPPRESS)
    hk.add_argument("event", choices=lab_mode.HOOK_EVENTS)
    return p


def _need_root() -> None:
    if os.geteuid() != 0:
        sys.exit("primers-lab: this needs administrator rights. Run it with sudo.")


def _print_status(lab: lab_mode.LabMode) -> int:
    st = lab.status()
    if st["enabled"] is None:
        print(f"Lab Mode: unknown ({st['error']})")
        return 1
    if not st["enabled"]:
        print("Lab Mode: off")
        print("Turn it on for a shared computer: sudo primers-lab enable")
        return 0
    print("Lab Mode: on")
    print(f"  Account:     {st['user']} (no password, not an administrator)"
          + ("" if st["account_exists"] else "  [MISSING]"))
    print(f"  Wiped:       at every sign-in, sign-out and boot"
          + ("" if st["login_hooks"] else "  [login hooks missing]"))
    print(f"  Fresh home:  copied from {st['template']}")
    print(f"  Last reset:  {st['last_reset'] or 'never'}")
    if not st["sign_in_ready"]:
        print("  Sign-in:     after the next restart (restart the computer to finish)")
    return 0


# exam_mode.ExamPaths().conf, here so a boot without an exam doesn't load Exam Mode
EXAM_CONF = "/etc/primers/exam.conf"


def exam_hook(lab: lab_mode.LabMode, event: str, user) -> int:
    """During an exam, refresh the exam firewall at boot and before every
    lab session. No firewall, no exam session (fail closed)."""
    if event not in ("boot", "session-setup") or (event == "session-setup" and not lab.is_lab_session(user)):
        return 0
    if not os.path.exists(EXAM_CONF):
        return 0            # no exam: nothing to refresh (and no need to load the exam module)
    from core import exam_mode
    exam = exam_mode.ExamMode(lab)
    try:
        exam.refresh()
        return 0
    except (exam_mode.ExamError, OSError) as e:
        exam.log(f"{event}: exam firewall not in place: {e}")
        return 1


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    lab = lab_mode.LabMode()

    if args.command == "status":
        return _print_status(lab)

    if args.command == "notice":
        if not lab.is_lab_session():
            return 0
        text = NOTICE + "\n\n" + _privacy_layer()
        if os.environ.get("DISPLAY") and shutil.which("zenity"):
            subprocess.run(["zenity", "--warning", "--title=Shared lab computer", "--width=520",
                            "--text=" + text], check=False)
        else:
            print(text)
        return 0

    _need_root()
    if args.command == "hook":
        user = os.environ.get("USER") or None
        try:
            rc = lab.hook(args.event, user)
            if rc == 0:
                rc = exam_hook(lab, args.event, user)
            if args.event == "boot":
                lab.log(f"boot hook done {time.monotonic() - STARTED:.1f} s after primers-lab started")
            return rc
        except Exception as e:  # a crash must never let a dirty lab session start
            lab.log(f"hook {args.event} crashed: {e!r}")
            return 1 if (args.event == "boot" or lab.is_lab_session(user)) else 0

    try:
        if args.command == "enable":
            conf = lab.enable(args.user, args.template)
            print("Lab Mode is on. Restart the computer to finish: after the restart,")
            print(f"students sign in as '{conf.user}' without a password, and their files are")
            print("deleted at every sign-in, sign-out and boot.")
            print(f"Customise the fresh desktop by editing {conf.template}.")
        elif args.command == "disable":
            for warning in lab.disable():
                print("warning: " + warning, file=sys.stderr)
            print("Lab Mode is off and the lab account has been deleted.")
        elif args.command == "reset":
            acct = lab.reset("manual")
            print(f"The '{acct.name}' account has been wiped and reset.")
    except lab_mode.LabError as e:
        print(f"primers-lab: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
