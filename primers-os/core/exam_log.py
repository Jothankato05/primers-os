"""
PRIMERS OS — the exam log, written so that a power cut can't lose it.

Every exam event (sessions, pages, blocked attempts, finishes, the exam
starting and stopping) is one JSON line in /var/log/primers/exam.jsonl,
appended and fsync'd before the call returns.

* Root's own events (``primers-exam``, Lab Mode hooks) are appended
  directly by the process that logs them.
* The candidate's events come from the exam session and the kiosk, which
  run as the lab account and can only use syslog. ``primers-exam
  log-writer`` (the primers-exam-log service) follows the journal for the
  ``primers-exam`` tag and appends each of those entries as soon as
  journald has it, so they don't wait for journald's own sync (every five
  minutes by default).

A power cut can tear the last line in half: readers skip a line that isn't
valid JSON, and the next append starts on a new line.
"""

import contextlib
import json
import os
import pwd
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

LOG_PATH = "/var/log/primers/exam.jsonl"
LOG_TAG = "primers-exam"
BOOT_ID = "/proc/sys/kernel/random/boot_id"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_time(text: str) -> Optional[datetime]:
    """A record's time, or a user's --since (2026-11-25, 2026-11-25 09:30,
    or the "2026-11-25 09:30:00 UTC" form exam.conf uses). Naive times are UTC."""
    text = text.strip().replace("T", " ").rstrip("Z").replace(" UTC", "")
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        with contextlib.suppress(ValueError):
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
    return None


