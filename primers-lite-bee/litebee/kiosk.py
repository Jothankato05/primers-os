"""
Lite Bee kiosk window for PRIMERS OS Exam Mode (``lite-bee --kiosk``).

Full screen, no address bar, tabs, menus, downloads, file picker, printing,
drag and drop, screen or camera capture, or developer tools, and no browser
key shortcuts (ADR 0003). Only the exam servers listed in /etc/primers/exam.conf
can be shown; anything else is refused and logged. "Finish exam" ends the
program with status FINISHED, which ends the exam session; when the
invigilator stops the exam the window closes by itself (EXAM_OVER).
"""

import json
import syslog
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.0")
from gi.repository import Gdk, GLib, GObject, Gtk, WebKit2  # noqa: E402

from litebee import exam, pages  # noqa: E402

# Browser shortcuts that do nothing in the exam (typing, copy and paste
# inside the exam page still work). Keys are (ctrl, shift, keyval name).
BLOCKED_KEYS = frozenset(
    [(False, False, k) for k in ("F5", "F6", "F7", "F11", "F12")] +
    [(True, False, k) for k in "deghjklnopqrstuw"] +
    [(True, True, k) for k in "ijkcpsnqt"] +
    [(True, False, "F5")])

FINISHED = 3     # the candidate pressed "Finish exam"
EXAM_OVER = 4    # the exam was stopped (exam.conf removed)
LOG_TAG = "primers-exam"


def log(message: str) -> None:
    syslog.openlog(LOG_TAG, syslog.LOG_PID, syslog.LOG_USER)
    syslog.syslog(syslog.LOG_NOTICE, message)


class _Current:
    """What the screenshot/test helpers read from a window."""

    def __init__(self, view: WebKit2.WebView):
        self.view = view
        self.page_bytes = 0
        self.error_uri = None


