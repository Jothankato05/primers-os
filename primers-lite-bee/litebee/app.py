"""
Primers Lite Bee — the browser window.

GTK 3 interface around the system WebKit engine. Lite Bee's own work:
choosing how much to download for the current connection, blocking it inside
the engine, metering data, saving pages for offline reading, reader mode and
crash-safe session restore.
"""

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
try:
    gi.require_version("WebKit2", "4.1")
except ValueError:  # Ubuntu 22.04 ships 4.0 alongside
    gi.require_version("WebKit2", "4.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, WebKit2  # noqa: E402

from litebee import APP_ID, APP_NAME, VERSION, filters, network, pages, storage, study, urls  # noqa: E402
from litebee.datameter import DataMeter  # noqa: E402
from litebee.modes import MODES, Mode, resolve  # noqa: E402
from litebee.session import Session, Settings  # noqa: E402

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
MOBILE_UA = ("Mozilla/5.0 (Linux; Android 12; Mobile) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/16.0 Mobile Safari/605.1.15 PrimersLiteBee/" + VERSION)
CSS = b"""
.bee-header { background-color: #0a1a27; padding: 4px 6px; }
.bee-header button, .bee-header button image { color: #f4efe6; }
.bee-header entry { background-color: #11263a; color: #f4efe6; border-color: #22394d; }
notebook header { background-color: #0d2131; }
notebook tab label { color: #c9d3dc; }
.bee-url { min-height: 32px; border-radius: 16px; padding: 0 12px; }
.bee-mode { font-weight: bold; color: #0a1a27; background: #e6ad39; border-radius: 12px; padding: 0 10px; }
.bee-data { color: #8aa0b4; padding: 0 8px; }
.bee-progress progress { background: #e6ad39; min-height: 2px; }
.bee-progress trough { min-height: 2px; background: transparent; }
"""


class Tab(Gtk.Box):
    """One page: a WebKit view plus its bookkeeping."""

    def __init__(self, window: "BrowserWindow", view: WebKit2.WebView):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.view = view
        self.page_bytes = 0
        self.error_uri: Optional[str] = None     # URI currently showing our error page
        self.pending_error: Optional[str] = None
        self.title_label = Gtk.Label(label="New tab", ellipsize=3, width_chars=14, max_width_chars=22, xalign=0)
        self.pack_start(view, True, True, 0)
        view.connect("load-changed", window.on_load_changed, self)
        view.connect("load-failed", window.on_load_failed, self)
        view.connect("load-failed-with-tls-errors", window.on_tls_error, self)
        view.connect("notify::title", window.on_title, self)
        view.connect("notify::uri", window.on_uri, self)
        view.connect("notify::estimated-load-progress", window.on_progress, self)
        view.connect("resource-load-started", window.on_resource, self)
        view.connect("create", window.on_create, self)
        view.connect("decide-policy", window.on_decide_policy, self)

    def tab_header(self) -> Gtk.Box:
        box = Gtk.Box(spacing=4)
        icon = Gtk.Image.new_from_file(os.path.join(ASSETS, "lite-bee-16.png"))
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("Close tab (Ctrl+W)")
        close.connect("clicked", lambda *_: self.window.close_tab(self))
        box.pack_start(icon, False, False, 0)
        box.pack_start(self.title_label, True, True, 0)
        box.pack_start(close, False, False, 0)
        box.show_all()
        return box


class BrowserWindow(Gtk.ApplicationWindow):
    def __init__(self, app: "LiteBeeApp"):
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.set_default_size(1180, 760)
        self.set_icon_from_file(os.path.join(ASSETS, "lite-bee-128.png"))

        header = Gtk.Box(spacing=4)
        header_bg = Gtk.EventBox()
        header_bg.get_style_context().add_class("bee-header")
        header_bg.add(header)
        self.back_btn = self._button("go-previous-symbolic", "Back (Alt+Left)", lambda *_: self.current.view.go_back())
        self.fwd_btn = self._button("go-next-symbolic", "Forward (Alt+Right)", lambda *_: self.current.view.go_forward())
        self.reload_btn = self._button("view-refresh-symbolic", "Reload (Ctrl+R)", self.on_reload)
        self.home_btn = self._button("go-home-symbolic", "Home", lambda *_: self.load("bee:home"))
        self.url = Gtk.Entry()
        self.url.get_style_context().add_class("bee-url")
        self.url.set_placeholder_text("Search or type a web address")
        self.url.connect("activate", self.on_url_activate)
        self.mode_btn = Gtk.MenuButton(label="Auto")
        self.mode_btn.get_style_context().add_class("bee-mode")
        self.mode_btn.set_tooltip_text("Data mode")
        self.mode_btn.set_popover(self._mode_popover())
        self.data_label = Gtk.Label()
        self.data_label.get_style_context().add_class("bee-data")
        menu_btn = Gtk.MenuButton()
        menu_btn.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        menu_btn.set_popover(self._main_popover())
        for w in (self.back_btn, self.fwd_btn, self.reload_btn, self.home_btn):
            header.pack_start(w, False, False, 0)
        header.pack_start(self.url, True, True, 4)
        header.pack_start(self.data_label, False, False, 0)
        header.pack_start(self.mode_btn, False, False, 0)
        header.pack_start(menu_btn, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.get_style_context().add_class("bee-progress")

        self.find_bar = Gtk.SearchBar()
        self.find_entry = Gtk.SearchEntry()
        self.find_entry.connect("search-changed", self.on_find)
        self.find_entry.connect("activate", lambda *_: self.current.view.get_find_controller().search_next())
        self.find_bar.add(self.find_entry)
        self.find_bar.connect_entry(self.find_entry)

        self.notebook = Gtk.Notebook(scrollable=True, show_border=False)
        self.notebook.connect("switch-page", self.on_switch_page)
        new_tab = self._button("tab-new-symbolic", "New tab (Ctrl+T)", lambda *_: self.new_tab("bee:home"))
        new_tab.show()
        self.notebook.set_action_widget(new_tab, Gtk.PackType.END)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(header_bg, False, False, 0)
        root.pack_start(self.progress, False, False, 0)
        root.pack_start(self.find_bar, False, False, 0)
        root.pack_start(self.notebook, True, True, 0)
        self.add(root)

        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", self.on_close)
        self.refresh_chrome()

    # ------------------------------------------------------------------ #
    #  Widgets
    # ------------------------------------------------------------------ #

    @staticmethod
    def _button(icon: str, tip: str, cb) -> Gtk.Button:
        b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.set_tooltip_text(tip)
        b.connect("clicked", cb)
        return b

    def _mode_popover(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=12)
        self.conn_label = Gtk.Label(xalign=0)
        box.pack_start(self.conn_label, False, False, 0)
        group = None
        self.mode_radios: Dict[str, Gtk.RadioButton] = {}
        options = [("auto", "Auto — pick for this connection")] + \
                  [(k, f"{m.label} — {m.summary}") for k, m in MODES.items()]
        for key, text in options:
            rb = Gtk.RadioButton.new_with_label_from_widget(group, text)
            rb.get_child().set_line_wrap(True)
            rb.get_child().set_max_width_chars(48)
            group = group or rb
            rb.connect("toggled", self.on_mode_toggled, key)
            self.mode_radios[key] = rb
            box.pack_start(rb, False, False, 0)
        box.show_all()
        pop.add(box)
        return pop

    def _main_popover(self) -> Gtk.Popover:
        pop = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=6)
        items = [
            ("New tab\tCtrl+T", lambda: self.new_tab("bee:home")),
            ("Reader mode\tCtrl+Shift+R", self.reader_mode),
            ("Save for offline\tCtrl+S", self.save_offline),
            ("Saved pages", lambda: self.load("bee:saved")),
            ("Find in page\tCtrl+F", self.toggle_find),
            ("Zoom in\tCtrl++", lambda: self.zoom(0.1)),
            ("Zoom out\tCtrl+-", lambda: self.zoom(-0.1)),
            ("Set data price…", self.ask_price),
            ("Clear browsing data", self.clear_data),
            (f"About {APP_NAME}", self.about),
        ]
        for text, cb in items:
            b = Gtk.ModelButton(text=text.split("\t")[0])
            b.connect("clicked", lambda _b, f=cb: (pop.popdown(), f()))
            box.pack_start(b, False, False, 0)
        box.show_all()
        pop.add(box)
        return pop

    # ------------------------------------------------------------------ #
    #  Tabs
    # ------------------------------------------------------------------ #

    @property
    def current(self) -> Optional[Tab]:
        page = self.notebook.get_nth_page(self.notebook.get_current_page())
        return page if isinstance(page, Tab) else None

    def tabs(self) -> List[Tab]:
        return [self.notebook.get_nth_page(i) for i in range(self.notebook.get_n_pages())]

    def new_tab(self, uri: Optional[str] = None, view: Optional[WebKit2.WebView] = None,
                switch: bool = True) -> Tab:
        view = view or self.app.make_view()
        tab = Tab(self, view)
        idx = self.notebook.append_page(tab, tab.tab_header())
        self.notebook.set_tab_reorderable(tab, True)
        tab.show_all()
        if switch:
            self.notebook.set_current_page(idx)
        if uri:
            self.load(uri, tab)
        if uri in (None, "bee:home"):
            self.url.grab_focus()
        return tab

    def close_tab(self, tab: Tab):
        idx = self.notebook.page_num(tab)
        if idx < 0:
            return
        self.notebook.remove_page(idx)
        tab.view.destroy()
        if self.notebook.get_n_pages() == 0:
            self.new_tab("bee:home")
        self.save_session()

    def load(self, uri: str, tab: Optional[Tab] = None):
        tab = tab or self.current
        if tab:
            tab.page_bytes = 0
            site = self.app.study.check(uri)
            tab.view.load_uri(pages.study_uri(site) if site else uri)

    # ------------------------------------------------------------------ #
    #  Signals
    # ------------------------------------------------------------------ #

    def on_url_activate(self, entry):
        self.load(urls.to_url(entry.get_text(), self.app.settings.search_engine))
        self.current.view.grab_focus()

    def on_reload(self, *_):
        view = self.current.view
        if view.is_loading():
            view.stop_loading()
        else:
            view.reload()

    def on_switch_page(self, nb, page, idx):
        GLib.idle_add(self.refresh_chrome)

    def on_load_changed(self, view, event, tab):
        if event == WebKit2.LoadEvent.STARTED:
            tab.page_bytes = 0
            tab.error_uri = None
        if event == WebKit2.LoadEvent.COMMITTED and tab.pending_error:
            if tab.pending_error == view.get_uri():
                tab.error_uri = tab.pending_error
            tab.pending_error = None
        if event == WebKit2.LoadEvent.FINISHED:
            self.save_session()
            self.app.meter.save()
            self.app.notify_loaded(view)
        if tab is self.current:
            self.refresh_chrome()

    def on_load_failed(self, view, event, uri, error, tab):
        if error.matches(WebKit2.NetworkError.quark(), WebKit2.NetworkError.CANCELLED) or \
                error.matches(WebKit2.PolicyError.quark(), WebKit2.PolicyError.FRAME_LOAD_INTERRUPTED_BY_POLICY_CHANGE):
            return False
        offline = self.app.connection.kind == "none"
        tab.pending_error = uri
        view.load_alternate_html(pages.error(uri, error.message, self.app.mode, offline), uri, None)
        return True

    def on_tls_error(self, view, uri, cert, errors, tab):
        tab.pending_error = uri
        view.load_alternate_html(pages.tls_error(uri, urls.display_host(uri)), uri, None)
        return True

    def on_title(self, view, _pspec, tab):
        title = view.get_title() or urls.display_host(view.get_uri() or "") or "New tab"
        tab.title_label.set_text(title)
        tab.title_label.set_tooltip_text(title)
        if tab is self.current:
            self.set_title(f"{title} — {APP_NAME}")

    def on_uri(self, view, _pspec, tab):
        if tab is self.current:
            self.refresh_chrome()

    def on_progress(self, view, _pspec, tab):
        if tab is self.current:
            p = view.get_estimated_load_progress()
            self.progress.set_fraction(p)
            self.progress.set_visible(view.is_loading())

    def on_resource(self, view, resource, request, tab):
        if not (request.get_uri() or "").startswith(("http://", "https://")):
            return  # bee:, file:, data: cost nothing

        def finished(res):
            resp = res.get_response()
            if resp is None:
                return
            size = resp.get_content_length()
            if size and size > 0:
                tab.page_bytes += size
                self.app.meter.add(size)
                if tab is self.current:
                    self.update_data_label()
        resource.connect("finished", finished)

    def on_create(self, view, action, tab):
        child = WebKit2.WebView.new_with_related_view(view)
        child.set_settings(self.app.settings_for(self.app.mode))
        child.connect("ready-to-show", lambda v: self.new_tab(view=v))
        return child

    def on_decide_policy(self, view, decision, decision_type, tab):
        if decision_type in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION,
                             WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            # Study Mode, early: a link the user clicked doesn't even reach the
            # network (on 2G every request counts).
            action = decision.get_navigation_action()
            site = self.app.study.check(action.get_request().get_uri() or "")
            clicked = action.get_navigation_type() == WebKit2.NavigationType.LINK_CLICKED and \
                action.is_user_gesture()
            if site and (clicked or decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
                decision.ignore()
                if decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                    GLib.idle_add(lambda: self.new_tab(pages.study_uri(site)) and False)
                else:
                    GLib.idle_add(lambda: self.load(pages.study_uri(site), tab) and False)
                return True
        if decision_type == WebKit2.PolicyDecisionType.RESPONSE:
            # Study Mode: paused sites never load, whether typed, clicked,
            # redirected to or embedded in another page.
            site = self.app.study.check(decision.get_request().get_uri() or "")
            if site:
                decision.ignore()
                main = getattr(decision, "is_main_frame_main_resource", lambda: True)()
                if main:
                    GLib.idle_add(lambda: self.load(pages.study_uri(site), tab) and False)
                return True
            if not decision.is_mime_type_supported():
                decision.download()
                return True
        return False

    def on_mode_toggled(self, button, key):
        if button.get_active() and key != self.app.settings.mode:
            self.app.set_preference(key)

    def on_find(self, entry):
        fc = self.current.view.get_find_controller()
        text = entry.get_text()
        if text:
            fc.search(text, WebKit2.FindOptions.CASE_INSENSITIVE | WebKit2.FindOptions.WRAP_AROUND, 500)
        else:
            fc.search_finish()

    def on_key(self, _w, event):
        ctrl = event.state & Gdk.ModifierType.CONTROL_MASK
        shift = event.state & Gdk.ModifierType.SHIFT_MASK
        alt = event.state & Gdk.ModifierType.MOD1_MASK
        key = Gdk.keyval_name(event.keyval) or ""
        k = key.lower()
        if ctrl and k == "t":
            self.new_tab("bee:home")
        elif ctrl and k == "w":
            self.close_tab(self.current)
        elif ctrl and k == "l" or key == "F6":
            self.url.grab_focus()
            self.url.select_region(0, -1)
        elif (ctrl and k == "r" and not shift) or key == "F5":
            self.current.view.reload()
        elif ctrl and shift and k == "r":
            self.reader_mode()
        elif ctrl and k == "s":
            self.save_offline()
        elif ctrl and k == "f":
            self.toggle_find()
        elif ctrl and k in ("plus", "equal", "kp_add"):
            self.zoom(0.1)
        elif ctrl and k in ("minus", "kp_subtract"):
            self.zoom(-0.1)
        elif ctrl and k == "0":
            self.current.view.set_zoom_level(1.0)
        elif ctrl and k == "tab":
            n = self.notebook.get_n_pages()
            step = -1 if shift else 1
            self.notebook.set_current_page((self.notebook.get_current_page() + step) % n)
        elif alt and k == "left":
            self.current.view.go_back()
        elif alt and k == "right":
            self.current.view.go_forward()
        elif key == "Escape":
            if self.find_bar.get_search_mode():
                self.find_bar.set_search_mode(False)
            else:
                self.current.view.stop_loading()
        else:
            return False
        return True

    def on_close(self, *_):
        self.save_session()
        self.app.meter.save(force=True)
        return False

    # ------------------------------------------------------------------ #
    #  Features
    # ------------------------------------------------------------------ #

    def refresh_chrome(self):
        tab = self.current
        if not tab:
            return False
        view = tab.view
        uri = view.get_uri() or ""
        shown = "" if uri.startswith("bee:home") else uri
        typed = self.url.get_text()
        # Don't overwrite an address the user is in the middle of typing
        if not self.url.has_focus() or typed in ("", getattr(self, "_shown_uri", "")):
            self.url.set_text(shown)
        self._shown_uri = shown
        icon = "channel-secure-symbolic" if urls.is_secure(uri) else "channel-insecure-symbolic"
        self.url.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, icon)
        self.back_btn.set_sensitive(view.can_go_back())
        self.fwd_btn.set_sensitive(view.can_go_forward())
        self.reload_btn.set_image(Gtk.Image.new_from_icon_name(
            "process-stop-symbolic" if view.is_loading() else "view-refresh-symbolic", Gtk.IconSize.BUTTON))
        self.progress.set_visible(view.is_loading())
        self.set_title(f"{view.get_title() or 'New tab'} — {APP_NAME}")
        self.update_mode_button()
        self.update_data_label()
        return False

    def update_mode_button(self):
        s, m = self.app.settings, self.app.mode
        self.mode_btn.set_label(m.label + (" ·A" if s.mode == "auto" else ""))
        self.mode_btn.set_tooltip_text(f"{m.label} mode ({'automatic' if s.mode == 'auto' else 'manual'}) — "
                                       f"{self.app.connection.describe()}\n{m.summary}")
        self.conn_label.set_markup(f"<b>Connection:</b> {html.escape(self.app.connection.describe())}")
        radio = self.mode_radios.get(s.mode)
        if radio and not radio.get_active():
            radio.set_active(True)

    def update_data_label(self):
        self.data_label.set_text(self.app.meter.label())
        self.data_label.set_tooltip_text(self.app.meter.tooltip())

    def zoom(self, delta: float):
        view = self.current.view
        view.set_zoom_level(max(0.3, min(3.0, view.get_zoom_level() + delta)))

    def toggle_find(self):
        on = not self.find_bar.get_search_mode()
        self.find_bar.set_search_mode(on)
        if on:
            self.find_entry.grab_focus()
        else:
            self.current.view.get_find_controller().search_finish()

    def reader_mode(self):
        with open(os.path.join(ASSETS, "reader.js"), encoding="utf-8") as f:
            script = f.read()
        self.current.view.run_javascript(script, None, None, None)

    def save_offline(self):
        view = self.current.view
        uri = view.get_uri() or ""
        if not uri.startswith(("http://", "https://")):
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        page_id = f"{stamp}-{re.sub(r'[^a-z0-9]+', '-', urls.display_host(uri).lower())[:40]}"
        path = os.path.join(storage.saved_pages_dir(), page_id + ".mhtml")
        title = view.get_title() or uri

        def done(v, res):
            try:
                v.save_to_file_finish(res)
            except GLib.Error as e:
                self.toast(f"Could not save: {e.message}")
                return
            index = self.app.saved_index()
            index.insert(0, {"id": page_id, "title": title, "url": uri,
                             "saved": datetime.now().strftime("%d %b %Y %H:%M")})
            storage.write_private(storage.data_file("saved.json"), json.dumps(index[:500]))
            self.toast("Saved for offline reading")

        view.save_to_file(Gio.File.new_for_path(path), WebKit2.SaveMode.MHTML, None, done)

    def toast(self, text: str):
        self.data_label.set_text(text)
        GLib.timeout_add_seconds(3, lambda: (self.update_data_label(), False)[1])

    def ask_price(self):
        dlg = Gtk.Dialog(title="Data price", transient_for=self, modal=True)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.add(Gtk.Label(label="How much does 1 GB of data cost you (₦)?\nLeave 0 to hide cost.", xalign=0))
        spin = Gtk.SpinButton.new_with_range(0, 1_000_000, 50)
        spin.set_value(self.app.settings.naira_per_gb)
        box.add(spin)
        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK:
            self.app.settings.naira_per_gb = float(spin.get_value())
            self.app.meter.naira_per_gb = self.app.settings.naira_per_gb
            self.app.settings.save()
            self.update_data_label()
        dlg.destroy()

    def clear_data(self):
        mgr = self.app.context.get_website_data_manager()
        mgr.clear(WebKit2.WebsiteDataTypes.ALL, 0, None, None, None)
        self.toast("Cookies, cache and site data cleared")

    def about(self):
        dlg = Gtk.AboutDialog(transient_for=self, modal=True)
        dlg.set_program_name(APP_NAME)
        dlg.set_version(VERSION)
        dlg.set_comments("A fast, data-saving browser for PRIMERS OS — from Primers Group.")
        dlg.set_logo(GdkPixbuf.Pixbuf.new_from_file_at_size(os.path.join(ASSETS, "lite-bee-128.png"), 96, 96))
        dlg.set_website("https://primersgroup.ng")
        dlg.run()
        dlg.destroy()

    def save_session(self):
        tabs = []
        for t in self.tabs():
            uri = t.view.get_uri()
            if uri and not uri.startswith(("bee:", "about:")):
                tabs.append(uri)
        self.app.session.tabs = tabs
        self.app.session.active = max(0, self.notebook.get_current_page())
        try:
            self.app.session.save()
        except OSError:
            pass


class LiteBeeApp(Gtk.Application):
    def __init__(self, urls_to_open: List[str], screenshot: Optional[str] = None,
                 private: bool = False):
        super().__init__(application_id=APP_ID if not screenshot else None,
                         flags=Gio.ApplicationFlags.NON_UNIQUE if screenshot else Gio.ApplicationFlags.FLAGS_NONE)
        self.urls_to_open = urls_to_open
        self.screenshot = screenshot
        self.settings = Settings.load()
        self.session = Session.load()
        self.meter = DataMeter(naira_per_gb=self.settings.naira_per_gb)
        self.study = study.StudyGate()
        self.connection = network.detect()
        self.mode: Mode = resolve(self.settings.mode, self.connection)
        self.window: Optional[BrowserWindow] = None
        self._filters: Dict[str, object] = {}
        self._screenshot_done = False
        self.filter_ready = False
        self._on_filter_ready: List = []

    # ------------------------------------------------------------------ #

    def do_startup(self):
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)

        data_mgr = WebKit2.WebsiteDataManager(base_data_directory=storage.data_dir(),
                                              base_cache_directory=storage.cache_dir())
        if hasattr(data_mgr, "set_itp_enabled"):
            data_mgr.set_itp_enabled(True)  # Intelligent Tracking Prevention
        self.context = WebKit2.WebContext.new_with_website_data_manager(data_mgr)
        self.context.set_cache_model(WebKit2.CacheModel.WEB_BROWSER)
        cookies = data_mgr.get_cookie_manager()
        cookies.set_persistent_storage(os.path.join(storage.data_dir(), "cookies.sqlite"),
                                       WebKit2.CookiePersistentStorage.SQLITE)
        cookies.set_accept_policy(WebKit2.CookieAcceptPolicy.NO_THIRD_PARTY)
        self.context.register_uri_scheme("bee", self.on_bee_request)
        # Web pages can't navigate to or embed bee: pages
        self.context.get_security_manager().register_uri_scheme_as_local("bee")
        self.context.connect("download-started", self.on_download)

        self.content = WebKit2.UserContentManager()
        # Buttons on Lite Bee's own error pages talk to the app through this
        self.content.register_script_message_handler("litebee")
        self.content.connect("script-message-received::litebee", self.on_page_message)
        self.filter_store = WebKit2.UserContentFilterStore.new(os.path.join(storage.cache_dir(), "filters"))
        self.apply_mode(self.mode)
        GLib.timeout_add_seconds(4, lambda: (self.filter_ready or self._filter_installed(), False)[1])
        GLib.timeout_add_seconds(30, self.check_connection)

    def do_activate(self):
        if self.window:
            for u in self.urls_to_open:
                self.window.new_tab(urls.to_url(u, self.settings.search_engine))
            self.window.present()
            return
        self.window = BrowserWindow(self)
        start = [urls.to_url(u, self.settings.search_engine) for u in self.urls_to_open]
        if not start and self.settings.restore_session and self.session.tabs and not self.screenshot:
            start = list(self.session.tabs)
        start = start or [self.settings.homepage]
        tabs = [self.window.new_tab(None, switch=(i == 0)) for i in range(len(start))]
        if self.session.tabs and start == self.session.tabs:
            self.window.notebook.set_current_page(min(self.session.active, len(start) - 1))
        self.window.show_all()
        self.window.progress.hide()

        def load_all():
            for tab, uri in zip(tabs, start):
                self.window.load(uri, tab)
        # Never load a page before the blocking rules are in place
        self.when_filter_ready(load_all)

    def do_command_line(self, cmdline):  # pragma: no cover - unused (no HANDLES_COMMAND_LINE)
        self.activate()
        return 0

    # ------------------------------------------------------------------ #
    #  Modes and filtering
    # ------------------------------------------------------------------ #

    def settings_for(self, mode: Mode) -> WebKit2.Settings:
        s = WebKit2.Settings()
        s.set_property("auto-load-images", mode.load_images)
        s.set_property("enable-javascript", mode.javascript)
        s.set_property("enable-webgl", mode.webgl)
        s.set_property("media-playback-requires-user-gesture", not mode.autoplay_media)
        s.set_property("enable-page-cache", True)
        s.set_property("enable-smooth-scrolling", True)
        s.set_property("enable-developer-extras", False)
        s.set_property("javascript-can-open-windows-automatically", False)
        if mode.mobile_pages:
            s.set_property("user-agent", MOBILE_UA)
        else:
            s.set_user_agent_with_application_details("PrimersLiteBee", VERSION)
        return s

    def make_view(self) -> WebKit2.WebView:
        view = WebKit2.WebView(web_context=self.context, user_content_manager=self.content,
                               settings=self.settings_for(self.mode))
        view.set_zoom_level(self.settings.zoom)
        return view

    def when_filter_ready(self, callback):
        """Run callback once blocking rules are active (or after 4 s if compiling failed)."""
        if self.filter_ready:
            callback()
            return
        self._on_filter_ready.append(callback)

    def _filter_installed(self):
        self.filter_ready = True
        callbacks, self._on_filter_ready = self._on_filter_ready, []
        for cb in callbacks:
            cb()

    def apply_mode(self, mode: Mode, on_ready=None):
        self.mode = mode
        fid = filters.filter_id(mode)
        self.filter_ready = False
        if on_ready:
            self._on_filter_ready.append(on_ready)

        def install(flt):
            self.content.remove_all_filters()
            self.content.add_filter(flt)
            self._filters[fid] = flt
            self._filter_installed()

        if fid in self._filters:
            install(self._filters[fid])
        else:
            def loaded(store, res):
                try:
                    install(store.load_finish(res))
                except GLib.Error:
                    store.save(fid, GLib.Bytes.new(filters.build_json(mode).encode()), None, saved)

            def saved(store, res):
                try:
                    install(store.save_finish(res))
                except GLib.Error as e:
                    print(f"[lite-bee] content filter failed: {e.message}", file=sys.stderr)
                    self._filter_installed()  # browse unfiltered rather than not at all

            self.filter_store.load(fid, None, loaded)

        if self.window:
            for tab in self.window.tabs():
                tab.view.set_settings(self.settings_for(mode))
            self.window.update_mode_button()

    def set_preference(self, pref: str):
        self.settings.mode = pref
        self.settings.save()
        new_mode = resolve(pref, self.connection)
        if new_mode.key == self.mode.key:
            self.window and self.window.update_mode_button()
            return

        def reload_current():
            if self.window and self.window.current:
                self.window.current.view.reload()
        self.apply_mode(new_mode, on_ready=reload_current)

    def check_connection(self):
        conn = network.detect()
        if conn != self.connection:
            self.connection = conn
            if self.settings.mode == "auto":
                new_mode = resolve("auto", conn)
                if new_mode.key != self.mode.key:
                    self.apply_mode(new_mode)
            if self.window:
                self.window.update_mode_button()
        self.meter.save()
        return True

    # ------------------------------------------------------------------ #
    #  bee: pages and downloads
    # ------------------------------------------------------------------ #

    def on_page_message(self, _ucm, js_result):
        """Only honoured while the visible tab is showing our own error page."""
        tab = self.window.current if self.window else None
        if not tab or not tab.error_uri or tab.view.get_uri() != tab.error_uri:
            return
        try:
            action = js_result.get_js_value().to_string()
        except (AttributeError, GLib.Error):
            return
        target = {"home": "bee:home", "saved": "bee:saved"}.get(action)
        if target:
            self.window.load(target, tab)

    def saved_index(self) -> list:
        data = storage.read_json(storage.data_file("saved.json"), [])
        return [d for d in data if isinstance(d, dict) and "id" in d] if isinstance(data, list) else []

    def on_bee_request(self, request):
        path = request.get_path() or ""
        try:
            if path in ("", "home", "newtab"):
                action, param = urls.search_form(self.settings.search_engine)
                body = pages.home(self.mode, self.connection, self.meter.label(), self.settings.mode,
                                  action, len(self.saved_index()), param).encode()
                self._finish(request, body, "text/html")
            elif path == "saved":
                self._finish(request, pages.saved_list(self.saved_index()).encode(), "text/html")
            elif path == "study":
                site = urls.query_param(request.get_uri(), "site")
                self._finish(request, pages.study_paused(site, self.study.until()).encode(), "text/html")
            elif path.startswith("saved/"):
                page_id = path[6:]
                if not re.fullmatch(r"[A-Za-z0-9-]+", page_id):
                    raise FileNotFoundError(page_id)
                with open(os.path.join(storage.saved_pages_dir(), page_id + ".mhtml"), "rb") as f:
                    self._finish(request, f.read(), "multipart/related")
            elif path.startswith("asset/"):
                name = os.path.basename(path[6:])
                if not re.fullmatch(r"[A-Za-z0-9._-]+\.(png|js)", name):
                    raise FileNotFoundError(name)
                with open(os.path.join(ASSETS, name), "rb") as f:
                    mime = "image/png" if name.endswith(".png") else "text/javascript"
                    self._finish(request, f.read(), mime)
            else:
                raise FileNotFoundError(path)
        except OSError:
            request.finish_error(GLib.Error.new_literal(Gio.io_error_quark(), "Not found", Gio.IOErrorEnum.NOT_FOUND))

    @staticmethod
    def _finish(request, data: bytes, mime: str):
        stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
        request.finish(stream, len(data), mime)

    def on_download(self, _ctx, download):
        def decide(d, suggested):
            folder = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or \
                os.path.join(os.path.expanduser("~"), "Downloads")
            os.makedirs(folder, exist_ok=True)
            name = os.path.basename(suggested or "download") or "download"
            target = os.path.join(folder, name)
            base, ext = os.path.splitext(target)
            n = 1
            while os.path.exists(target):
                target = f"{base} ({n}){ext}"
                n += 1
            d.set_destination(GLib.filename_to_uri(target, None))
            return True
        download.connect("decide-destination", decide)
        download.connect("finished", lambda d: self.window and self.window.toast(
            f"Downloaded: {os.path.basename(GLib.filename_from_uri(d.get_destination())[0])}"))

    # ------------------------------------------------------------------ #
    #  Screenshot mode (used by tests)
    # ------------------------------------------------------------------ #

    def notify_loaded(self, view):
        if self.screenshot and not self._screenshot_done:
            self._screenshot_done = True
            GLib.timeout_add(1500, self._take_screenshot)

    def _take_screenshot(self):
        win = self.window.get_window()
        w, h = win.get_width(), win.get_height()
        pb = Gdk.pixbuf_get_from_window(win, 0, 0, w, h)
        pb.savev(self.screenshot, "png", [], [])
        print(json.dumps({"screenshot": self.screenshot, "mode": self.mode.key,
                          "uri": self.window.current.view.get_uri(),
                          "title": self.window.current.view.get_title(),
                          "bytes": self.window.current.page_bytes}))
        self.quit()
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="lite-bee", description=f"{APP_NAME} — fast, data-saving browser")
    parser.add_argument("urls", nargs="*", help="addresses or searches to open")
    parser.add_argument("--mode", choices=["auto", "full", "lite", "ultra"], help="set the data mode and remember it")
    parser.add_argument("--screenshot", metavar="PNG", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    args = parser.parse_args(argv)
    GLib.set_prgname("lite-bee")
    GLib.set_application_name(APP_NAME)
    if args.mode:
        s = Settings.load()
        s.mode = args.mode
        s.save()
    app = LiteBeeApp(args.urls, screenshot=args.screenshot)
    return app.run([sys.argv[0]])
