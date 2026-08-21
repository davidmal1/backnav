from contextlib import contextmanager

from adapters.registry import ADAPTERS_BY_APP, ADAPTERS_BY_RESTORE_TYPE
from core.events.browser_disconnected import BrowserDisconnected
from core.events.browser_tab_changed import BrowserTabChanged
from core.events.browser_tab_closed import BrowserTabClosed
from core.events.browser_tabs_alive import BrowserTabsAlive
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
#
# Grouped by the `browser` family name the extension sends (see
# browser/*/background.js) rather than kept as one flat set, because
# "which app could this tab event have come from" is a question that has
# to be answerable per event - see _may_own() and the misattribution it
# exists to prevent.
TAB_EXTENSION_APPS_BY_FAMILY = {
    "chromium": {
        "brave-browser",
        "vivaldi-stable",
        "Vivaldi-snap",
        "google-chrome",
        "chromium-browser",
        "chromium",
        "microsoft-edge",
    },
    "firefox": {
        "firefox",
        "firefox_firefox",
    },
    # Confirmed live via the KWin script's own event log.
    #
    # Both spellings are real and depend on packaging, not version: the
    # deb reports "thunderbird" and the snap "thunderbird_thunderbird" -
    # the same doubled shape as firefox_firefox above, seen on a clean
    # Kubuntu install 2026-08-21. Missing one costs the whole feature and
    # says nothing: the extension connects, reports its tabs, and every
    # event is then discarded for want of a window to attribute it to.
    "thunderbird": {
        "thunderbird",
        "thunderbird_thunderbird",
    },
}

TAB_EXTENSION_APPS = set().union(*TAB_EXTENSION_APPS_BY_FAMILY.values())

# How many tab events a connection may have discarded before the daemon
# says so. Not one: a browser that has not been focused yet legitimately
# fails to bind, and a connection that is merely early must not be
# reported as broken. A genuinely unrecognised resource class never stops
# accumulating, so any small number separates the two.
DISCARDS_BEFORE_COMPLAINING = 3


def _may_own(app, family):
    """
    Could a window of resource class `app` be the one that sent a tab
    event from extension family `family`?

    The guard against cross-app tab misattribution. Reported live
    (2026-08-12) as a "thunderbird - SnakeoilOS" row sitting directly
    above the real "brave-browser - SnakeoilOS": a BACKGROUND Brave tab
    refreshing its title while Thunderbird had focus was stamped with
    Thunderbird's identity, because the only test being applied was "is
    the focused app *a* tab-extension app", which Thunderbird is.

    Unknown families are permitted against any tab-extension app rather
    than rejected, so adding a browser to browser/ can't silently break
    tab tracking until someone remembers to update this table. The
    window-identity checks in _on_browser_tab_changed still apply, so
    permissiveness here costs correctness only in the narrow case of two
    same-family browsers (Vivaldi and Brave both report "chromium").
    """
    if app not in TAB_EXTENSION_APPS:
        return False

    owners = TAB_EXTENSION_APPS_BY_FAMILY.get(family)

    return True if owners is None else app in owners


