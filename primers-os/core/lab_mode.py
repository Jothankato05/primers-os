"""
PRIMERS OS — Lab Mode: one shared account for computer labs.

A lab machine gets a passwordless, non-admin account (default ``lab``)
whose home folder is rebuilt from a template whenever someone signs in or
out, and at every boot. The next student always starts clean: no files,
browser history, saved passwords or Wi-Fi keys from the person before.

How it is wired (``primers-lab enable`` sets all of this up):

* LightDM runs ``primers-lab hook session-setup`` before and
  ``primers-lab hook session-cleanup`` after every desktop session.
* ``primers-lab-reset.service`` runs ``primers-lab hook boot`` before
  logins are allowed, so a power cut can't leave a session behind.
* The account's password is locked, so it can't be used on a text console,
  over SSH or with ``su``. The boot hook puts it in the ``nopasswdlogin``
  group (LightDM's PAM file lets those users in without a password) only
  once LightDM is about to start with the wipe hooks loaded: LightDM reads
  its configuration only when it starts, so until the next restart the lab
  account can't sign in at all, and it is never usable without the wipe.

Everything that deletes files is guarded. The account must be the one Lab
Mode created (name and UID are recorded in /etc/primers/lab.conf), an
ordinary user (UID 1000-59999) whose home is /home/<name>, and in no admin
group. If a check fails nothing is deleted and the lab account is not let
in (fail closed), so one student's files never reach the next.
"""

import contextlib
import fcntl
import grp
import os
import pwd
import re
import signal
import stat
import subprocess
import syslog
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

DEFAULT_USER = "lab"
GECOS = "Shared lab account (files are deleted at sign-out)"
PASSWORDLESS_GROUP = "nopasswdlogin"
UNIT = "primers-lab-reset.service"
UID_MIN, UID_MAX = 1000, 59999
NAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")

# An account in any of these groups is somebody's real (admin) account:
# Lab Mode never wipes it.
PRIVILEGED_GROUPS = frozenset({
    "root", "sudo", "admin", "adm", "wheel", "lpadmin", "netdev", "docker",
    "lxd", "libvirt", "kvm", "disk", "shadow", "systemd-journal",
})

LIGHTDM_SNIPPET = """\
# Written by primers-lab: Lab Mode is on. Turn it off with: sudo primers-lab disable
[Seat:*]
session-setup-script=/usr/bin/primers-lab hook session-setup
session-cleanup-script=/usr/bin/primers-lab hook session-cleanup
"""

HOOK_EVENTS = ("session-setup", "session-cleanup", "boot")


class LabError(Exception):
    """Lab Mode refused or failed to do something; the message says why."""


@dataclass
class Paths:
    conf: str = "/etc/primers/lab.conf"
    state: str = "/var/lib/primers/lab"
    lightdm: str = "/etc/lightdm/lightdm.conf.d/60-primers-lab.conf"
    home_root: str = "/home"
    default_template: str = "/etc/skel"
    lab_template: str = "/etc/primers/lab-skel"
    tmp_dirs: Sequence[str] = ("/tmp", "/var/tmp", "/dev/shm")
    nm_connections: str = "/etc/NetworkManager/system-connections"
    crontabs: str = "/var/spool/cron/crontabs"
    linger: str = "/var/lib/systemd/linger"
    mail: str = "/var/mail"
    proc: str = "/proc"
    mountinfo: str = "/proc/self/mountinfo"
    lock: str = "/run/primers-lab.lock"


@dataclass
class LabConfig:
    user: str
    uid: int
    template: str


@dataclass
class Account:
    name: str
    uid: int
    gid: int
    home: str
    gecos: str = ""
    groups: List[str] = field(default_factory=list)


# ------------------------------------------------------------------ #
#  Configuration
# ------------------------------------------------------------------ #

def read_config(path: str) -> Optional[LabConfig]:
    """None when Lab Mode is off; LabError when the file is damaged."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return None
    values: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    try:
        conf = LabConfig(values["LAB_USER"], int(values["LAB_UID"]),
                         values.get("TEMPLATE", "/etc/skel"))
    except (KeyError, ValueError):
        raise LabError(f"{path} is damaged (needs LAB_USER and LAB_UID)")
    if not NAME_RE.match(conf.user):
        raise LabError(f"{path} names an invalid account: {conf.user!r}")
    return conf


def sync_dir(path: str) -> None:
    """fsync a directory, so a rename or unlink in it survives a power cut."""
    with contextlib.suppress(OSError):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _atomic_write(path: str, text: str, mode: int = 0o644) -> None:
    """Replace a file so that after a power cut it holds either the old or
    the new text, never a mix or nothing: written, fsync'd, renamed over the
    old one, directory fsync'd."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    sync_dir(os.path.dirname(path))


