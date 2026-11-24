"""Turn what the user typed into something to load."""

import ipaddress
import re
from urllib.parse import quote_plus, urlparse

# DuckDuckGo Lite: no JavaScript, tiny pages — ideal on 2G.
SEARCH_ENGINES = {
    "duckduckgo-lite": "https://lite.duckduckgo.com/lite/?q={query}",
    "duckduckgo": "https://duckduckgo.com/?q={query}",
    "google": "https://www.google.com/search?q={query}",
    "wikipedia": "https://en.m.wikipedia.org/w/index.php?search={query}",
}
DEFAULT_ENGINE = "duckduckgo-lite"

_ALLOWED_SCHEMES = ("http", "https", "file", "bee", "about")
_HOST_RE = re.compile(r"^([a-z0-9-]+\.)+[a-z]{2,63}(:\d{1,5})?(/.*)?$", re.IGNORECASE)


def search_url(query: str, engine: str = DEFAULT_ENGINE) -> str:
    template = SEARCH_ENGINES.get(engine, SEARCH_ENGINES[DEFAULT_ENGINE])
    return template.format(query=quote_plus(query.strip()))


def search_form(engine: str = DEFAULT_ENGINE):
    """(action URL, query parameter name) for an HTML search form."""
    template = SEARCH_ENGINES.get(engine, SEARCH_ENGINES[DEFAULT_ENGINE])
    base, _, query = template.partition("?")
    return base, query.split("=", 1)[0] or "q"


def _is_ip_or_localhost(host: str) -> bool:
    host = host.split(":")[0].strip("[]")
    if host == "localhost":
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def to_url(text: str, engine: str = DEFAULT_ENGINE) -> str:
    """'primersgroup.ng' → https://primersgroup.ng ; 'how to cook rice' → search."""
    text = (text or "").strip()
    if not text:
        return "bee:home"
    lowered = text.lower()
    scheme = lowered.split(":", 1)[0] if ":" in lowered else ""
    if scheme in _ALLOWED_SCHEMES and (lowered.startswith(scheme + "://") or scheme in ("bee", "about")):
        return text
    if scheme in ("javascript", "data", "vbscript"):
        return search_url(text, engine)  # never execute typed script URLs
    if " " not in text:
        host = text.split("/")[0]
        if _is_ip_or_localhost(host):
            return "http://" + text
        if _HOST_RE.match(text):
            return "https://" + text
    return search_url(text, engine)


def display_host(url: str) -> str:
    try:
        return urlparse(url).hostname or url
    except ValueError:
        return url


def is_secure(url: str) -> bool:
    return url.startswith(("https://", "bee:", "file://"))
