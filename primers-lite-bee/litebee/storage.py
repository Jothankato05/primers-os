"""Where Lite Bee keeps its files, and crash-safe writes."""

import json
import os
from typing import Any

APP_DIR = "lite-bee"


def _xdg(var: str, fallback: str) -> str:
    return os.environ.get(var) or os.path.join(os.path.expanduser("~"), fallback)


def _ensure(path: str) -> str:
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def data_dir() -> str:
    override = os.environ.get("LITEBEE_HOME")
    if override:
        return _ensure(os.path.join(override, "data"))
    return _ensure(os.path.join(_xdg("XDG_DATA_HOME", ".local/share"), APP_DIR))


def cache_dir() -> str:
    override = os.environ.get("LITEBEE_HOME")
    if override:
        return _ensure(os.path.join(override, "cache"))
    return _ensure(os.path.join(_xdg("XDG_CACHE_HOME", ".cache"), APP_DIR))


def data_file(name: str) -> str:
    return os.path.join(data_dir(), name)


def saved_pages_dir() -> str:
    return _ensure(os.path.join(data_dir(), "saved"))


def write_private(path: str, text: str) -> None:
    """Write atomically (survives a power cut mid-write) with 0600 permissions."""
    tmp = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default