def write_config(path: str, conf: LabConfig) -> None:
    _atomic_write(path, (
        "# Lab Mode, written by primers-lab. Don't edit: use primers-lab enable/disable.\n"
        f"LAB_USER={conf.user}\nLAB_UID={conf.uid}\nTEMPLATE={conf.template}\n"))


# ------------------------------------------------------------------ #
#  Accounts and safety checks
# ------------------------------------------------------------------ #

def lookup_account(name: str) -> Optional[Account]:
    try:
        pw = pwd.getpwnam(name)
    except KeyError:
        return None
    groups = []
    for gid in os.getgrouplist(name, pw.pw_gid):
        try:
            groups.append(grp.getgrgid(gid).gr_name)
        except KeyError:
            groups.append(str(gid))
    return Account(pw.pw_name, pw.pw_uid, pw.pw_gid, pw.pw_dir, pw.pw_gecos, groups)


def account_problems(acct: Account, conf: Optional[LabConfig], home_root: str) -> List[str]:
    """Reasons this account must NOT be wiped (empty list = safe)."""
    problems = []
    if not NAME_RE.match(acct.name):
        problems.append(f"{acct.name!r} is not a valid account name")
    if not UID_MIN <= acct.uid <= UID_MAX:
        problems.append(f"UID {acct.uid} is not an ordinary user's UID ({UID_MIN}-{UID_MAX})")
    if conf is not None and acct.uid != conf.uid:
        problems.append(f"UID is {acct.uid} but Lab Mode was set up for UID {conf.uid}")
    expected = os.path.join(home_root, acct.name)
    if os.path.normpath(acct.home) != expected:
        problems.append(f"home folder is {acct.home}, expected {expected}")
    admin = sorted(set(acct.groups) & PRIVILEGED_GROUPS)
    if admin:
        problems.append("member of admin groups: " + ", ".join(admin))
    if os.path.realpath(home_root) != os.path.abspath(home_root):
        problems.append(f"{home_root} is (or is inside) a symbolic link")
    if os.path.lexists(expected) and (os.path.islink(expected) or not os.path.isdir(expected)):
        problems.append(f"{expected} is not a plain folder")
    return problems


def pids_of(uid: int, proc: str = "/proc") -> List[int]:
    """Live processes running as `uid` (real, effective, saved or fs UID)."""
    pids = []
    for entry in os.listdir(proc):
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc, entry, "status"), encoding="utf-8") as f:
                status = f.read()
        except OSError:
            continue
        uids, state = [], ""
        for line in status.splitlines():
            if line.startswith("Uid:"):
                uids = line.split()[1:]
            elif line.startswith("State:"):
                state = line.split()[1] if len(line.split()) > 1 else ""
        if state not in ("Z", "X") and str(uid) in uids:
            pids.append(int(entry))
    return pids


def mounts_under(path: str, mountinfo: str) -> List[str]:
    """Mount points strictly inside `path`, deepest first."""
    prefix = path.rstrip("/") + "/"
    found = []
    try:
        with open(mountinfo, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) > 4:
                    point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), parts[4])
                    if point.startswith(prefix):
                        found.append(point)
    except OSError:
        pass
    return sorted(set(found), key=lambda p: p.count("/"), reverse=True)


def _connection_only_for(text: str, user: str) -> bool:
    """True if a NetworkManager keyfile is private to `user` (and only them)."""
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
        elif section == "connection" and line.startswith("permissions="):
            items = [i for i in line.split("=", 1)[1].split(";") if i.strip()]
            owners = [i.split(":")[1] if i.count(":") >= 1 and i.startswith("user:") else None
                      for i in items]
            return bool(owners) and all(o == user for o in owners)
    return False


