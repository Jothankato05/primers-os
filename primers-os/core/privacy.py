"""
PRIMERS OS — privacy: the notice people see, how long the logs are kept,
and exporting them (Nigeria Data Protection Act 2023, NDPA).

* The notice (``primers-privacy notice``) says what PRIMERS OS records,
  why, for how long, who is responsible and the person's rights. It is
  shown once per account at the first desktop sign-in on an installed PC
  (again when the notice changes), and any time from the desktop menu
  (System › Privacy notice). The shared lab account shows a short version
  in its shared-computer notice at every sign-in instead, pointing to the
  full one.
* Retention: the exam log and the lab control (fleet) log keep records for
  ``exam_log_days`` / ``fleet_log_days`` days (90 by default); a daily
  timer removes older records (never from the exam log while an exam is
  running), and the system journal, which also holds the exam events, is
  limited to the same time.
* Export: ``primers-privacy export DIR`` copies the logs as JSON lines and
  CSV with SHA256SUMS, for an access request or an auditor.

Settings: /etc/primers/privacy.conf. Decisions: docs/decisions/0008-privacy.md.
"""

import configparser
import contextlib
import csv
import hashlib
import io
import json
import os
import socket
import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from core import exam_log, logfiles

CONF_PATH = "/etc/primers/privacy.conf"
EXAM_LOG = exam_log.LOG_PATH
FLEET_LOG = "/var/log/primers/fleet.jsonl"
EXAM_CONF = "/etc/primers/exam.conf"            # present while an exam is running
JOURNALD_DROPIN = "/etc/systemd/journald.conf.d/90-primers-retention.conf"
DOC = "/usr/share/doc/primers/privacy.md"
NOTICE_VERSION = "2026-11-25"                   # change it to show the notice to everyone again
DEFAULT_DAYS = 90
MIN_DAYS, MAX_DAYS = 1, 3650
JOURNAL_FILE_DAYS = 7                           # the journal starts a new file weekly (MaxFileSec)
FIELD_MAX = 200


class PrivacyError(Exception):
    pass


def _clean(value: str) -> str:
    value = " ".join(str(value).split())
    if len(value) > FIELD_MAX:
        raise PrivacyError(f"keep it under {FIELD_MAX} characters")
    return value


def _days(value, what: str) -> int:
    try:
        days = int(str(value).strip())
    except ValueError:
        raise PrivacyError(f"{what} must be a whole number of days")
    if not MIN_DAYS <= days <= MAX_DAYS:
        raise PrivacyError(f"{what} must be between {MIN_DAYS} and {MAX_DAYS} days")
    return days


# ------------------------------------------------------------------ #
#  Settings
# ------------------------------------------------------------------ #

@dataclass
class PrivacyConfig:
    controller: str = ""          # the institution: the data controller under the NDPA
    contact: str = ""             # how people reach it about their data
    dpo: str = ""                 # its data protection officer, if it has one
    exam_log_days: int = DEFAULT_DAYS
    fleet_log_days: int = DEFAULT_DAYS

    @classmethod
    def load(cls, path: str = CONF_PATH) -> "PrivacyConfig":
        cp = configparser.ConfigParser(interpolation=None)
        try:
            cp.read(path, encoding="utf-8")
        except configparser.Error as e:
            raise PrivacyError(f"{path} is damaged: {e}")
        c = cp["controller"] if cp.has_section("controller") else {}
        r = cp["retention"] if cp.has_section("retention") else {}
        return cls(controller=_clean(c.get("name", "")), contact=_clean(c.get("contact", "")),
                   dpo=_clean(c.get("dpo", "")),
                   exam_log_days=_days(r.get("exam_log_days", DEFAULT_DAYS), "exam_log_days"),
                   fleet_log_days=_days(r.get("fleet_log_days", DEFAULT_DAYS), "fleet_log_days"))

    def text(self) -> str:
        return "\n".join(line.rstrip() for line in self._text().split("\n"))

    def _text(self) -> str:
        return ("# PRIMERS OS privacy settings: change them with 'sudo primers-privacy'\n"
                "# (controller, retention). See /usr/share/doc/primers/privacy.md.\n"
                "[controller]\n"
                "# The institution that runs these PCs (the data controller under the NDPA),\n"
                "# how to reach it about personal data, and its data protection officer\n"
                f"name = {self.controller}\ncontact = {self.contact}\ndpo = {self.dpo}\n\n"
                "[retention]\n"
                "# Days the exam log and the lab control (primers-fleet) log keep records\n"
                f"exam_log_days = {self.exam_log_days}\nfleet_log_days = {self.fleet_log_days}\n")

    def save(self, path: str = CONF_PATH) -> None:
        _atomic_write(path, self.text(), 0o644)


