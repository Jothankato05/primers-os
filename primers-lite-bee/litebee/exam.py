"""
Exam Mode policy for Lite Bee's kiosk (``lite-bee --kiosk``).

The exam is configured by the PRIMERS OS administrator with
``sudo primers-exam start URL`` (see primers-os/core/exam_mode.py), which
writes /etc/primers/exam.conf. The kiosk reads it, shows only that site and
refuses to leave the listed servers. The firewall enforces the same list
for every program in the exam account; this is the browser's half.
"""

import ipaddress
import os
import re
from dataclasses import dataclass
from typing import FrozenSet, Optional
from urllib.parse import urlsplit

DEFAULT_CONF = "/etc/primers/exam.conf"
_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def conf_path() -> str:
    return os.environ.get("PRIMERS_EXAM_CONF") or DEFAULT_CONF


def _valid_host(host: str) -> bool:
    if not host or len(host) > 253:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return all(_LABEL.fullmatch(label) for label in host.split("."))


def host_of(uri: str) -> str:
    try:
        return (urlsplit(uri or "").hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


@dataclass(frozen=True)
class ExamPolicy:
    url: str
    hosts: FrozenSet[str]

    def allows(self, uri: str) -> bool:
        """May the exam browser show `uri`? Only the exam servers, over the web."""
        if uri in ("about:blank", ""):
            return True
        try:
            scheme = urlsplit(uri).scheme
        except ValueError:
            return False
        return scheme in ("http", "https") and host_of(uri) in self.hosts

    @property
    def main_host(self) -> str:
        return host_of(self.url)


def parse(text: str) -> Optional[ExamPolicy]:
    values = {}
    for line in (text or "").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    url = values.get("EXAM_URL", "")
    try:
        scheme = urlsplit(url).scheme
    except ValueError:
        return None
    hosts = frozenset(h.lower().rstrip(".") for h in values.get("ALLOW", "").split())
    if scheme not in ("http", "https") or not hosts or not all(_valid_host(h) for h in hosts):
        return None
    if host_of(url) not in hosts:
        return None
    return ExamPolicy(url, hosts)


def load(path: Optional[str] = None) -> Optional[ExamPolicy]:
    """The running exam, or None (no exam, or a damaged file)."""
    try:
        with open(path or conf_path(), encoding="utf-8") as f:
            return parse(f.read(65536))
    except OSError:
        return None