def _tab_owner(item):
    """
    Split a browser-tab entry's restore_id back into
    (connection_id, tab_id), or None if this entry is not a browser tab.

    Gated on restore_type rather than on the shape of the string, which
    is not safe to infer: Konsole's restore_id is "konsole:{pid}:
    {session_id}", three colon-separated fields with an integer last, so
    it parses perfectly as a browser tab. Nothing but the restore_type
    distinguishes them. That mis-parse would currently be caught by the
    connection_id comparison downstream - a pid is never a UUID - but
    only by luck, and it would hand a Konsole session to whichever
    browser happened to reconnect.

    Past the type check the format is guaranteed by _push_tab, so this
    does not defend against malformed ids it cannot receive.
    """
    if item.restore_type != "browser_tab":
        return None

    _browser, connection_id, tab_id = item.restore_id.split(":", 2)

    return connection_id, int(tab_id)


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

        # Support for _report_discard(): how many tab events each
        # connection has had thrown away without ever binding, and which
        # (resource class, family) pairs have already been complained
        # about. See there for why it says anything at all.
        self._discards_by_connection = {}
        self._discards_reported = set()

        # KWin window_id -> latest known adapter restore_id for that
        # window (Konsole session, etc). Mirrors _latest_tab_by_kwin_window
        # for non-browser tabbed apps; kept separate since the two paths
        # populate it differently (adapter resolution vs. browser
        # extension messages) but serve the exact same purpose below.
        self._latest_adapter_restore_by_kwin_window = {}

        # Adapter liveness snapshot for the walk currently in progress, or
        # None when no walk is open. See _liveness_scope().
        self._live_targets = None

        event_bus.subscribe(FocusChanged, self._on_focus_changed)
        event_bus.subscribe(BrowserTabChanged, self._on_browser_tab_changed)
        event_bus.subscribe(WindowClosed, self._on_window_closed)
        event_bus.subscribe(BrowserTabClosed, self._on_browser_tab_closed)
        event_bus.subscribe(BrowserTabsAlive, self._on_browser_tabs_alive)
        event_bus.subscribe(BrowserDisconnected, self._on_browser_disconnected)
        event_bus.subscribe(WindowCaptionChanged, self._on_window_caption_changed)

    def seed(self, windows):
        """
        Populate history from KWin's current window list.

        History is learned from focus events and nothing else, so a daemon
        that starts mid-session knows nothing: journalctl is followed with
        `-n 0` (no backlog), and the KWin script emits its initial
        activeWindow only when the SCRIPT loads, not when this reconnects.
        The practical effect was that back/forward did nothing at all after
        a daemon restart until the user had switched between two windows by
        mouse - which is survivable while BackNav is a second switcher, and
        not survivable at all if it is bound to Alt+Tab.

        Seeded window-level only. Resolving each window's tab would mean a
        D-Bus round trip per window at startup, and it is unnecessary: the
        first real focus or tab event for a window supersedes its seeded
        entry (see HistoryManager.push), so the detail arrives as soon as
        it matters and costs nothing before then.

        Ordered oldest-first by the caller, so the most recently raised
        window ends up at the front where MRU expects it.
        """
        # Guarded on history being EMPTY rather than on a "have I seeded
        # yet" flag, and that distinction is the whole fix.
        #
        # A once-only flag seeds at the first opportunity, which at login
        # is the worst possible moment: the daemon and KWin start
        # together, so the panel answers before the session has opened
        # anything. Observed 2026-08-19 - the seed went out, reported
        # nothing, and the flag then blocked every later attempt, so a
        # freshly booted session knew only the windows it had watched the
        # user focus by hand.
        #
        # Empty history is the honest condition. It is true at login until
        # something real exists to seed, so the panel keeps offering and
        # the first offer with windows in it lands. It goes false the
        # moment there is anything at all, which is what stops a seed from
        # ever overwriting navigation the user has actually done.
        if self._history.has_live_items():
            return

        for window in windows:
            window_id = window.get("windowId")
            app = window.get("app")

            if not window_id or not app:
                continue

            self._history.push(FocusItem(
                app=app,
                window_id=window_id,
                title=window.get("title") or app,
                restore_type=None,
                restore_id=None,
            ))

    @property
    def seeded(self) -> bool:
        """
        Whether history holds anything at all, which is what the panel
        uses to decide whether to offer KWin's window list.

        Not a record of having been seeded: a seed that arrived empty has
        achieved nothing and must not count. Nor is it "history is not
        empty" - at login KDE's splash screen takes focus as a normal
        window and then closes, and a dead entry left behind by it would
        otherwise be enough to declare the daemon populated. See
        HistoryManager.has_live_items.
        """
        return self._history.has_live_items()

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

        if self._may_bind(browser_window_key, event.browser):
            self._kwin_window_for_browser_window[browser_window_key] = self._current_window_id

        kwin_window_id = self._kwin_window_for_browser_window.get(browser_window_key)

        if kwin_window_id is None:
            self._report_discard(event)
        else:
            # It bound, so any earlier discards were the ordinary
            # before-first-focus kind and must not accumulate towards a
            # complaint.
            self._discards_by_connection.pop(event.connection_id, None)

        if kwin_window_id is not None:
            self._latest_tab_by_kwin_window[kwin_window_id] = event

        # Only a tab belonging to the window that currently HAS focus is a
        # navigation. Everything else is background chatter - a title
        # refresh, a page finishing load, a tab activating in another
        # window - and stamping that with the focused window's identity is
        # what produced the "thunderbird - SnakeoilOS" corruption. Note
        # this is deliberately window identity, not app identity: two
        # windows of the same browser must not adopt each other's tabs
        # either.
        if kwin_window_id is not None and kwin_window_id == self._current_window_id:
            self._push_tab(event)

    def _report_discard(self, event):
        """
        Say so, once, when a tab event cannot be attributed to any window.

        This is the failure that hid the thunderbird_thunderbird bug for
        as long as it did. An unrecognised resource class means every tab
        event from that extension is dropped here, which disables tab
        navigation for the application completely - and every OTHER signal
        says things are fine. The extension connects, enumerates its tabs
        and reports each switch; the connection log is clean. What you see
        is the plain window-level row, frozen on whatever caption the
        window had when it was focused, because switching tabs inside a
        focused window raises no KWin event to refresh it. That reads as
        cosmetic staleness rather than an absent feature, and sends you
        looking anywhere but here.

        The two facts that identify it are both in hand at this moment:
        the focused window's class, and the family claiming the tab. So
        say them.

        Once per pair, not per event - tab events are continuous, and a
        line each would bury the one that matters. Deliberately NOT a
        prompt to add more names to TAB_EXTENSION_APPS_BY_FAMILY on
        suspicion: every entry there was seen live, which is what makes
        the table worth trusting. This reports what was actually
        observed, and someone decides.
        """
        count = self._discards_by_connection.get(event.connection_id, 0) + 1
        self._discards_by_connection[event.connection_id] = count

        if count < DISCARDS_BEFORE_COMPLAINING:
            return

        pair = (self._current_app, event.browser)

        if pair in self._discards_reported:
            return

        self._discards_reported.add(pair)

        print(
            f"backnav: discarding {event.browser} tab events - focused "
            f"window is {self._current_app!r}, which no extension family "
            f"claims. Tab navigation is inactive for it; window-level "
            f"still works.",
            flush=True,
        )

    def _may_bind(self, browser_window_key, family):
        """
        Whether the focused KWin window can be recorded as the owner of
        this browser window. Learned on first sight and then effectively
        permanent, so a wrong answer here corrupts the history until the
        daemon restarts - hence three separate conditions rather than the
        single "is a tab app" test this replaces.
        """
        if not _may_own(self._current_app, family):
            return False

        # Already bound. Re-binding on every event is what let a
        # background tab drag its browser window's mapping over to
        # whatever was focused at the time.
        existing = self._kwin_window_for_browser_window.get(browser_window_key)

        if existing is not None:
            return False

        # A KWin window hosts exactly one browser window, so if this one
        # is already spoken for, we are looking at someone else's event.
        # Catches the same-family case (_may_own can't): Brave's first
        # tab event arriving while Vivaldi happens to be focused.
        return self._current_window_id not in set(
            self._kwin_window_for_browser_window.values()
        )

    def _on_window_closed(self, event: WindowClosed):
        self._history.mark_window_dead(event.window_id)

        # Drop it from the tab caches too - otherwise a later refocus of a
        # *different* window that happens to reuse this slot could never
        # actually collide (KWin ids aren't reused), but leaving a stale
        # closed-window entry lying around serves no purpose either way.
        self._latest_tab_by_kwin_window.pop(event.window_id, None)
        self._latest_adapter_restore_by_kwin_window.pop(event.window_id, None)

        # And the binding that named it. A leak rather than a wedge -
        # KWin never reuses a window id, so a binding to a dead window
        # can't block a live one the way a dead CONNECTION's can (see
        # _on_browser_disconnected) - but it would otherwise sit in the
        # "already spoken for" set forever, which is exactly the state
        # that made the connection case so hard to see.
        for key, kwin_window_id in list(self._kwin_window_for_browser_window.items()):
            if kwin_window_id == event.window_id:
                del self._kwin_window_for_browser_window[key]

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

    def _on_browser_disconnected(self, event: BrowserDisconnected):
        """
        Forget everything learned from a connection that has gone away.

        The window binding is the load-bearing part. It is learned once
        and never revised, and _may_bind() refuses to bind a KWin window
        that is already spoken for - so a browser returning under a NEW
        instanceId (extension reloaded, reinstalled, or loaded from a
        different directory) finds its window permanently claimed by the
        dead connection and can never bind again. Tab tracking for that
        browser is then dead until the daemon restarts, silently:
        switching tabs records nothing, and refocusing the window keeps
        re-pushing whatever tab was cached before the swap.

        Reported live (2026-08-12) as one Brave tab pinned to the top of
        the switcher while the tab actually being used sat eight rows
        down, untouched since the reload.

        An MV3 worker being evicted produces this too, under the same
        instanceId, and that is fine: the binding is re-learned from the
        first tab event that arrives while the browser is focused, which
        the extension sends on connect.
        """
        for key in list(self._kwin_window_for_browser_window):
            if key[0] == event.connection_id:
                del self._kwin_window_for_browser_window[key]

        # The cached tab goes too. It is only ever a guess about a
        # background window, and after a disconnect it is a guess made
        # from information we can no longer confirm - keeping it means
        # refocusing the browser pushes a tab that may not be active any
        # more, as a real history entry. The cost of dropping it is one
        # window-level entry until the extension reports again on
        # connect, which _is_noop_window_entry already knows to skip.
        for kwin_window_id, cached in list(self._latest_tab_by_kwin_window.items()):
            if cached.connection_id == event.connection_id:
                del self._latest_tab_by_kwin_window[kwin_window_id]

    def _on_browser_tabs_alive(self, event: BrowserTabsAlive):
        """
        Reconcile history against the tab set an extension can actually
        see, which it sends on every (re)connect.

        BrowserTabClosed is best-effort and is *provably* dropped in one
        routine case: an MV3 service worker respawns on tabs.onRemoved,
        runs connect() at top level, and the send that follows finds the
        socket still CONNECTING and returns without sending. The
        extensions already compensate for that on the tab_changed side by
        re-reporting the active tab on open - but a closure has no such
        recovery, because nothing later ever mentions the tab again.
        Reported live (2026-08-12) as a closed Brave tab still sitting in
        the chooser.

        So closures are treated as a fast path, not as the source of
        truth. Anything this connection no longer lists is dead however
        its closure went missing - worker respawn, daemon downtime, a tab
        id changed by Chrome's memory-saver discard (tabs.onReplaced,
        which nothing listens for), or a bug not yet found.

        Both directions, deliberately: see mark_tab_alive().
        """
        for item in self._history.all_items():
            owner = _tab_owner(item)

            if owner is None:
                continue

            connection_id, tab_id = owner

            # Only this connection's tabs. Another browser's entries are
            # not this extension's to have an opinion about, and marking
            # them dead because they are missing from ITS list would wipe
            # every other browser's history on each reconnect.
            if connection_id != event.connection_id:
                continue

            if tab_id in event.tab_ids:
                self._history.mark_tab_alive(item.restore_id)
            else:
                self._history.mark_tab_dead(item.restore_id)

        # Same purge _on_browser_tab_closed does, for the same reason:
        # a cached tab that no longer exists must not be resurrected by
        # the next refocus of its window.
        for kwin_window_id, cached in list(self._latest_tab_by_kwin_window.items()):
            if (
                cached.connection_id == event.connection_id
                and cached.tab_id not in event.tab_ids
            ):
                del self._latest_tab_by_kwin_window[kwin_window_id]

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
        with self._liveness_scope():
            item = step()

            while item is not None and (
                self._is_noop_window_entry(item)
                or self._is_closed_adapter_tab(item)
            ):
                item = step()

            return item

    @contextmanager
    def _liveness_scope(self):
        """
        Holds one adapter liveness snapshot open for everything inside the
        block, however many entries get stepped over.

        Re-entrant on purpose, and that re-entrancy is the whole point:
        walk_view()/peek() render the overlay by calling back() in a loop,
        and the overlay polls them every 80ms for the length of a gesture.
        Without an outer scope each of those inner back() calls would open
        a snapshot of its own - a qdbus6 subprocess plus a SQLite read per
        row, ~12x a second. With one, a whole render costs a single query
        (measured 6ms against the real qpdfview).

        Only the outermost scope owns the snapshot; nested ones reuse it
        and leave the teardown to the owner.
        """
        outermost = self._live_targets is None

        if outermost:
            self._live_targets = {}

        try:
            yield
        finally:
            # Always dropped on the way out rather than kept warm: a tab
            # closed between two gestures must be noticed by the next one.
            if outermost:
                self._live_targets = None

    def _is_closed_adapter_tab(self, item: FocusItem) -> bool:
        # The dead-window/dead-tab sets in HistoryManager only ever learn
        # about closures something reports: KWin's WindowClosed for whole
        # windows, the extension's BrowserTabClosed for browser tabs.
        # Adapter-tracked apps emit no close event of any kind - closing a
        # qpdfview tab leaves its window wide open - so their entries can
        # never be marked dead that way, and restoring one doesn't harmlessly
        # do nothing: qpdfview's jumpToPageOrOpenInNewTab and Kate's openUrl
        # both REOPEN a file that's no longer there. Hence asking the app
        # directly, at navigation time, for adapters that can answer.
        #
        # Deliberately not cached into _dead_tabs. A restore_id names a
        # file path, so reopening that same file by hand would produce the
        # identical id - and "once dead, always dead" would then skip right
        # past the reopened tab forever.
        adapter = ADAPTERS_BY_RESTORE_TYPE.get(item.restore_type)

        if adapter is None or not hasattr(adapter, "live_targets"):
            return False

        if item.restore_type not in self._live_targets:
            self._live_targets[item.restore_type] = adapter.live_targets()

        targets = self._live_targets[item.restore_type]

        # Couldn't tell (app not running, D-Bus call failed, database
        # unreadable). Assume alive: landing on a stale entry is a much
        # smaller failure than refusing to navigate anywhere at all.
        if targets is None:
            return False

        return adapter.target_of(item.restore_id) not in targets

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

        # One liveness snapshot for the whole preview rather than one per
        # previewed entry - this runs on the overlay's 80ms poll.
        with self._liveness_scope():
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

            # One liveness snapshot for the whole render rather than one
            # per row - see _liveness_scope(). The overlay calls this every
            # 80ms for the length of a gesture, so per-row would mean a
            # qdbus6 subprocess per row, ~12x a second.
            with self._liveness_scope():
                while True:
                    item = self.back()

                    if item is None:
                        break

                    entries.append(item)

                    if self._history.walk_position() == target:
                        highlight = len(entries) - 1

                    # Keep going past `count` only while still hunting for
                    # the highlighted row, so a walk deeper than the panel
                    # can show is still locatable rather than silently
                    # unhighlighted.
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

    def abandon_walk(self):
        """
        Escape out of the focused chooser: go back to where the gesture
        started and leave the MRU order untouched. See
        HistoryManager.abandon().
        """
        return self._history.abandon()

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