def _atomic_write(path: str, text: str, mode: int) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    logfiles.fsync_dir(directory)


def journald_dropin(days: int) -> str:
    return ("# PRIMERS OS: the system journal also holds the exam events, so it keeps\n"
            "# nothing longer than the exam log does (sudo primers-privacy retention).\n"
            "[Journal]\n"
            f"MaxRetentionSec={days}day\n"
            f"MaxFileSec={JOURNAL_FILE_DAYS}day\n")


# ------------------------------------------------------------------ #
#  The notice
# ------------------------------------------------------------------ #

def _wrap(text: str, indent: str = "") -> str:
    return textwrap.fill(" ".join(text.split()), width=74, initial_indent=indent, subsequent_indent=indent)


def notice(conf: PrivacyConfig) -> str:
    """The full notice, with this PC's settings in it."""
    who = conf.controller or "Not set on this computer: ask the lab administrator."
    lines = [
        "PRIMERS OS PRIVACY NOTICE",
        f"Version {NOTICE_VERSION}",
        "",
        _wrap("This notice explains what PRIMERS OS records on this computer, why, for how long, "
              "who can see it, and your rights under the Nigeria Data Protection Act 2023 (NDPA)."),
        "",
        "WHO IS RESPONSIBLE",
        _wrap("The institution that runs this computer decides how it is used and is responsible "
              "(the data controller) for what is recorded on it:"),
        f"  Institution: {who}",
        f"  Contact: {conf.contact or 'ask the lab administrator'}",
        f"  Data protection officer: {conf.dpo or 'ask the lab administrator'}",
        _wrap("PRIMERS OS is made by Primers Group (primersgroup.ng). PRIMERS OS does not send "
              "anything it records on this computer to Primers."),
        "",
        "WHAT IS RECORDED, AND WHY",
        _wrap("1. Exam log, only while an exam is running in Exam Mode: when the exam started and "
              "stopped, which account signed in and when, the addresses of the exam pages that "
              "were opened, pages and connections that were blocked, and when the candidate "
              "finished. Why: to run exams fairly and to settle questions about what happened "
              "during one. Lawful basis: the institution's task of running and supervising exams "
              "(public interest or legitimate interests; the institution confirms which). "
              f"Kept for {conf.exam_log_days} days, then deleted automatically.", "   ")[3:],
        _wrap("2. Lab control log, only on PCs linked to an invigilator's PC (primers-fleet): which "
              "PC sent which command (start, stop, status, collecting the exam logs), from which "
              "network address, and when. Why: security, and to show who controlled an exam. "
              f"Kept for {conf.fleet_log_days} days.", "   ")[3:],
        _wrap("3. The system's technical log (the journal), which also holds the exam events and "
              f"sign-in times: kept for at most {conf.exam_log_days} days (up to "
              f"{JOURNAL_FILE_DAYS} more while its current file is in use).", "   ")[3:],
        _wrap("4. On the shared lab account (Lab Mode), everything saved in the account, browser "
              "history included, is deleted at every sign-in, sign-out and restart.", "   ")[3:],
        _wrap("5. Primers ID, only if you sign in with it (primers-id): your Primers ID number, name, "
              "email and a sign-in token, kept in your own account folder (readable by you only) "
              "until you sign out. The Primers ID service itself is run by Primers Group under its "
              "own privacy notice.", "   ")[3:],
        _wrap("6. Your own files and settings stay in your account folder.", "   ")[3:],
        "",
        "WHAT IS NOT RECORDED",
        _wrap("No keystrokes, screenshots, screen recordings, camera or microphone, and not the "
              "answers you give in an exam (they go to the exam site, which your institution "
              "runs). No advertising and no usage tracking: Firefox's telemetry is turned off."),
        "",
        "WHO CAN SEE IT",
        _wrap("The exam and lab control logs: this computer's administrators, and the invigilator, "
              "who may copy every lab PC's exam log at the end of an exam. The institution shares "
              "them outside itself only when the law requires it."),
        "",
        "CONNECTIONS TO THE INTERNET",
        _wrap("Software updates come from Ubuntu's servers, which see this computer's network "
              "address. Websites you visit see what any website sees. During an exam only the "
              "exam site can be reached."),
        "",
        "YOUR RIGHTS",
        _wrap("Under the NDPA you can ask the institution (contact above) to tell you what it holds "
              "about you and give you a copy, to correct it, to delete it, to restrict or object "
              "to its use, to give it to you in a portable form, and to stop using it where you "
              "consented. You can complain to the Nigeria Data Protection Commission (NDPC, "
              "ndpc.gov.ng). For a student under 18, a parent or guardian can act for them."),
        "",
        "FOR ADMINISTRATORS",
        _wrap("sudo primers-privacy export DIR copies the logs (JSON and CSV, with checksums) for a "
              "request; sudo primers-privacy retention --days N changes how long they are kept; "
              "sudo primers-privacy controller sets the contact details above. Full text: "
              f"{DOC}."),
    ]
    return "\n".join(lines) + "\n"


