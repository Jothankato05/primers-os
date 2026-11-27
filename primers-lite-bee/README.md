# Primers Lite Bee

**A fast, data-saving web browser for PRIMERS OS - built for 2G, LTE and Wi-Fi.**
From Primers Group.

Lite Bee is our own browser: its own interface, network awareness, data
modes, content blocking, data meter, offline reading and crash-safe
sessions. Pages are rendered by the system's WebKit engine (the engine behind
Safari and GNOME Web), so the full modern web works and security fixes
arrive with normal Ubuntu updates.

## Data modes

Lite Bee looks at your connection (NetworkManager + ModemManager) every 30
seconds and picks a mode automatically. You can also pin one from the mode
button.

| Mode | When (Auto) | What loads |
|---|---|---|
| **Full** | Wi-Fi, Ethernet | Everything - ads and trackers still blocked |
| **Lite** | LTE, 3G, phone hotspots, any metered network | No autoplay, no web fonts, no third-party images/media |
| **Ultra** | 2G / EDGE / GPRS | Text first - no images, video, fonts or third-party scripts; mobile pages requested |

Blocking happens *inside the engine* (WebKit content rules), before any
request is sent, so blocked bytes are never downloaded. On a test page with
a 1 MB photo and a web font: Full 1.16 MB, Lite 1.04 MB, **Ultra 735 bytes**.

## Features

- Data meter in the toolbar (today / month / session); set your price per GB
  to also see the cost in naira
- About 50 advertising and tracking networks blocked in every mode; Intelligent
  Tracking Prevention on; third-party cookies off
- Start page loads instantly with zero data, with DuckDuckGo Lite search (no
  JavaScript, tiny pages)
- **Save for offline** (Ctrl+S): keep any page and read it with no connection
- **Reader mode** (Ctrl+Shift+R): just the article text
- Session saved after every page load, so tabs come back after a power cut
- Tabs, find in page, zoom, downloads to ~/Downloads
- Typed `javascript:`/`data:` URLs are never executed; TLS errors stop the
  load (no click-through); built-in `bee:` pages can't be opened by websites

## Use

```bash
lite-bee                          # start (restores your last session)
lite-bee primersgroup.ng          # open a site
lite-bee "how to cook jollof"     # search
lite-bee --mode ultra             # pin a mode (auto|full|lite|ultra)
```

From the PRIMERS Brain: `browse <site or search>`.

| Shortcut | Action |
|---|---|
| Ctrl+T / Ctrl+W | new / close tab |
| Ctrl+L | address bar |
| Ctrl+R, F5 | reload |
| Alt+← / Alt+→ | back / forward |
| Ctrl+S | save for offline |
| Ctrl+Shift+R | reader mode |
| Ctrl+F | find in page |
| Ctrl+ + / − / 0 | zoom |

## Files

`~/.local/share/lite-bee/` holds settings, session, saved pages, cookies and
the data meter (0700); `~/.cache/lite-bee/` holds the HTTP cache and compiled
blocking rules.

## Development

```bash
python3 -m pytest -q tests          # logic tests, no display needed
sudo apt install python3-gi gir1.2-webkit2-4.1 xvfb
./lite-bee                          # run from the checkout
```

Code: `litebee/app.py` (window, tabs, engine), `modes.py`, `network.py`,
`filters.py`, `datameter.py`, `urls.py`, `session.py`, `pages.py`.
