from adapters.registry import ADAPTERS_BY_APP
from core.events.browser_tab_changed import BrowserTabChanged
from core.events.browser_tab_closed import BrowserTabClosed
from core.events.focus_changed import FocusChanged
from core.events.window_caption_changed import WindowCaptionChanged
from core.events.window_closed import WindowClosed
from core.history_manager import HistoryManager
from core.models.focus_item import FocusItem

# Resource classes (KWin's `app`) that host a companion WebExtension
# reporting BrowserTabChanged/BrowserTabClosed - originally just browsers,
# but Thunderbird's MailExtension APIs (tabs.onActivated/onRemoved) give it
# the exact same "real tab id, extension can report and restore it" shape,
# so it's tracked the same way rather than needing its own mechanism.
# There's no shared ID space between a KWin window and the extension's own
# `windowId`, so we can't correlate a tab event to a specific KWin window -
# we treat "one instance of the app" as a single logical window, which
# matches every scenario this project has designed for so far.
TAB_EXTENSION_APPS = {
    "brave-browser",
    "vivaldi-stable",
    "Vivaldi-snap",
    "google-chrome",
    "chromium-browser",
    "chromium",
    "microsoft-edge",
    "firefox",
    "firefox_firefox",
    # Confirmed live via the KWin script's own event log.
    "thunderbird",
}


