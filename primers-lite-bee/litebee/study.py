"""
Study Mode support: while a PRIMERS OS study session runs, distracting sites
are paused. The session itself is managed by the PRIMERS Brain (`study 25`)
or `primers-study`; this module only reads it.

Session file: $XDG_STATE_HOME/primers/study ("started=", "until=", "minutes=").
Extra sites: ~/.config/primers/study-sites, one domain per line; a line
"-example.com" allows a site the built-in list pauses.
"""

import os
import time
from typing import Iterable, Optional, Set, Tuple
from urllib.parse import urlsplit

# Social media, video, games and betting: the usual study killers.
DEFAULT_SITES = frozenset({
    "facebook.com", "fb.com", "messenger.com", "instagram.com", "threads.net", "tiktok.com",
    "x.com", "twitter.com", "snapchat.com", "pinterest.com", "tumblr.com", "reddit.com",
    "9gag.com", "discord.com", "youtube.com", "youtu.be", "netflix.com", "primevideo.com",
    "showmax.com", "twitch.tv", "kick.com", "roblox.com", "poki.com", "crazygames.com",
    "miniclip.com", "bet9ja.com", "sportybet.com", "betking.com", "1xbet.com", "nairabet.com",
})


def _state_path() -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "primers", "study")


def _sites_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "primers", "study-sites")


def session_until(path: Optional[str] = None, now: Optional[float] = None) -> Optional[int]:
    """End time (unix) of the running study session, or None."""
    try:
        with open(path or _state_path(), encoding="utf-8") as f:
            text = f.read(4096)
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("until="):
            try:
                until = int(line[6:].strip())
            except ValueError:
                return None
            return until if until > (time.time() if now is None else now) else None
    return None


def parse_sites(lines: Iterable[str], base: Iterable[str] = DEFAULT_SITES) -> Set[str]:
    sites = set(base)
    for raw in lines:
        line = raw.split("#", 1)[0].strip().lower()
        if not line:
            continue
        if line.startswith("-"):
            sites.discard(line[1:].strip().lstrip("."))
        else:
            sites.add(line.lstrip("."))
    return sites


def load_sites(path: Optional[str] = None) -> Set[str]:
    try:
        with open(path or _sites_path(), encoding="utf-8") as f:
            return parse_sites(f)
    except OSError:
        return set(DEFAULT_SITES)


def paused_site(uri: str, sites: Iterable[str]) -> Optional[str]:
    """The listed site `uri` belongs to (e.g. 'youtube.com'), or None."""
    try:
        parts = urlsplit(uri or "")
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").rstrip(".").lower()
    for site in sites:
        if host == site or host.endswith("." + site):
            return site
    return None


class StudyGate:
    """What Lite Bee asks on every navigation. Cheap: re-reads files only when they change."""

    def __init__(self, state: Optional[str] = None, sites: Optional[str] = None):
        self.state = state or _state_path()
        self.sites_file = sites or _sites_path()
        self._sites: Tuple[Optional[float], Set[str]] = (None, set(DEFAULT_SITES))

    def _current_sites(self) -> Set[str]:
        try:
            mtime = os.stat(self.sites_file).st_mtime
        except OSError:
            mtime = None
        if mtime != self._sites[0]:
            self._sites = (mtime, load_sites(self.sites_file) if mtime is not None else set(DEFAULT_SITES))
        return self._sites[1]

    def until(self) -> Optional[int]:
        return session_until(self.state)

    def check(self, uri: str) -> Optional[str]:
        """Site to pause for `uri` right now, or None."""
        if not uri.startswith(("http:", "https:")) or self.until() is None:
            return None
        return paused_site(uri, self._current_sites())