class KioskWindow(Gtk.ApplicationWindow):
    def __init__(self, app, policy: exam.ExamPolicy):
        super().__init__(application=app, title="PRIMERS OS Exam")
        self.app, self.policy = app, policy
        self.blocked = 0
        self.finishing = False
        self._last_logged = None
        self._error_uri = None
        self._shown = False                # the exam page has been shown once (logged)
        self._ticks = 0
        self._started = time.monotonic()   # the exam timer ignores the wall clock
        self.set_decorated(False)

        bar = Gtk.Box(spacing=14)
        bar_bg = Gtk.EventBox()
        bar_bg.get_style_context().add_class("bee-header")
        bar_bg.add(bar)
        title = Gtk.Label()
        title.set_markup("<b>PRIMERS OS · Exam</b>")
        title.get_style_context().add_class("bee-exam-title")
        host = Gtk.Label(label=policy.main_host)
        host.get_style_context().add_class("bee-data")
        self.notice = Gtk.Label()
        self.notice.get_style_context().add_class("bee-exam-notice")
        self.clock = Gtk.Label()
        self.clock.get_style_context().add_class("bee-exam-clock")
        self.clock.set_tooltip_text("Time since this exam session started")
        finish = Gtk.Button(label="Finish exam")
        finish.get_style_context().add_class("bee-mode")
        finish.connect("clicked", self.on_finish)
        bar.pack_start(title, False, False, 6)
        bar.pack_start(host, False, False, 0)
        bar.pack_start(self.notice, True, True, 0)
        bar.pack_end(finish, False, False, 4)
        bar.pack_end(self.clock, False, False, 0)

        self.view = app.make_view()
        self.current = _Current(self.view)
        self.view.connect("decide-policy", self.on_decide_policy)
        self.view.connect("create", self.on_create)
        self.view.connect("context-menu", lambda *_: True)        # no "Inspect", "Save as"...
        self.view.connect("run-file-chooser", lambda _v, req: (req.cancel(), True)[1])  # no files
        self.view.connect("print", lambda *_: True)               # no printing or print preview
        self.view.connect("permission-request", self.on_permission)  # no screen/camera/mic capture
        self.view.drag_dest_unset()                                # nothing can be dropped in
        settings = self.view.get_settings()
        settings.set_property("enable-developer-extras", False)
        for prop in ("enable-media-stream", "enable-mediasource-capture", "enable-webrtc"):
            if settings.find_property(prop):
                settings.set_property(prop, False)
        settings.set_property("javascript-can-access-clipboard", False)
        self.view.connect("load-changed", self.on_load_changed)
        self.view.connect("load-failed", self.on_load_failed)
        self.view.connect("load-failed-with-tls-errors", self.on_tls_error)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(bar_bg, False, False, 0)
        root.pack_start(self.view, True, True, 0)
        self.add(root)
        self.connect("delete-event", lambda *_: not self.finishing)   # only "Finish exam" closes it
        self.connect("key-press-event", self.on_key)
        clear_clipboards()
        self._tick()
        GLib.timeout_add_seconds(1, self._tick)
        self.fullscreen()

    def start(self):
        log(f"exam opened: {self.policy.url}")
        self.view.load_uri(self.policy.url)

    # ------------------------------------------------------------------ #

    def _tick(self):
        elapsed = int(time.monotonic() - self._started)
        self.clock.set_text(f"In exam {elapsed // 3600}:{elapsed // 60 % 60:02d}:{elapsed % 60:02d}")
        self._ticks += 1
        if self._ticks % 5 == 0 and not self.finishing and exam.load() is None:
            log("exam stopped by the invigilator; closing the exam")
            self.finish(EXAM_OVER)
            return False
        return True

    def on_key(self, _w, event):
        key = Gdk.keyval_name(Gdk.keyval_to_lower(event.keyval)) or ""
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        return (ctrl, shift, key) in BLOCKED_KEYS

    def on_permission(self, _view, request):
        log(f"denied a {type(request).__name__} request")
        request.deny()
        return True

    def hardening(self) -> dict:
        """What the kiosk has switched off, for automated checks."""
        def has(obj, signal):
            sig = GObject.signal_lookup(signal, type(obj))
            return bool(sig) and GObject.signal_has_handler_pending(obj, sig, 0, False)
        s = self.view.get_settings()
        return {
            "developer_extras_off": not s.get_property("enable-developer-extras"),
            "drag_and_drop_off": self.view.drag_dest_get_target_list() is None,
            "print_blocked": has(self.view, "print"),
            "context_menu_blocked": has(self.view, "context-menu"),
            "file_chooser_blocked": has(self.view, "run-file-chooser"),
            "permissions_denied": has(self.view, "permission-request"),
            "new_windows_redirected": has(self.view, "create"),
            "downloads_cancelled": has(self.app.context, "download-started"),
            "clipboard_js_off": not s.get_property("javascript-can-access-clipboard"),
            "keys_filtered": has(self, "key-press-event"),
            "undecorated_fullscreen": not self.get_decorated(),
            "toplevel_windows": sum(1 for w in Gtk.Window.list_toplevels() if w.get_visible()),
        }

    def _say(self, text: str):
        self.notice.set_text(text)
        GLib.timeout_add_seconds(6, lambda: (self.notice.get_text() == text and self.notice.set_text(""), False)[1])

    def _blocked(self, uri: str):
        self.blocked += 1
        log(f"blocked {uri[:300]}")
        self._say("That page isn't part of the exam.")

    def _load_later(self, uri: str):
        GLib.idle_add(lambda: (self.view.load_uri(uri), False)[1])

    def on_decide_policy(self, view, decision, decision_type):
        if decision_type in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
                             WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri() or ""
            if not self.policy.allows(uri):
                decision.ignore()
                self._blocked(uri)
                return True
            if decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                decision.ignore()          # one window only: open it here instead
                self._load_later(uri)
                return True
        elif decision_type == WebKit2.PolicyDecisionType.RESPONSE:
            uri = decision.get_request().get_uri() or ""
            main = getattr(decision, "is_main_frame_main_resource", lambda: True)()
            if not self.policy.allows(uri):
                decision.ignore()
                if main:
                    self._blocked(uri)
                return True
            if main and not decision.is_mime_type_supported():
                decision.ignore()
                self._say("Files can't be downloaded during the exam.")
                return True
        return False

    def on_create(self, view, action):
        uri = action.get_request().get_uri() or ""
        if self.policy.allows(uri):
            self._load_later(uri)
        else:
            self._blocked(uri)
        return None

    def on_load_changed(self, view, event):
        if event == WebKit2.LoadEvent.COMMITTED:
            uri = view.get_uri() or ""
            if uri and uri == self._error_uri:        # our error page, not a visit
                self._error_uri = None
            elif uri and uri != self._last_logged and self.policy.allows(uri):
                self._last_logged = uri
                log(f"visited {uri[:300]}")
        elif event == WebKit2.LoadEvent.FINISHED:
            if not self._shown and (view.get_uri() or "") != self._error_uri:
                # How long the candidate waited for the exam (docs/benchmarks.md)
                self._shown = True
                log(f"exam page shown ({time.monotonic() - self._started:.1f} s after the exam browser opened)")
            self.app.notify_loaded(view)

    def on_load_failed(self, view, event, uri, error):
        if error.matches(WebKit2.NetworkError.quark(), WebKit2.NetworkError.CANCELLED) or \
                error.matches(WebKit2.PolicyError.quark(), WebKit2.PolicyError.FRAME_LOAD_INTERRUPTED_BY_POLICY_CHANGE):
            return False
        log(f"could not load {uri[:300]}: {error.message}")
        self._error_uri = uri
        view.load_alternate_html(pages.exam_error(uri, error.message, self.policy.url), uri, None)
        return True

    def on_tls_error(self, view, uri, cert, errors):
        log(f"certificate not trusted: {uri[:300]}")
        self._error_uri = uri
        view.load_alternate_html(pages.exam_error(
            uri, "The exam server's security certificate could not be verified.", self.policy.url), uri, None)
        return True

    def on_finish(self, *_):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.YES_NO, text="Finish the exam and sign out?")
        dlg.format_secondary_text("Make sure you have submitted your answers on the exam site first. "
                                  "Everything on this computer is cleared when you sign out.")
        answer = dlg.run()
        dlg.destroy()
        if answer == Gtk.ResponseType.YES:
            log("candidate finished the exam")
            self.finish(FINISHED)

    def finish(self, code: int):
        clear_clipboards()
        self.finishing = True
        self.app.exit_code = code
        self.app.quit()


def clear_clipboards() -> None:
    """Nothing copied before the exam can be pasted into it, and nothing
    copied during it survives the session."""
    for selection in (Gdk.SELECTION_CLIPBOARD, Gdk.SELECTION_PRIMARY):
        clip = Gtk.Clipboard.get(selection)
        clip.set_text("", 0)
        clip.store()


def selftest_report(window: "KioskWindow") -> str:
    return json.dumps({"hardening": window.hardening(), "blocked": window.blocked,
                       "uri": window.view.get_uri(), "title": window.view.get_title()})
