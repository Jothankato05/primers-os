"""
PRIMERS OS — filesystem locations.

Resolution order for the per-user data directory (usage history, tasks,
GPA records, logs, user plugins):

1. ``$PRIMERS_DATA_DIR`` if set.
2. A development checkout (anything not installed under ``/usr``) keeps
   using ``<checkout>/logs`` so existing data stays where it was.
3. Installed system: ``$XDG_DATA_HOME/primers`` (``~/.local/share/primers``).

Logs follow ``$PRIMERS_LOG_DIR`` when set, otherwise live in the data dir.
Directories are created ``0700``: they hold command history and scheduled
shell commands, which other local users must not read or tamper with.
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_dir(path: str) -> str:
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def is_system_install() -> bool:
    return BASE_DIR.startswith("/usr/")


def data_dir() -> str:
    env = os.environ.get("PRIMERS_DATA_DIR")
    if env:
        return _ensure_dir(os.path.expanduser(env))
    if not is_system_install():
        return _ensure_dir(os.path.join(BASE_DIR, "logs"))
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return _ensure_dir(os.path.join(xdg, "primers"))


def log_dir() -> str:
    env = os.environ.get("PRIMERS_LOG_DIR")
    if env:
        return _ensure_dir(os.path.expanduser(env))
    return data_dir()


def data_file(name: str) -> str:
    return os.path.join(data_dir(), name)


def user_plugin_dir() -> str:
    return os.path.join(data_dir(), "plugins")


def write_private(path: str, text: str) -> None:
    """Atomically write a file readable only by its owner."""
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_private(path: str, line: str) -> None:
    """Append a line to a file created with owner-only permissions."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(line)