def short_notice(conf: PrivacyConfig) -> str:
    """The layer shown with the shared-computer notice at every lab sign-in."""
    return ("Privacy: outside exams, this computer records only sign-in times and technical "
            "events. During an exam it keeps an exam log (pages opened, pages blocked, sign-in "
            f"and finish times) for {conf.exam_log_days} days. Full notice and your rights: "
            "right-click the desktop › System › Privacy notice.")


def acknowledged_path() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "primers", "privacy-notice")


def acknowledged(path: Optional[str] = None) -> bool:
    try:
        with open(path or acknowledged_path(), encoding="utf-8") as f:
            return f.read().strip() == NOTICE_VERSION
    except OSError:
        return False


def acknowledge(path: Optional[str] = None) -> None:
    path = path or acknowledged_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    _atomic_write(path, NOTICE_VERSION + "\n", 0o600)


def live_session(cmdline: str = "/proc/cmdline") -> bool:
    try:
        with open(cmdline, encoding="ascii", errors="replace") as f:
            return "boot=casper" in f.read().split()
    except OSError:
        return False


# ------------------------------------------------------------------ #
#  Retention
# ------------------------------------------------------------------ #

def exam_running(exam_conf: str = EXAM_CONF) -> bool:
    return os.path.exists(exam_conf)


def apply_retention(conf: PrivacyConfig, now: Optional[datetime] = None, exam_log_path: str = EXAM_LOG,
                    fleet_log_path: str = FLEET_LOG, exam_conf: str = EXAM_CONF) -> Dict[str, Dict]:
    """Remove the records older than the retention times. The exam log is
    left alone while an exam is running (its records are the exam's
    evidence); the next run catches up."""
    now = now or datetime.now(timezone.utc)
    out: Dict[str, Dict] = {}
    for name, path, days in (("exam", exam_log_path, conf.exam_log_days),
                             ("fleet", fleet_log_path, conf.fleet_log_days)):
        if name == "exam" and exam_running(exam_conf):
            out[name] = {"skipped": "an exam is running", "days": days}
            continue
        kept, removed = logfiles.prune(path, now - timedelta(days=days))
        out[name] = {"kept": kept, "removed": removed, "days": days}
    return out


def write_journald(days: int, path: str = JOURNALD_DROPIN) -> bool:
    """Write the journal's limit; True if it changed (journald needs a restart)."""
    text = journald_dropin(days)
    with contextlib.suppress(OSError):
        with open(path, encoding="utf-8") as f:
            if f.read() == text:
                return False
    _atomic_write(path, text, 0o644)
    return True


def journald_days(path: str = JOURNALD_DROPIN) -> Optional[int]:
    with contextlib.suppress(OSError, ValueError):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("MaxRetentionSec="):
                    return int(line.split("=", 1)[1].strip().removesuffix("day"))
    return None


# ------------------------------------------------------------------ #
#  What is kept, and exporting it
# ------------------------------------------------------------------ #

