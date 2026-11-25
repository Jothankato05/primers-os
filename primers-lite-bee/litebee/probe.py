"""
Exam site probe (``lite-bee --probe URL``), behind ``primers-exam probe``.

Before an exam, staff open the exam site in a probe window, sign in with a
test account and click through a practice exam. Every page, script, style,
image, font, frame, redirect and background request is recorded, so
``primers-exam probe`` can say which servers (and ports) the exam needs on
its allow list. The window uses a private, throw-away browser profile and
no content blocking, exactly like the exam kiosk.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from urllib.parse import urlsplit

DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


@dataclass
class HostUse:
    schemes: Set[str] = field(default_factory=set)
    ports: Set[int] = field(default_factory=set)
    requests: int = 0
    first: str = ""
    kinds: Set[str] = field(default_factory=set)

    def as_dict(self) -> dict:
        return {"schemes": sorted(self.schemes), "ports": sorted(self.ports), "requests": self.requests,
                "first": self.first, "kinds": sorted(self.kinds)}


class Recorder:
    """What the exam site loaded, host by host (pure; the window feeds it)."""

    def __init__(self, start: str):
        self.start = start
        self.hosts: Dict[str, HostUse] = {}
        self.other: Set[str] = set()     # data:, blob:, about:... (no network)
        self.failed: List[dict] = []

    def record(self, uri: str, kind: str = "resource") -> Optional[str]:
        try:
            parts = urlsplit(uri or "")
            scheme = parts.scheme.lower()
            host = (parts.hostname or "").lower().rstrip(".")
            port = parts.port or DEFAULT_PORTS.get(scheme)
        except ValueError:
            return None
        if scheme not in DEFAULT_PORTS or not host:
            if scheme:
                self.other.add(scheme)
            return None
        use = self.hosts.setdefault(host, HostUse(first=uri))
        use.schemes.add(scheme)
        if port:
            use.ports.add(port)
        use.requests += 1
        use.kinds.add(kind)
        return host

    def fail(self, uri: str, error: str) -> None:
        if len(self.failed) < 200:
            self.failed.append({"uri": uri, "error": error})

    def report(self) -> dict:
        main = (urlsplit(self.start).hostname or "").lower().rstrip(".")
        return {"start": self.start, "main_host": main,
                "hosts": {h: u.as_dict() for h, u in sorted(self.hosts.items())},
                "other_schemes": sorted(self.other), "failed": self.failed}

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.report(), f, indent=2)


def window(app, url: str, report_path: str, seconds: int = 0):   # pragma: no cover - needs a display
    """The probe window: the exam site in a normal-looking page with a
    'Done' button; on Done, close or timeout the report is written."""
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.0")
    from gi.repository import GLib, Gtk, WebKit2

    rec = Recorder(url)
    win = Gtk.ApplicationWindow(application=app, title="PRIMERS OS · Exam site probe")
    win.set_default_size(1100, 760)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    bar = Gtk.Box(spacing=10)
    bar.set_border_width(6)
    note = Gtk.Label()
    note.set_markup("<b>Exam site probe.</b> Sign in with a test account and go through a practice exam, "
                    "then press Done. Every server the site uses is recorded.")
    note.set_line_wrap(True)
    count = Gtk.Label(label="0 servers")
    done = Gtk.Button(label="Done")
    bar.pack_start(note, True, True, 0)
    bar.pack_start(count, False, False, 0)
    bar.pack_start(done, False, False, 0)
    box.pack_start(bar, False, False, 0)

    context = WebKit2.WebContext.new_with_website_data_manager(WebKit2.WebsiteDataManager.new_ephemeral())
    context.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
    context.connect("download-started", lambda _c, d: (rec.record(d.get_request().get_uri(), "download"),
                                                       d.cancel()))
    view = WebKit2.WebView.new_with_context(context)
    settings = view.get_settings()
    settings.set_property("enable-developer-extras", False)
    box.pack_start(view, True, True, 0)
    win.add(box)

    finished = []

    def finish(*_):
        if not finished:
            finished.append(True)
            rec.save(report_path)
            app.quit()
        return False

    def update():
        count.set_text(f"{len(rec.hosts)} server" + ("" if len(rec.hosts) == 1 else "s"))

    def on_resource(_view, resource, request):
        rec.record(request.get_uri(), "resource")

        def redirected(_res, req, response):
            if response is not None:
                rec.record(req.get_uri(), "redirect")
            update()
        resource.connect("sent-request", redirected)

        def failed(res, error):
            rec.fail(res.get_uri(), error.message if error else "failed")
        resource.connect("failed", failed)
        update()

    def on_policy(_view, decision, decision_type):
        if decision_type in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
                             WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri()
            rec.record(uri, "page" if decision_type == WebKit2.PolicyDecisionType.NAVIGATION_ACTION else "window")
            if decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                decision.ignore()                         # as in the kiosk: opened in place
                GLib.idle_add(lambda: view.load_uri(uri) and False)
                return True
        return False

    def on_failed(_view, _event, uri, error):
        rec.fail(uri, error.message)
        return False

    view.connect("resource-load-started", on_resource)
    view.connect("decide-policy", on_policy)
    view.connect("load-failed", on_failed)
    done.connect("clicked", finish)
    win.connect("delete-event", lambda *_: (finish(), False)[1])
    if seconds:
        GLib.timeout_add_seconds(seconds, finish)
    win.show_all()
    view.load_uri(url)
    return win
