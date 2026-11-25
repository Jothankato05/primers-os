"""
primers-reduce-motion — less movement on screen (installed as /usr/bin/primers-reduce-motion).

  sudo primers-reduce-motion on       the boot splash's cursor stays still; no GTK animations;
                                      web pages see prefers-reduced-motion
  sudo primers-reduce-motion off      back to normal
       primers-reduce-motion status   is it on?
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import motion  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="primers-reduce-motion", description="Less movement on screen.")
    p.add_argument("action", choices=["on", "off", "status"], nargs="?", default="status")
    args = p.parse_args(argv)
    m = motion.Motion()
    if args.action == "status":
        print(f"Reduced motion: {'on' if m.reduced() else 'off'}")
        return 0
    if os.geteuid() != 0:
        print("primers-reduce-motion on/off needs sudo (it changes settings for everyone).", file=sys.stderr)
        return 1
    try:
        note = m.set(args.action == "on")
    except (motion.MotionError, OSError) as e:
        print(f"primers-reduce-motion: {e}", file=sys.stderr)
        return 1
    print(f"Reduced motion is {args.action}. {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
