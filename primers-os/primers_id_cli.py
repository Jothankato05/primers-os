"""
primers-id — sign in with your Primers ID (installed as /usr/bin/primers-id).

  primers-id login [--browser] [--no-pin]   sign in (a code to type at Primers ID, or the browser);
                                            choose a PIN for signing in when offline
  primers-id login --offline                sign in with that PIN when Primers ID can't be reached
  primers-id status [--json]                who is signed in, and how
  primers-id logout                         sign out on this PC

The provider is set in /etc/primers/id.conf (issuer, client_id).
"""

import argparse
import getpass
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import primers_id as pid  # noqa: E402


def _show(uri: str, code: str, complete) -> None:
    print("\nTo sign in, open this address on this PC or your phone:\n")
    print(f"  {complete or uri}\n")
    print(f"and enter the code:  {code}\n\nWaiting…", flush=True)


def _read_pin(prompt: str, from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().strip()
    return getpass.getpass(prompt)


def _choose_pin(from_stdin: bool):
    if from_stdin:
        return sys.stdin.readline().strip() or None
    print("Choose a PIN for signing in when Primers ID can't be reached (4 or more digits; Enter to skip).")
    first = getpass.getpass("PIN: ")
    if not first:
        return None
    if getpass.getpass("PIN again: ") != first:
        raise pid.IdError("the PINs don't match")
    return first


def _describe(s: dict) -> str:
    who = s.get("name") or s.get("sub")
    extra = f" <{s['email']}>" if s.get("email") else ""
    how = "offline, with your PIN" if s.get("mode") == "offline" else "online"
    return f"Signed in as {who}{extra} ({how})."


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="primers-id", description="Sign in with your Primers ID.")
    sub = p.add_subparsers(dest="command", required=True)
    lg = sub.add_parser("login", help="sign in")
    lg.add_argument("--offline", action="store_true", help="sign in with your PIN, without Primers ID")
    lg.add_argument("--browser", action="store_true", help="sign in through the browser on this PC")
    lg.add_argument("--no-pin", action="store_true", help="don't set up offline sign-in")
    lg.add_argument("--pin-stdin", action="store_true", help=argparse.SUPPRESS)    # scripts and tests
    st = sub.add_parser("status", help="who is signed in")
    st.add_argument("--json", action="store_true")
    sub.add_parser("logout", help="sign out on this PC")
    args = p.parse_args(argv)
    try:
        ident = pid.PrimersID(pid.IdConfig.load())
        if args.command == "status":
            s = ident.status()
            if args.json:
                print(json.dumps(s or {}, indent=2, sort_keys=True))
            else:
                print(_describe(s) if s else "Not signed in with Primers ID.")
            return 0 if s else 1
        if args.command == "logout":
            print("Signed out." if ident.logout() else "Not signed in.")
            return 0
        if args.offline:
            s = ident.offline_login(_read_pin("PIN: ", args.pin_stdin))
            print(_describe(s))
            return 0
        pin = None if args.no_pin else _choose_pin(args.pin_stdin)
        try:
            s = ident.browser_login(pin) if args.browser else ident.login(_show, pin)
        except pid.Unreachable as e:
            print(f"{e}.", file=sys.stderr)
            if (ident.store.load() or {}).get("pin_hash"):
                print("You can sign in offline with your PIN: primers-id login --offline", file=sys.stderr)
            return 2
        print(_describe(s))
        return 0
    except pid.IdError as e:
        print(f"primers-id: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
