"""
Browsing modes.

Lite Bee picks how much of the web to download based on the connection:

  full   Wi-Fi / Ethernet: everything, trackers and ads still blocked
  lite   LTE, 3G, phone hotspots, metered links: no autoplay video,
         no web fonts, no third-party media, lazy everything
  ultra  2G / EDGE / very slow links: text first - no images, media,
         fonts or third-party scripts; mobile pages requested

"auto" (the default) chooses one of these from the detected connection.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from litebee.network import ConnectionInfo


@dataclass(frozen=True)
class Mode:
    key: str
    label: str
    summary: str
    load_images: bool
    autoplay_media: bool
    block_fonts: bool
    block_media: bool
    block_third_party_scripts: bool
    block_third_party_images: bool
    javascript: bool
    webgl: bool
    mobile_pages: bool
    block_trackers: bool = True


MODES: Dict[str, Mode] = {
    "full": Mode(
        key="full", label="Full", summary="Everything loads. Ads and trackers are still blocked.",
        load_images=True, autoplay_media=True, block_fonts=False, block_media=False,
        block_third_party_scripts=False, block_third_party_images=False,
        javascript=True, webgl=True, mobile_pages=False,
    ),
    "lite": Mode(
        key="lite", label="Lite", summary="For LTE/3G and hotspots: no autoplay, web fonts or third-party media.",
        load_images=True, autoplay_media=False, block_fonts=True, block_media=True,
        block_third_party_scripts=False, block_third_party_images=True,
        javascript=True, webgl=False, mobile_pages=False,
    ),
    "ultra": Mode(
        key="ultra", label="Ultra", summary="For 2G/EDGE: text first, with no images, video, fonts or third-party scripts.",
        load_images=False, autoplay_media=False, block_fonts=True, block_media=True,
        block_third_party_scripts=True, block_third_party_images=True,
        javascript=True, webgl=False, mobile_pages=True,
    ),
}

PREFERENCES = ("auto", "full", "lite", "ultra")


def auto_mode_for(conn: Optional[ConnectionInfo]) -> Mode:
    """Pick the mode that suits a connection."""
    if conn is None or conn.kind in ("none", "unknown"):
        return MODES["lite"]
    if conn.kind == "mobile":
        if conn.generation in ("2g",):
            return MODES["ultra"]
        return MODES["lite"]
    if conn.metered:  # e.g. Wi-Fi from a phone hotspot
        return MODES["lite"]
    return MODES["full"]


def resolve(preference: str, conn: Optional[ConnectionInfo]) -> Mode:
    if preference in MODES:
        return MODES[preference]
    return auto_mode_for(conn)
