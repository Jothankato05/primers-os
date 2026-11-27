"""
Content-blocking rules in WebKit's content-extension (Safari) JSON format.

Rules are compiled by WebKit itself, so blocking happens inside the engine
before a single byte is requested - that is where the data savings come from.
"""

import json
from typing import Dict, List

from litebee.modes import Mode

# Well-known advertising and tracking hosts. Blocking these alone often cuts
# a news page's download size in half.
TRACKER_DOMAINS = [
    "doubleclick.net", "googlesyndication.com", "googleadservices.com", "google-analytics.com",
    "googletagmanager.com", "googletagservices.com", "adservice.google.com", "pagead2.googlesyndication.com",
    "connect.facebook.net", "facebook.com/tr", "analytics.twitter.com", "ads-twitter.com",
    "scorecardresearch.com", "quantserve.com", "adnxs.com", "criteo.com", "criteo.net",
    "taboola.com", "outbrain.com", "amazon-adsystem.com", "adsrvr.org", "rubiconproject.com",
    "pubmatic.com", "openx.net", "casalemedia.com", "moatads.com", "hotjar.com", "mixpanel.com",
    "segment.io", "segment.com", "branch.io", "appsflyer.com", "adcolony.com", "unityads.unity3d.com",
    "propellerads.com", "popads.net", "mgid.com", "revcontent.com", "zedo.com", "yieldmo.com",
    "chartbeat.com", "newrelic.com", "nr-data.net", "clarity.ms", "bat.bing.com", "tiktok.com/i18n/pixel",
    "analytics.tiktok.com", "snap.licdn.com", "px.ads.linkedin.com", "static.ads-twitter.com",
]


def _domain_pattern(domain: str) -> str:
    host, _, path = domain.partition("/")
    escaped = host.replace(".", "\\.")
    regex = f"^https?://([^/]+\\.)?{escaped}[:/]"
    if path:
        regex += path.replace(".", "\\.")
    return regex


def build_rules(mode: Mode) -> List[Dict]:
    rules: List[Dict] = []
    if mode.block_trackers:
        for domain in TRACKER_DOMAINS:
            rules.append({"trigger": {"url-filter": _domain_pattern(domain)}, "action": {"type": "block"}})

    types: List[str] = []
    if mode.block_fonts:
        types.append("font")
    if mode.block_media:
        types.append("media")
    if not mode.load_images:
        types.append("image")
    if types:
        rules.append({"trigger": {"url-filter": ".*", "resource-type": types}, "action": {"type": "block"}})

    third_party: List[str] = []
    if mode.block_third_party_scripts:
        third_party.append("script")
    if mode.block_third_party_images and mode.load_images:
        third_party.append("image")
    if third_party:
        rules.append({"trigger": {"url-filter": ".*", "resource-type": third_party,
                                  "load-type": ["third-party"]},
                      "action": {"type": "block"}})
    return rules


def build_json(mode: Mode) -> str:
    return json.dumps(build_rules(mode), separators=(",", ":"))


def filter_id(mode: Mode) -> str:
    """Stable identifier so compiled filters are cached on disk per mode/version."""
    import hashlib
    return f"litebee-{mode.key}-{hashlib.sha1(build_json(mode).encode()).hexdigest()[:10]}"
