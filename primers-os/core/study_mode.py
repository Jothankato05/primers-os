"""
PRIMERS OS — Study Mode: a focus timer that pauses distractions.

``study 25`` (in the Brain) or ``primers-study start 25`` starts a 25-minute
session. While it runs, Primers Lite Bee pauses distracting sites (social
media, video, games and betting; edit ~/.config/primers/study-sites to add or
allow sites), the panel shows the minutes left, and a notice says when the
session is over. ``study stop`` ends it early.

The session is one small per-user file, so the browser and the panel can read
it without the Brain running: $XDG_STATE_HOME/primers/study (by default
~/.local/state/primers/study), with ``key=value`` lines::

    started=<unix time>
    until=<unix time>
    minutes=<n>
"""

import contextlib
import os
import time
from dataclasses import dataclass
from typing import Callable, Optional

DEFAULT_MINUTES = 25
MIN_MINUTES, MAX_MINUTES = 1, 240


def state_path() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "primers", "study")


@dataclass
class Session:
    started: int
    until: int
    minutes: int

    def remaining(self, now: Optional[float] = None) -> int:
        return max(0, self.until - int(time.time() if now is None else now))

    def active(self, now: Optional[float] = None) -> bool:
        return self.remaining(now) > 0


def format_left(seconds: int) -> str:
    if seconds >= 60:
        minutes = (seconds + 59) // 60
        return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60:02d} min"
    return f"{seconds} s"


def read(path: Optional[str] = None) -> Optional[Session]:
    """The session on file (active or just finished), or None."""
    try:
        with open(path or state_path(), encoding="utf-8") as f:
            text = f.read(4096)
    except OSError:
        return None
    values = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    try:
        return Session(int(values["started"]), int(values["until"]), int(values["minutes"]))
    except (KeyError, ValueError):
        return None


def current(path: Optional[str] = None, now: Optional[float] = None) -> Optional[Session]:
    """The running session, or None."""
    session = read(path)
    return session if session and session.active(now) else None


def start(minutes: int = DEFAULT_MINUTES, path: Optional[str] = None,
          now: Optional[float] = None) -> Session:
    if not MIN_MINUTES <= minutes <= MAX_MINUTES:
        raise ValueError(f"a study session is {MIN_MINUTES}-{MAX_MINUTES} minutes")
    path = path or state_path()
    started = int(time.time() if now is None else now)
    session = Session(started, started + minutes * 60, minutes)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f"started={session.started}\nuntil={session.until}\nminutes={session.minutes}\n")
    os.replace(tmp, path)
    return session


def stop(path: Optional[str] = None) -> Optional[Session]:
    """End the session early. Returns it if one was running."""
    path = path or state_path()
    session = current(path)
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    return session


def wait_for_end(path: Optional[str] = None, on_done: Optional[Callable[[Session], None]] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time) -> Optional[Session]:
    """Block until the session that is running now ends.

    Returns the session when it ran to the end (after calling ``on_done``),
    or None when it was stopped or replaced by a new one first.
    """
    path = path or state_path()
    mine = current(path, clock())
    if mine is None:
        return None
    while True:
        session = read(path)
        if session is None or session.started != mine.started:
            return None                    # stopped, or a new session took over
        left = session.remaining(clock())
        if left <= 0:
            break
        sleep(min(left, 5))
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    if on_done:
        on_done(mine)
    return mine