def copy_template(src: str, dst_fd: int, uid: int, gid: int) -> None:
    """Copy the template tree into the open directory `dst_fd`.

    Works relative to directory file descriptors and never follows symbolic
    links, so nothing outside the new home can be written to or chowned.
    """
    for entry in os.scandir(src):
        st = entry.stat(follow_symlinks=False)
        mode = stat.S_IMODE(st.st_mode) & 0o777
        if entry.is_symlink():
            os.symlink(os.readlink(entry.path), entry.name, dir_fd=dst_fd)
            os.chown(entry.name, uid, gid, dir_fd=dst_fd, follow_symlinks=False)
        elif entry.is_dir(follow_symlinks=False):
            os.mkdir(entry.name, 0o700, dir_fd=dst_fd)
            sub = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dst_fd)
            try:
                copy_template(entry.path, sub, uid, gid)
                os.fchown(sub, uid, gid)
                os.fchmod(sub, mode)
            finally:
                os.close(sub)
        elif entry.is_file(follow_symlinks=False):
            src_fd = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                out = os.open(entry.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                              0o600, dir_fd=dst_fd)
                try:
                    while True:
                        chunk = os.read(src_fd, 1 << 20)
                        if not chunk:
                            break
                        view = memoryview(chunk)
                        while view:
                            view = view[os.write(out, view):]
                    os.fchown(out, uid, gid)
                    os.fchmod(out, mode)
                finally:
                    os.close(out)
            finally:
                os.close(src_fd)
        # sockets, FIFOs and device files are not copied


# ------------------------------------------------------------------ #
#  Lab Mode
# ------------------------------------------------------------------ #

def _default_run(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=300)


def _default_log(message: str) -> None:
    syslog.openlog("primers-lab", syslog.LOG_PID, syslog.LOG_AUTH)
    syslog.syslog(syslog.LOG_NOTICE, message)


