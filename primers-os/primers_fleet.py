"""
primers-fleet — run exams on a lab's PCs from the invigilator's PC (installed as /usr/bin/primers-fleet).

On the invigilator's PC:
  sudo primers-fleet pair [--minutes 15]          let lab PCs join (shows a one-time code)
  sudo primers-fleet list                         the paired PCs
  sudo primers-fleet status [--watch S] [--json]  each PC: reachable, Lab Mode, exam, candidate
  sudo primers-fleet exam-start URL [--allow HOST[:PORT]]... [--pc NAME]...
  sudo primers-fleet exam-stop [--pc NAME]...
  sudo primers-fleet collect DIR [--pc NAME]...   every PC's exam log, with SHA256SUMS
  sudo primers-fleet forget NAME                  unpair a PC
On each lab PC:
  sudo primers-fleet join INVIGILATOR-PC CODE     pair with the invigilator's PC
  sudo primers-fleet leave                        stop being controlled
On either:
  sudo primers-fleet id                           this PC's fingerprint

Only paired PCs talk to each other (TLS with both certificates checked), lab
PCs run only these commands, and both sides log every command to
/var/log/primers/fleet.jsonl.
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import fleet  # noqa: E402

AGENT_UNIT = "primers-fleet-agent.service"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="primers-fleet",
                                description="Run exams on a lab's PCs from the invigilator's PC.")
    sub = p.add_subparsers(dest="command", required=True)
    pa = sub.add_parser("pair", help="let lab PCs join this PC (shows a one-time code)")
    pa.add_argument("--minutes", type=int, default=fleet.PAIR_MINUTES)
    jo = sub.add_parser("join", help="pair this lab PC with the invigilator's PC")
    jo.add_argument("controller", help="the invigilator's PC: its address or name")
    jo.add_argument("code", help="the code 'primers-fleet pair' shows there")
    sub.add_parser("list", help="the paired PCs")
    st = sub.add_parser("status", help="each paired PC: reachable, Lab Mode, exam, candidate")
    st.add_argument("--json", action="store_true")
    st.add_argument("--watch", type=int, default=0, metavar="SECONDS", help="refresh every SECONDS")
    st.add_argument("--pc", action="append", default=[], metavar="NAME")
    es = sub.add_parser("exam-start", help="start the exam on the paired PCs")
    es.add_argument("url")
    es.add_argument("--allow", action="append", default=[], metavar="HOST[:PORT]")
    es.add_argument("--pc", action="append", default=[], metavar="NAME", help="only these PCs (repeatable)")
    ex = sub.add_parser("exam-stop", help="end the exam on the paired PCs")
    ex.add_argument("--pc", action="append", default=[], metavar="NAME")
    co = sub.add_parser("collect", help="copy every PC's exam log into DIR")
    co.add_argument("dest")
    co.add_argument("--pc", action="append", default=[], metavar="NAME")
    fo = sub.add_parser("forget", help="unpair a lab PC")
    fo.add_argument("name")
    sub.add_parser("leave", help="on a lab PC: stop being controlled by any invigilator PC")
    sub.add_parser("id", help="this PC's fingerprint")
    sub.add_parser("agent", help=argparse.SUPPRESS)      # the lab PC's service
    return p


def _addresses() -> str:
    try:
        r = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
        return ", ".join(a for a in r.stdout.split() if not a.startswith("fe80")) or "no network address"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def _ufw(*args: str) -> bool:
    """A firewall rule, when the firewall (ufw) is on; PRIMERS OS denies incoming by default."""
    try:
        active = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=30)
        if "Status: active" not in active.stdout:
            return True
        return subprocess.run(["ufw", *args], capture_output=True, text=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return True                                     # no ufw on this system


def _agent_rule(address: str) -> List[str]:
    return ["from", address, "to", "any", "port", str(fleet.AGENT_PORT), "proto", "tcp"]


def _give_to_caller(dest: str, names: List[str]) -> None:
    """The copied logs belong to the person who ran sudo, not to root."""
    try:
        uid, gid = int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"])
    except (KeyError, ValueError):
        return
    paths = [dest, os.path.join(dest, "SHA256SUMS")]
    for name in names:
        paths += [os.path.join(dest, name), os.path.join(dest, name, "exam.jsonl")]
    for path in paths:
        if os.path.lexists(path) and not os.path.islink(path):
            os.chown(path, uid, gid)


def cmd_pair(paths: fleet.FleetPaths, minutes: int) -> int:
    code = fleet.new_code()
    pairing = fleet.Pairing(paths, code,
                            on_paired=lambda pc: print(f"  paired {pc.name} ({pc.address})", flush=True),
                            on_refused=lambda addr, why: print(f"  refused {addr}: {why}", flush=True))
    print(f"Pairing is open for {minutes} minutes on {socket.gethostname()} ({_addresses()}).")
    print(f"This PC's fingerprint: {fleet.fingerprint(fleet.ensure_identity(paths))}")
    print("\nOn each lab PC, run:\n")
    print(f"  sudo primers-fleet join {_addresses().split(',')[0]} {code}\n")
    print("Press Ctrl+C when every PC has joined.", flush=True)
    pair_rule = [f"{fleet.PAIR_PORT}/tcp"]

    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)                 # stopped any way: close the port again
    signal.signal(signal.SIGHUP, stop)
    _ufw("allow", *pair_rule)                          # open only while pairing
    try:
        pairing.serve(minutes * 60)
    except KeyboardInterrupt:
        pass
    finally:
        _ufw("delete", "allow", *pair_rule)
    if pairing.failures >= fleet.MAX_PAIR_FAILURES:
        print("Pairing closed: too many wrong codes. Run 'primers-fleet pair' again for a new code.")
    print(f"{len(fleet.load_pcs(paths))} PC(s) paired.")
    return 0


def cmd_join(paths: fleet.FleetPaths, controller: str, code: str) -> int:
    fp = fleet.join(paths, controller, code)
    print(f"Paired with {controller} (fingerprint {fp}).")
    for address in fleet.controller_addresses(paths):  # only the invigilator PC may connect
        if not _ufw("allow", *_agent_rule(address)):
            print(f"Couldn't open the firewall for {address}.", file=sys.stderr)
    r = subprocess.run(["systemctl", "enable", "--now", AGENT_UNIT], capture_output=True, text=True)
    subprocess.run(["systemctl", "restart", AGENT_UNIT], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Couldn't start {AGENT_UNIT}: {r.stderr.strip()}", file=sys.stderr)
        return 1
    print("The invigilator's PC can now start and stop exams here, see their status and collect the exam log.")
    return 0


def cmd_status(paths: fleet.FleetPaths, args) -> int:
    pcs = fleet.select(paths, args.pc)
    if not pcs:
        print("No PCs paired yet: run 'sudo primers-fleet pair' here, then 'primers-fleet join' on each lab PC.")
        return 1
    while True:
        rows = fleet.on_each(paths, pcs, "status", timeout=10)
        if args.json:
            print(json.dumps({name: r for name, r in rows.items()}, indent=2, sort_keys=True), flush=True)
        else:
            if args.watch:
                print("\033[2J\033[H", end="")
                print(time.strftime("%H:%M:%S"), "· refreshing every", args.watch, "s · Ctrl+C to stop")
            print(fleet.format_status(rows, pcs), end="", flush=True)
        if not args.watch:
            return 0 if all(r.get("ok") for r in rows.values()) else 1
        time.sleep(args.watch)


def _report(results: dict, what: str) -> int:
    bad = 0
    for name, r in results.items():
        if r.get("ok"):
            print(f"  {name}: {what}")
        else:
            bad += 1
            print(f"  {name}: FAILED: {r.get('error', 'unknown error')}")
    print(f"{len(results) - bad} of {len(results)} PC(s) done.")
    return 1 if bad else 0


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    paths = fleet.FleetPaths()
    if args.command != "agent" and os.geteuid() != 0:
        print("primers-fleet needs sudo (its keys are root's).", file=sys.stderr)
        return 1
    try:
        if args.command == "pair":
            return cmd_pair(paths, max(1, args.minutes))
        if args.command == "join":
            return cmd_join(paths, args.controller, args.code)
        if args.command == "list":
            pcs = fleet.load_pcs(paths)
            for pc in pcs:
                print(f"{pc.name}\t{pc.address}\t{pc.fingerprint}\tpaired {pc.paired_at}")
            if not pcs:
                print("No PCs paired.")
            return 0
        if args.command == "status":
            return cmd_status(paths, args)
        if args.command == "exam-start":
            results = fleet.on_each(paths, fleet.select(paths, args.pc), "exam-start",
                                    {"url": args.url, "allow": args.allow}, timeout=30)
            return _report(results, f"exam on ({args.url})")
        if args.command == "exam-stop":
            return _report(fleet.on_each(paths, fleet.select(paths, args.pc), "exam-stop", timeout=30), "exam off")
        if args.command == "collect":
            dest = os.path.abspath(args.dest)
            results = fleet.collect(paths, fleet.select(paths, args.pc), dest)
            _give_to_caller(dest, [name for name, r in results.items() if r.get("ok")])
            code = _report(results, "log copied")
            print(f"Logs in {os.path.abspath(args.dest)} (check them with: sha256sum -c SHA256SUMS)")
            return code
        if args.command == "forget":
            if fleet.forget_pc(paths, args.name):
                fleet.log_event(paths, "forgot", pc=fleet.clean_name(args.name))
                print(f"Forgot {args.name}. To stop it accepting this PC too, run 'sudo primers-fleet leave' on it.")
                return 0
            print(f"{args.name} isn't paired.", file=sys.stderr)
            return 1
        if args.command == "leave":
            for address in fleet.controller_addresses(paths):
                _ufw("delete", "allow", *_agent_rule(address))
            n = fleet.forget_controllers(paths)
            fleet.log_event(paths, "left", controllers=n)
            subprocess.run(["systemctl", "disable", "--now", AGENT_UNIT], capture_output=True)
            print(f"This PC no longer accepts commands ({n} invigilator PC(s) forgotten).")
            return 0
        if args.command == "id":
            print(fleet.fingerprint(fleet.ensure_identity(paths)))
            return 0
        if args.command == "agent":
            agent = fleet.Agent(paths)
            fleet.log_event(paths, "agent started", port=fleet.AGENT_PORT,
                            controllers=list(fleet.controllers(paths)))
            agent.serve_forever()
            return 0
    except fleet.FleetError as e:
        print(f"primers-fleet: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"primers-fleet: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