def _fsync_dir(path: str) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass
class Record:
    time: str
    message: str
    uid: int = 0
    user: str = "root"
    pid: int = 0
    boot: str = ""
    cursor: str = ""          # journal cursor, for entries copied from the journal

    def to_json(self) -> str:
        data = {"time": self.time, "message": self.message, "uid": self.uid, "user": self.user,
                "pid": self.pid, "boot": self.boot}
        if self.cursor:
            data["cursor"] = self.cursor
        return json.dumps(data, sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> Optional["Record"]:
        try:
            data = json.loads(line)
            return cls(time=str(data["time"]), message=str(data["message"]),
                       uid=int(data.get("uid", 0)), user=str(data.get("user", "")),
                       pid=int(data.get("pid", 0)), boot=str(data.get("boot", "")),
                       cursor=str(data.get("cursor", "")))
        except (ValueError, KeyError, TypeError):
            return None


class ExamLog:
    def __init__(self, path: str = LOG_PATH, boot_id_path: str = BOOT_ID):
        self.path = path
        self.boot_id_path = boot_id_path

    def boot_id(self) -> str:
        try:
            with open(self.boot_id_path, encoding="ascii") as f:
                return f.read().strip()
        except OSError:
            return ""

    def append(self, record: Record) -> None:
        """Append one record and make it durable before returning."""
        directory = os.path.dirname(self.path)
        if not os.path.isdir(directory):
            os.makedirs(directory, mode=0o750, exist_ok=True)
            _fsync_dir(os.path.dirname(directory) or "/")
        created = not os.path.exists(self.path)
        fd = os.open(self.path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o640)
        try:
            data = (record.to_json() + "\n").encode("utf-8")
            size = os.fstat(fd).st_size
            if size:
                # A power cut may have torn the last line: start a new one
                last = os.pread(fd, 1, size - 1)
                if last != b"\n":
                    data = b"\n" + data
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        if created:
            _fsync_dir(directory)

    def log(self, message: str, uid: Optional[int] = None, user: Optional[str] = None) -> Record:
        uid = os.getuid() if uid is None else uid
        if user is None:
            try:
                user = pwd.getpwuid(uid).pw_name
            except KeyError:
                user = str(uid)
        record = Record(utc_now(), message, uid, user, os.getpid(), self.boot_id())
        self.append(record)
        return record

    def records(self) -> Tuple[List[Record], int]:
        """Every readable record, and how many lines were damaged (a line
        torn by a power cut)."""
        out, damaged = [], 0
        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    record = Record.from_json(line)
                    if record is None:
                        damaged += 1
                    else:
                        out.append(record)
        except FileNotFoundError:
            pass
        return out, damaged

    def since(self, when: Optional[datetime]) -> Tuple[List[Record], int]:
        records, damaged = self.records()
        if when is None:
            return records, damaged
        return [r for r in records if (parse_time(r.time) or when) >= when], damaged

    def last_exam_start(self) -> Optional[datetime]:
        records, _ = self.records()
        for record in reversed(records):
            if record.uid == 0 and record.message.startswith("exam started:"):
                return parse_time(record.time)
        return None


def format_record(record: Record) -> str:
    when = parse_time(record.time)
    stamp = when.strftime("%Y-%m-%d %H:%M:%S UTC") if when else record.time
    return f"{stamp}  {record.user or record.uid:<8} {record.message}"


# ------------------------------------------------------------------ #
#  Copying the candidate's entries from the journal
# ------------------------------------------------------------------ #

def journal_record(entry: Dict, users: Callable[[int], str]) -> Optional[Record]:
    """A journal entry (journalctl -o json) as a log record, or None for
    entries that aren't the candidate's: root's are already in the log."""
    try:
        uid = int(entry.get("_UID", "0"))
    except ValueError:
        return None
    if uid == 0:
        return None
    message = entry.get("MESSAGE")
    if isinstance(message, list):                 # non-UTF-8 message: bytes
        message = bytes(message).decode("utf-8", "replace")
    if not isinstance(message, str):
        return None
    try:
        usec = int(entry.get("__REALTIME_TIMESTAMP", "0"))
    except ValueError:
        usec = 0
    when = datetime.fromtimestamp(usec / 1e6, timezone.utc) if usec else datetime.now(timezone.utc)
    try:
        pid = int(entry.get("_PID", "0"))
    except ValueError:
        pid = 0
    return Record(when.strftime("%Y-%m-%dT%H:%M:%S.%fZ"), message, uid, users(uid), pid,
                  str(entry.get("_BOOT_ID", "")), str(entry.get("__CURSOR", "")))


def _user_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def follow_start(log: ExamLog, exam_started: Optional[datetime]) -> Tuple[datetime, set]:
    """Where to start reading the journal, and the cursors already copied.

    From the last copied entry (a second before, as journal times and ours
    can tie), or from the start of the exam when nothing was copied yet.
    Cursors are compared rather than trusted for seeking: after a power cut
    the journal may not have kept the entry a saved cursor points at.
    """
    records, _ = log.records()
    copied = [r for r in records if r.cursor]
    if copied:
        start = (parse_time(copied[-1].time) or datetime.now(timezone.utc)) - timedelta(seconds=1)
    else:
        start = exam_started or (datetime.now(timezone.utc) - timedelta(hours=1))
    seen = {r.cursor for r in copied if (parse_time(r.time) or start) >= start}
    return start, seen


def copy_entries(lines: Iterable[str], log: ExamLog, seen: set,
                 users: Callable[[int], str] = _user_name) -> int:
    """Append each new candidate entry from journalctl -o json lines."""
    count = 0
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        record = journal_record(entry, users)
        if record is None or (record.cursor and record.cursor in seen):
            continue
        log.append(record)
        if record.cursor:
            seen.add(record.cursor)
        count += 1
    return count


def follow_command(start: datetime) -> List[str]:
    return ["journalctl", "--follow", "--output=json", "--no-pager", "--identifier", LOG_TAG,
            "--since", start.strftime("%Y-%m-%d %H:%M:%S UTC")]


def run_writer(log: ExamLog, exam_started: Optional[datetime],
               popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> int:
    """The primers-exam-log service: copy entries until journalctl stops
    (systemd then restarts the service, which resumes where it left off)."""
    start, seen = follow_start(log, exam_started)
    proc = popen(follow_command(start), stdout=subprocess.PIPE, text=True, encoding="utf-8",
                 errors="replace")
    try:
        copy_entries(proc.stdout, log, seen)
    finally:
        with contextlib.suppress(OSError):
            proc.terminate()
        proc.wait()
    return 1