def _lines(path: str) -> List[bytes]:
    try:
        with open(path, "rb") as f:
            return [line for line in f.read().split(b"\n") if line.strip()]
    except FileNotFoundError:
        return []


def log_summary(path: str) -> Dict:
    times = [t for t in (logfiles.record_time(line) for line in _lines(path)) if t]
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return {"path": path, "records": len(times), "bytes": size,
            "oldest": min(times).isoformat() if times else None,
            "newest": max(times).isoformat() if times else None}


def _cell(value) -> str:
    """A CSV cell a spreadsheet won't run as a formula."""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def _records(path: str, since: Optional[datetime]) -> List[Dict]:
    out = []
    for line in _lines(path):
        try:
            data = json.loads(line)
        except ValueError:
            continue                        # a line torn by a power cut
        if not isinstance(data, dict):
            continue
        when = logfiles.parse_time(data.get("time", ""))
        if since is None or (when is not None and when >= since):
            out.append(data)
    return out


def export(dest: str, conf: PrivacyConfig, since: Optional[datetime] = None,
           which: Sequence[str] = ("exam", "fleet"), exam_log_path: str = EXAM_LOG,
           fleet_log_path: str = FLEET_LOG, owner: Optional[Tuple[int, int]] = None) -> List[str]:
    """Copy the logs into a new folder ``dest`` (readable by its owner only):
    each log as JSON lines and CSV, a README.txt and SHA256SUMS."""
    if os.path.lexists(dest) and (not os.path.isdir(dest) or os.path.islink(dest) or os.listdir(dest)):
        raise PrivacyError(f"{dest} already exists: choose a new folder")
    os.makedirs(dest, mode=0o700, exist_ok=True)
    os.chmod(dest, 0o700)
    files: Dict[str, bytes] = {}
    columns = {"exam": ["time", "user", "uid", "pid", "boot", "message"]}
    counts = {}
    for name, path in (("exam", exam_log_path), ("fleet", fleet_log_path)):
        if name not in which:
            continue
        records = _records(path, since)
        counts[name] = len(records)
        files[f"{name}.jsonl"] = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n"
                                         for r in records).encode("utf-8")
        cols = columns.get(name) or ["time", "event"] + sorted({k for r in records for k in r} - {"time", "event"})
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow(cols)
        for r in records:
            w.writerow([_cell(r.get(c, "") if not isinstance(r.get(c), (dict, list)) else json.dumps(r[c]))
                        for c in cols])
        files[f"{name}.csv"] = buf.getvalue().encode("utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    readme = [
        "PRIMERS OS log export",
        f"Exported {stamp} from {socket.gethostname()}"
        + (f", records since {since.strftime('%Y-%m-%d %H:%M UTC')}" if since else ", every record kept") + ".",
        "",
    ]
    for name in counts:
        what = {"exam": "the exam log", "fleet": "the lab control (primers-fleet) log"}[name]
        days = conf.exam_log_days if name == "exam" else conf.fleet_log_days
        readme.append(f"{name}.jsonl, {name}.csv: {what}, {counts[name]} records "
                      f"(this PC keeps them for {days} days).")
    readme += ["", "Check the copies: sha256sum -c SHA256SUMS", "",
               _wrap("These files are personal data under the Nigeria Data Protection Act 2023: keep "
                     "them where only the people who need them can read them, and delete them when "
                     "they are no longer needed."), ""]
    files["README.txt"] = "\n".join(readme).encode("utf-8")
    sums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in sorted(files.items()))
    files["SHA256SUMS"] = sums.encode("ascii")
    written = []
    for name, data in files.items():
        path = os.path.join(dest, name)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        written.append(path)
    if owner:
        for path in [dest] + written:
            os.chown(path, *owner)
    return sorted(written)


def status(conf: PrivacyConfig, exam_log_path: str = EXAM_LOG, fleet_log_path: str = FLEET_LOG,
           dropin: str = JOURNALD_DROPIN) -> Dict:
    return {"notice_version": NOTICE_VERSION, "controller": conf.controller, "contact": conf.contact,
            "dpo": conf.dpo, "exam_log_days": conf.exam_log_days, "fleet_log_days": conf.fleet_log_days,
            "journal_days": journald_days(dropin), "exam_log": log_summary(exam_log_path),
            "fleet_log": log_summary(fleet_log_path)}