class LabMode:
    def __init__(self, paths: Optional[Paths] = None,
                 run: Callable[[Sequence[str]], subprocess.CompletedProcess] = _default_run,
                 lookup: Callable[[str], Optional[Account]] = lookup_account,
                 log: Callable[[str], None] = _default_log,
                 kill: Callable[[int, int], None] = os.kill,
                 sleep: Callable[[float], None] = time.sleep,
                 trusted_uid: int = 0):
        self.paths = paths or Paths()
        self.run = run
        self.lookup = lookup
        self.log = log
        self.kill = kill
        self.sleep = sleep
        self.trusted_uid = trusted_uid   # owner required for the home template

    # ---------------- status (works for any user) ----------------

    def config(self) -> Optional[LabConfig]:
        return read_config(self.paths.conf)

    def status(self) -> Dict:
        try:
            conf = self.config()
        except LabError as e:
            return {"enabled": None, "error": str(e)}
        if conf is None:
            return {"enabled": False}
        last = None
        with contextlib.suppress(OSError):
            with open(os.path.join(self.paths.state, "last-reset"), encoding="utf-8") as f:
                last = f.read().strip() or None
        acct = self.lookup(conf.user)
        return {"enabled": True, "user": conf.user, "template": conf.template,
                "last_reset": last, "account_exists": acct is not None,
                "login_hooks": os.path.exists(self.paths.lightdm),
                "sign_in_ready": acct is not None and PASSWORDLESS_GROUP in acct.groups}

    def is_lab_session(self, user: Optional[str] = None) -> bool:
        try:
            conf = self.config()
        except LabError:
            return False
        if conf is None:
            return False
        if user is None:
            try:
                user = pwd.getpwuid(os.getuid()).pw_name
            except KeyError:
                return False
        return user == conf.user

    # ---------------- helpers ----------------

    def _checked(self, argv: Sequence[str]) -> None:
        result = self.run(argv)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise LabError(f"'{' '.join(argv)}' failed" + (f": {detail}" if detail else ""))

    @contextlib.contextmanager
    def _locked(self):
        os.makedirs(os.path.dirname(self.paths.lock), exist_ok=True)
        fd = os.open(self.paths.lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _check_template(self, template: str) -> None:
        try:
            st = os.lstat(template)
        except FileNotFoundError:
            raise LabError(f"home template {template} does not exist")
        if not stat.S_ISDIR(st.st_mode):
            raise LabError(f"home template {template} is not a folder")
        if st.st_uid != self.trusted_uid or st.st_mode & 0o022:
            raise LabError(f"home template {template} must be owned by root and "
                           "not writable by other users")

    def _home(self, acct: Account) -> str:
        return os.path.join(self.paths.home_root, acct.name)

    def _guard(self, acct: Optional[Account], conf: Optional[LabConfig]) -> Account:
        if acct is None:
            raise LabError(f"the lab account '{conf.user if conf else '?'}' does not exist")
        problems = account_problems(acct, conf, self.paths.home_root)
        if problems:
            raise LabError(f"won't touch account '{acct.name}': " + "; ".join(problems))
        return acct

    def _stop_user(self, acct: Account) -> None:
        """End every process of the lab account (its session is over)."""
        self.run(["systemctl", "stop", f"user@{acct.uid}.service"])
        for _ in range(50):
            pids = pids_of(acct.uid, self.paths.proc)
            if not pids:
                return
            for pid in pids:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    self.kill(pid, signal.SIGKILL)
            self.sleep(0.1)
        if pids_of(acct.uid, self.paths.proc):
            raise LabError(f"processes of '{acct.name}' are still running")

    def _empty(self, folder: str) -> List[str]:
        """Delete everything inside `folder`; return what is left."""
        for point in mounts_under(folder, self.paths.mountinfo):
            self.run(["umount", "--lazy", "--", point])
        self.run(["find", folder, "-mindepth", "1", "-maxdepth", "1",
                  "-exec", "rm", "-rf", "--one-file-system", "--", "{}", "+"])
        return sorted(os.listdir(folder))

    def _reset_home(self, acct: Account, template: str) -> None:
        home = self._home(acct)
        if not os.path.lexists(home):
            os.mkdir(home, 0o700)
        fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            left = self._empty(home)
            if left:
                raise LabError(f"could not empty {home}; still there: {', '.join(left[:5])}")
            copy_template(template, fd, acct.uid, acct.gid)
            os.fchown(fd, acct.uid, acct.gid)
            os.fchmod(fd, 0o700)
        finally:
            os.close(fd)

    def _clean_elsewhere(self, acct: Account) -> None:
        """What the account may have left outside its home folder."""
        for folder in self.paths.tmp_dirs:
            if os.path.isdir(folder) and not os.path.islink(folder):
                self.run(["find", folder, "-mindepth", "1", "-maxdepth", "1", "-uid", str(acct.uid),
                          "-exec", "rm", "-rf", "--one-file-system", "--", "{}", "+"])
        for folder in (self.paths.crontabs, self.paths.linger):
            with contextlib.suppress(FileNotFoundError):
                os.unlink(os.path.join(folder, acct.name))
        with contextlib.suppress(OSError):
            fd = os.open(os.path.join(self.paths.mail, acct.name),
                         os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
            os.close(fd)
        removed = False
        with contextlib.suppress(FileNotFoundError):
            for entry in os.scandir(self.paths.nm_connections):
                if not entry.is_file(follow_symlinks=False):
                    continue
                try:
                    with open(entry.path, encoding="utf-8", errors="replace") as f:
                        private = _connection_only_for(f.read(), acct.name)
                except OSError:
                    continue
                if private:
                    os.unlink(entry.path)
                    removed = True
        if removed:
            self.run(["nmcli", "connection", "reload"])

    def _passwordless(self, acct: Account, allow: bool) -> None:
        """Let the account sign in from LightDM without a password, or not."""
        if allow:
            self.run(["groupadd", "--system", "-f", PASSWORDLESS_GROUP])
            self._checked(["usermod", "--append", "--groups", PASSWORDLESS_GROUP, acct.name])
        elif PASSWORDLESS_GROUP in acct.groups:
            self.run(["gpasswd", "--delete", acct.name, PASSWORDLESS_GROUP])

    def _record(self, reason: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        _atomic_write(os.path.join(self.paths.state, "last-reset"), f"{stamp} ({reason})\n")

    def _template(self, conf: LabConfig) -> str:
        self._check_template(conf.template)
        return conf.template

    # ---------------- actions ----------------

    def reset(self, reason: str = "manual") -> Account:
        conf = self.config()
        if conf is None:
            raise LabError("Lab Mode is off")
        with self._locked():
            acct = self._guard(self.lookup(conf.user), conf)
            template = self._template(conf)
            self._stop_user(acct)
            self._reset_home(acct, template)
            self._clean_elsewhere(acct)
            self._record(reason)
        self.log(f"reset lab account '{acct.name}' ({reason})")
        return acct

    def enable(self, user: str = DEFAULT_USER, template: Optional[str] = None) -> LabConfig:
        if not NAME_RE.match(user):
            raise LabError(f"{user!r} is not a valid account name (lowercase letters, digits, - and _)")
        current = self.config()
        if current and current.user != user:
            raise LabError(f"Lab Mode is already on for account '{current.user}'. "
                           "Turn it off first: sudo primers-lab disable")
        if template is None:
            template = current.template if current else (
                self.paths.lab_template if os.path.isdir(self.paths.lab_template)
                else self.paths.default_template)
        template = os.path.abspath(template)
        self._check_template(template)

        acct = self.lookup(user)
        ours = acct is not None and (acct.gecos == GECOS or (current is not None and current.uid == acct.uid))
        if acct is not None and not ours:
            raise LabError(
                f"an account called '{user}' already exists. Lab Mode deletes everything in its "
                "account at every sign-out, so it only uses an account it created itself. "
                "Pick another name: sudo primers-lab enable --user NAME")
        if acct is None:
            self._checked(["useradd", "--comment", GECOS, "--shell", "/bin/bash", "--user-group",
                           "--no-create-home", "--home-dir", os.path.join(self.paths.home_root, user),
                           user])
            acct = self.lookup(user)
        acct = self._guard(acct, None)

        self._checked(["usermod", "--lock", user])
        conf = LabConfig(user, acct.uid, template)
        write_config(self.paths.conf, conf)
        _atomic_write(self.paths.lightdm, LIGHTDM_SNIPPET)
        result = self.run(["systemctl", "enable", UNIT])
        if result.returncode != 0:
            self.log(f"could not enable {UNIT}: {(result.stderr or '').strip()}")
        self.reset("enabled")
        self.log(f"Lab Mode enabled for '{user}' (template {template})")
        return conf

    def disable(self) -> List[str]:
        """Turn Lab Mode off and delete the lab account. Returns warnings."""
        conf = self.config()
        if conf is None:
            raise LabError("Lab Mode is already off")
        warnings: List[str] = []
        with self._locked():
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.paths.lightdm)
            self.run(["systemctl", "disable", UNIT])
            acct = self.lookup(conf.user)
            if acct is not None:
                problems = account_problems(acct, conf, self.paths.home_root)
                if problems:
                    # Not ours any more: delete nothing, but make sure it can't be
                    # used without a password.
                    self.run(["gpasswd", "--delete", acct.name, PASSWORDLESS_GROUP])
                    warnings.append(f"left account '{acct.name}' in place (" + "; ".join(problems) +
                                    ") and removed its passwordless sign-in")
                else:
                    self._stop_user(acct)
                    self._clean_elsewhere(acct)
                    self._checked(["userdel", acct.name])
                    home = self._home(acct)
                    if os.path.isdir(home) and not os.path.islink(home):
                        left = self._empty(home)
                        if left:
                            warnings.append(f"could not delete everything in {home}")
                        else:
                            with contextlib.suppress(OSError):
                                os.rmdir(home)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(os.path.join(self.paths.state, "last-reset"))
            os.unlink(self.paths.conf)
        self.log(f"Lab Mode disabled (account '{conf.user}')")
        return warnings

    def hook(self, event: str, user: Optional[str]) -> int:
        """Entry point for LightDM and systemd. Returns the exit status.

        A failed reset before a lab session returns 1, which makes LightDM
        refuse that session: better no login than someone else's files.
        Other users are never affected.
        """
        if event not in HOOK_EVENTS:
            raise LabError(f"unknown hook {event!r}")
        try:
            conf = self.config()
        except LabError as e:
            self.log(str(e))
            if event == "session-setup" and user:
                acct = self.lookup(user)
                if acct is not None and acct.gecos == GECOS:
                    return 1
            return 0
        if conf is None:
            return 0
        if event != "boot" and user != conf.user:
            return 0
        try:
            acct = self.reset(event)
            if event == "boot":
                # LightDM starts after this and loads the wipe hooks; only now
                # may the lab account sign in without a password.
                ready = os.path.exists(self.paths.lightdm)
                self._passwordless(acct, ready)
                if not ready:
                    self.log(f"{self.paths.lightdm} is missing: the lab account can't sign in "
                             "until Lab Mode is enabled again")
            return 0
        except (LabError, OSError) as e:
            self.log(f"{event}: lab account not reset: {e}")
            if event == "boot":
                acct = self.lookup(conf.user)
                if acct is not None and not account_problems(acct, conf, self.paths.home_root):
                    with contextlib.suppress(LabError, OSError):
                        self._passwordless(acct, False)
            return 1 if event in ("session-setup", "boot") else 0