class NavigationEngine:
    """
    Merges KWin focus events and browser tab events into a single
    navigation history.
    """

    def __init__(self, event_bus, history_manager=None):
        self._history = history_manager or HistoryManager()
        self._current_app = None
        self._current_window_id = None

        # (WebSocket connection, browser-native windowId) -> the KWin
        # window it belongs to, learned the first time that browser
        # window is seen focused. Keyed by connection rather than the
        # `browser` field's family name ("chromium"/"firefox"), since two
        # windows of the same family - e.g. Vivaldi and Brave both
        # reporting "chromium" - would otherwise collide and each pick up
        # the other's tab.
        self._kwin_window_for_browser_window = {}

        # KWin window_id -> latest known tab for that window, so
        # refocusing it picks up tab activity that happened while it was
        # in the background.
        self._latest_tab_by_kwin_window = {}

        # KWin window_id -> latest known adapter restore_id for that
        # window (Konsole session, etc). Mirrors _latest_tab_by_kwin_window
        # for non-browser tabbed apps; kept separate since the two paths
        # populate it differently (adapter resolution vs. browser
        # extension messages) but serve the exact same purpose below.
        self._latest_adapter_restore_by_kwin_window = {}

        event_bus.subscribe(FocusChanged, self._on_focus_changed)
        event_bus.subscribe(BrowserTabChanged, self._on_browser_tab_changed)
        event_bus.subscribe(WindowClosed, self._on_window_closed)
        event_bus.subscribe(BrowserTabClosed, self._on_browser_tab_closed)
        event_bus.subscribe(WindowCaptionChanged, self._on_window_caption_changed)

    def _on_focus_changed(self, event: FocusChanged):
        # Transient/modal dialogs (an app's "Open File"/"Close Document"
        # prompts, etc) report the exact same `app` resourceClass as their
        # owning window. Treating one like a real focus change would let an
        # adapter-tracked app's dialog get misattributed to whatever the
        # app's *main* window happens to have open right now (adapters
        # resolve by pid, and dialogs share their owning process's pid),
        # and would also stomp _current_window_id - silently breaking
        # caption-change detection on the REAL window until its next
        # genuine focus event arrives. Bail out before touching any state.
        if not event.normal:
            return

        self._current_app = event.app
        self._current_window_id = event.window_id

        current = self._history.current

        # Already sitting on an entry for this exact window - either a
        # redundant re-activation, or the echo of raising this window to
        # satisfy a back()/forward() request (KWin fires the same
        # windowActivated signal either way). Re-confirm that entry rather
        # than falling through to the tab cache below, which holds
        # whatever tab was *most recently* seen for this window and can
        # easily be newer than the one this history position actually
        # refers to - substituting it in would silently jump us to the
        # wrong tab and, worse, look like a fresh navigation and truncate
        # away the forward history we were just re-visiting.
        #
        # Checked against the live current position (not a one-shot flag
        # set by the navigation call) so it can't be invalidated by an
        # unrelated event - e.g. a page title update on some other tab -
        # arriving before this echo does.
        if current is not None and current.window_id == event.window_id:
            self._history.push(current)
            return

        latest_tab = self._latest_tab_by_kwin_window.get(event.window_id)

        adapter = ADAPTERS_BY_APP.get(event.app)

        if event.app in TAB_EXTENSION_APPS and latest_tab is not None:
            self._push_tab(latest_tab)
        elif adapter is not None:
            self._push_adapter_tab(adapter, event)
        else:
            self._push_window(event)

    def _on_browser_tab_changed(self, event: BrowserTabChanged):
        browser_window_key = (event.connection_id, event.window_id)

        if self._current_app in TAB_EXTENSION_APPS:
            self._kwin_window_for_browser_window[browser_window_key] = self._current_window_id

        kwin_window_id = self._kwin_window_for_browser_window.get(browser_window_key)

        if kwin_window_id is not None:
            self._latest_tab_by_kwin_window[kwin_window_id] = event

        if self._current_app in TAB_EXTENSION_APPS:
            self._push_tab(event)

    def _on_window_closed(self, event: WindowClosed):
        self._history.mark_window_dead(event.window_id)

        # Drop it from the tab caches too - otherwise a later refocus of a
        # *different* window that happens to reuse this slot could never
        # actually collide (KWin ids aren't reused), but leaving a stale
        # closed-window entry lying around serves no purpose either way.
        self._latest_tab_by_kwin_window.pop(event.window_id, None)
        self._latest_adapter_restore_by_kwin_window.pop(event.window_id, None)

    def _on_browser_tab_closed(self, event: BrowserTabClosed):
        # Find every restore_id this (connection, tab) has ever been
        # recorded under. In practice there's only ever one, but nothing
        # guarantees that, so this is a filter rather than a fixed lookup.
        for kwin_window_id, cached in list(self._latest_tab_by_kwin_window.items()):
            if cached.connection_id == event.connection_id and cached.tab_id == event.tab_id:
                del self._latest_tab_by_kwin_window[kwin_window_id]

        # restore_id is "{browser}:{connection_id}:{tab_id}" - the browser
        # family name isn't known here, so mark dead by suffix match (with
        # a leading ":" to anchor it at a field boundary) against the whole
        # history rather than reconstructing the exact string.
        restore_id_suffix = f":{event.connection_id}:{event.tab_id}"

        for item in self._history.all_items():
            if item.restore_id is not None and item.restore_id.endswith(restore_id_suffix):
                self._history.mark_tab_dead(item.restore_id)

    def _on_window_caption_changed(self, event: WindowCaptionChanged):
        # See _on_focus_changed - a dialog's caption changing is just as
        # misattributable as its focus gain would be.
        if not event.normal:
            return

        # Only means anything for the window that's actually focused right
        # now - a caption change on a background window isn't a navigation,
        # and _current_window_id is the same liveness signal _on_focus_changed
        # already relies on.
        if event.window_id != self._current_window_id:
            return

        adapter = ADAPTERS_BY_APP.get(event.app)

        if adapter is None:
            return

        self._push_adapter_tab(adapter, event)

    def _push_adapter_tab(self, adapter, event):
        # title is passed alongside pid for adapters (qpdfview) that have
        # no D-Bus query for "what's currently active" at all and must
        # resolve the active tab from the caption text itself - Kate and
        # Konsole both ignore it, since they can query fresher state
        # directly by pid instead.
        restore_id = adapter.resolve_restore_id(event.pid, event.title)

        if restore_id is None:
            self._push_window(event)
            return

        self._latest_adapter_restore_by_kwin_window[event.window_id] = restore_id

        self._history.push(FocusItem(
            app=event.app,
            window_id=event.window_id,
            title=event.title,
            restore_type=adapter.restore_type,
            restore_id=restore_id,
            timestamp=event.timestamp,
        ))

    def _push_window(self, event: FocusChanged):
        self._history.push(FocusItem(
            app=event.app,
            window_id=event.window_id,
            title=event.title,
            timestamp=event.timestamp,
        ))

    def _push_tab(self, tab_event: BrowserTabChanged):
        self._history.push(FocusItem(
            app=self._current_app,
            window_id=self._current_window_id,
            title=tab_event.title,
            restore_type="browser_tab",
            restore_id=f"{tab_event.browser}:{tab_event.connection_id}:{tab_event.tab_id}",
            timestamp=tab_event.timestamp,
        ))

    def back(self):
        return self._skip_noop_entries(self._history.back)

    def forward(self):
        return self._skip_noop_entries(self._history.forward)

    def _skip_noop_entries(self, step):
        item = step()

        while item is not None and self._is_noop_window_entry(item):
            item = step()

        return item

    def _is_noop_window_entry(self, item: FocusItem) -> bool:
        # A plain window-level entry (no specific tab/session captured -
        # see the fallbacks in _push_adapter_tab/_on_focus_changed) is only
        # a guaranteed no-op if we ALSO hold more specific info for this
        # exact window (a real browser tab or adapter session) - that's
        # the case this exists for: bouncing between a stale fallback
        # entry and the adjacent real tab/session entry for a window that
        # never lost focus, which would otherwise make back/forward look
        # completely stuck even though a genuinely different window sits
        # one step further out.
        #
        # Without a more specific entry on record, this fallback IS the
        # only representation of that window's history - e.g. Konsole's
        # D-Bus call failed, or the browser extension never reported a
        # tab - and skipping it would silently swallow the one real
        # position we have for it (see test_dead_entry_skip.py's Konsole
        # entry, which must remain reachable).
        if item.restore_type is not None or item.window_id != self._current_window_id:
            return False

        return (
            item.window_id in self._latest_tab_by_kwin_window
            or item.window_id in self._latest_adapter_restore_by_kwin_window
        )

    def peek(self, direction: str, count: int):
        """
        Non-mutating preview of up to `count` valid steps from the
        current position in `direction`, for the overlay (see
        core/overlay_controller.py) to show where the following taps of
        the shortcut would land.

        Reuses back()/forward() themselves - not HistoryManager's raw
        back()/forward() - so the exact same dead-entry/no-op-window
        skipping rules apply here as they would to a real navigation;
        otherwise the overlay could preview/highlight an entry that a
        real step() in the same direction would then skip straight past,
        landing somewhere else than what was shown. The walk state is
        snapshotted first and always restored afterwards (even if a
        caller's `count` overshoots the end of the list) so peeking never
        has a side effect of its own.
        """
        step = self.back if direction == "back" else self.forward
        saved_walk = self._history.snapshot_walk()
        items = []

        try:
            for _ in range(count):
                item = step()
                if item is None:
                    break
                items.append(item)
        finally:
            self._history.restore_walk(saved_walk)

        return items

    def walk_view(self, count: int):
        """
        The MRU list as a switcher should render it: up to `count` entries
        counted from the FRONT of the list, plus which of those rows the
        in-progress walk is currently standing on.

        Deliberately not "the next `count` entries from wherever the walk
        is". That was the first version, and it made the panel a sliding
        window with the highlight pinned to row 0, so every tap scrolled
        the whole list up by one and the entry you had just walked away
        from vanished off the top - the one entry a bounce depends on
        being able to see. Observed live and misread as entries appearing
        from nowhere, which is fair, because between two gestures the
        commit reorders the list underneath a view that never showed the
        reordered part.

        Rendering from the front instead keeps the list still and moves
        the highlight down it, which is what Alt+Tab does and what makes
        the reordering legible.

        Walks with back() rather than the raw history so dead and no-op
        entries are skipped exactly as a real navigation would skip them -
        otherwise the panel could show a row that no tap can ever land on.
        Returns (entries, highlight_index), with highlight_index -1 when
        there is nothing to show.
        """
        saved_walk = self._history.snapshot_walk()

        try:
            target = self._history.walk_position()

            # Re-run the walk from the front so the rows come out in
            # rendered order. The activation set starts empty because
            # nothing here activates anything.
            self._history.restore_walk((0, set()))

            first = self._history.current

            if first is None:
                return [], -1

            entries = [first]
            highlight = 0 if target == 0 else -1

            while True:
                item = self.back()

                if item is None:
                    break

                entries.append(item)

                if self._history.walk_position() == target:
                    highlight = len(entries) - 1

                # Keep going past `count` only while still hunting for the
                # highlighted row, so a walk deeper than the panel can show
                # is still locatable rather than silently unhighlighted.
                if highlight != -1 and len(entries) >= count:
                    break
        finally:
            self._history.restore_walk(saved_walk)

        if len(entries) > count:
            # Scroll the window down just far enough to keep the highlight
            # on the last row rather than off the bottom.
            start = max(0, highlight - count + 1)
            entries = entries[start:start + count]
            highlight -= start

        return entries, highlight

    def step(self, direction: str):
        """
        Advance an in-progress gesture by one entry and return where it
        landed, for the caller to activate. Deliberately does NOT reorder
        history - under MRU ordering that only happens in commit_walk(),
        once the gesture has actually finished. See HistoryManager's
        docstring for why reordering on every step would make anything
        past the second entry unreachable.
        """
        return self.back() if direction == "back" else self.forward()

    def commit_walk(self):
        """
        End of gesture: promote wherever the walk landed to the front of
        the MRU list, so the next gesture counts from there. Fired by the
        caller after an idle dwell, since KGlobalAccel gives no
        modifier-release signal that could mark a gesture's end directly.
        """
        return self._history.commit()

    @property
    def current(self):
        return self._history.current
