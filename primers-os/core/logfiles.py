"""
PRIMERS OS — the JSON-lines logs in /var/log/primers: one lock shared by
everything that appends to a log and by the retention pass that removes
old records from it (core.privacy), so no record is lost while a log is
rewritten.

The lock is a separate file (``<log>.lock``) because the retention pass
replaces the log file itself: a writer that locked the old file could
still append to it after it was replaced.
"""

import contextlib
import fcntl
import json
import os
import stat
from datetime import datetime, timezone
from typing import Callable, Iterator, Optional, Tuple


@contextlib.contextmanager
def locked(path: str) -> Iterator[None]:
    """Hold the log's lock (exclusive) for the duration of the block."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, mode=0o750, exist_ok=True)
    fd = os.open(f"{path}.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)                    # releases the lock


def parse_time(text: str) -> Optional[datetime]:
    """A record's time: ISO 8601 with Z, an offset, or none (UTC)."""
    text = str(text).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def record_time(line: bytes) -> Optional[datetime]:
    try:
        data = json.loads(line)
    except ValueError:
        return None
    return parse_time(data.get("time", "")) if isinstance(data, dict) else None


def fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prune(path: str, cutoff: datetime,
          time_of: Callable[[bytes], Optional[datetime]] = record_time) -> Tuple[int, int]:
    """Remove the records older than ``cutoff``; (records kept, lines removed).

    A line that isn't a record (torn by a power cut) goes with the record
    before it. The file keeps its owner and mode, and is replaced in one
    step (written, fsync'd, renamed), so a crash leaves the old or the new
    log, never a mix."""
    with locked(path):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError:
            return 0, 0
        with os.fdopen(fd, "rb") as f:
            st = os.fstat(f.fileno())
            if not stat.S_ISREG(st.st_mode):
                raise OSError(f"{path} is not a regular file")
            lines = f.read().split(b"\n")
        keep, removed, dropping = [], 0, True
        for line in lines:
            if not line.strip():
                continue
            when = time_of(line)
            if when is not None:
                dropping = when < cutoff
            if dropping:
                removed += 1
            else:
                keep.append(line)
        if not removed:
            return len(keep), 0
        directory = os.path.dirname(path) or "."
        tmp = f"{path}.prune"
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            if (st.st_uid, st.st_gid) != (os.getuid(), os.getgid()):
                os.fchown(fd, st.st_uid, st.st_gid)
            os.fchmod(fd, stat.S_IMODE(st.st_mode))
            data = b"\n".join(keep) + (b"\n" if keep else b"")
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            os.unlink(tmp)
            raise
        os.close(fd)
        os.replace(tmp, path)
        fsync_dir(directory)
        return len(keep), removed
