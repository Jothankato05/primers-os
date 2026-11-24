"""
Built-in pages served from the local "bee:" scheme. They load instantly and
cost zero data. Every dynamic value is HTML-escaped.
"""

import html
from typing import Iterable, Optional

from litebee import APP_NAME, VERSION
from litebee.modes import Mode
from litebee.network import ConnectionInfo

NAVY = "#0a1a27"
NAVY_2 = "#11263a"
GOLD = "#e6ad39"
CREAM = "#f4efe6"
MUTED = "#8aa0b4"

QUICK_LINKS = [
    ("Primers Group", "https://primersgroup.ng"),
    ("Velaji", "https://velaji.vercel.app"),
    ("Wikipedia", "https://en.m.wikipedia.org"),
    ("News (text)", "https://lite.cnn.com"),
    ("Weather (text)", "https://wttr.in/?format=4"),
]

_STYLE = f"""
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: {NAVY}; color: {CREAM};
       font: 16px/1.5 'Noto Sans', 'DejaVu Sans', sans-serif; }}
main {{ max-width: 720px; margin: 0 auto; padding: 48px 20px; }}
a {{ color: {GOLD}; }}
.logo {{ display: block; width: min(420px, 90%); margin: 0 auto 28px; }}
form {{ display: flex; gap: 8px; margin: 0 0 22px; }}
input[type=search] {{ flex: 1; padding: 14px 16px; border-radius: 12px; border: 1px solid #2a4257;
       background: {NAVY_2}; color: {CREAM}; font-size: 17px; }}
input[type=search]:focus {{ outline: 2px solid {GOLD}; border-color: transparent; }}
button {{ padding: 0 20px; border-radius: 12px; border: 0; background: {GOLD}; color: {NAVY};
       font-weight: 700; font-size: 16px; cursor: pointer; }}
.status {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 24px; }}
.pill {{ background: {NAVY_2}; border: 1px solid #22394d; border-radius: 999px; padding: 6px 14px;
        font-size: 14px; color: {MUTED}; }}
.pill b {{ color: {CREAM}; font-weight: 600; }}
.links {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }}
.links a {{ display: block; padding: 12px 14px; border-radius: 10px; background: {NAVY_2};
           border: 1px solid #22394d; text-decoration: none; color: {CREAM}; }}
.links a:hover, .links a:focus {{ border-color: {GOLD}; }}
h1 {{ font-size: 24px; margin: 0 0 8px; }}
h2 {{ font-size: 15px; text-transform: uppercase; letter-spacing: .08em; color: {MUTED}; margin: 28px 0 10px; }}
p.muted, .muted {{ color: {MUTED}; }}
ul.saved {{ list-style: none; padding: 0; margin: 0; }}
ul.saved li {{ padding: 10px 0; border-bottom: 1px solid #1c3245; }}
.actions {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 20px; }}
.actions a {{ padding: 10px 16px; border-radius: 10px; background: {NAVY_2}; border: 1px solid #22394d;
             text-decoration: none; }}
footer {{ margin-top: 36px; font-size: 13px; color: {MUTED}; text-align: center; }}
"""


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{_STYLE}</style></head>"
            f"<body><main>{body}</main></body></html>")


def home(mode: Mode, conn: Optional[ConnectionInfo], data_label: str, preference: str,
         search_action: str, saved_count: int, search_param: str = "q") -> str:
    conn_text = conn.describe() if conn else "Unknown network"
    pref = "Auto" if preference == "auto" else "Manual"
    links = "".join(f"<a href='{html.escape(url, quote=True)}'>{html.escape(name)}</a>"
                    for name, url in QUICK_LINKS)
    saved = (f"<a href='bee:saved'>{saved_count} saved page{'s' if saved_count != 1 else ''} — read offline</a>"
             if saved_count else "")
    action = html.escape(search_action, quote=True)
    body = f"""
<img class="logo" src="bee:asset/logo-full.png" alt="Primers Lite Bee">
<form action="{action}" method="get" role="search">
  <input type="search" name="{html.escape(search_param, quote=True)}" placeholder="Search or type a web address" autofocus
         aria-label="Search the web">
  <button type="submit">Go</button>
</form>
<div class="status">
  <span class="pill">Network: <b>{html.escape(conn_text)}</b></span>
  <span class="pill">Mode: <b>{html.escape(mode.label)}</b> ({pref})</span>
  <span class="pill">Data: <b>{html.escape(data_label)}</b></span>
</div>
<p class="muted">{html.escape(mode.summary)}</p>
<h2>Quick links</h2>
<div class="links">{links}</div>
{('<h2>Offline</h2><div class="links">' + saved + '</div>') if saved else ''}
<footer>{html.escape(APP_NAME)} {html.escape(VERSION)} · from Primers Group · ads and trackers blocked</footer>
"""
    return _page(APP_NAME, body)


def error(uri: str, message: str, mode: Mode, offline: bool) -> str:
    safe_uri = html.escape(uri, quote=True)
    tips = []
    if offline:
        tips.append("You seem to be offline. Pages you saved are still available.")
    if mode.key != "ultra":
        tips.append("On a weak signal, switch to Ultra with the gold mode button (top right): it loads text first and needs far less data.")
    tips_html = "".join(f"<li>{html.escape(t)}</li>" for t in tips)
    body = f"""
<h1>This page didn't load</h1>
<p class="muted">{html.escape(message)}</p>
<p><code>{html.escape(uri)}</code></p>
<ul>{tips_html}</ul>
<div class="actions">
  <a href="{safe_uri}">Try again</a>
  <a href="#" onclick="webkit.messageHandlers.litebee.postMessage('saved');return false">Saved pages</a>
  <a href="#" onclick="webkit.messageHandlers.litebee.postMessage('home');return false">Home</a>
</div>
"""
    return _page("Page didn't load", body)


def saved_list(items: Iterable[dict]) -> str:
    rows = []
    for item in items:
        rows.append(
            f"<li><a href='bee:saved/{html.escape(item['id'], quote=True)}'>"
            f"{html.escape(item.get('title') or item.get('url', 'Untitled'))}</a>"
            f"<div class='muted'>{html.escape(item.get('url', ''))} · saved {html.escape(item.get('saved', ''))}</div></li>")
    content = "".join(rows) or "<li class='muted'>Nothing saved yet. Press Ctrl+S on any page to keep it for offline reading.</li>"
    body = f"<h1>Saved for offline</h1><ul class='saved'>{content}</ul><div class='actions'><a href='bee:home'>Home</a></div>"
    return _page("Saved pages", body)


def tls_error(uri: str, host: str) -> str:
    body = f"""
<h1>Connection not secure</h1>
<p>The certificate presented by <b>{html.escape(host)}</b> could not be verified, so Lite Bee stopped
before sending or receiving anything. Someone could be trying to intercept this connection
(common on public Wi-Fi), or the site is misconfigured.</p>
<p class="muted"><code>{html.escape(uri)}</code></p>
<div class="actions"><a href="#" onclick="webkit.messageHandlers.litebee.postMessage('home');return false">Go home</a></div>
"""
    return _page("Connection not secure", body)
