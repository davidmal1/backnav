"""
A closed browser tab must not survive in the switcher when its
BrowserTabClosed went missing.

Reported live (2026-08-12): the chooser listed "brave-browser - Chris
Scott says players 'deserve the right to pri..." for a tab that had
already been closed. The daemon handles a DELIVERED closure correctly
(test_dead_entry_skip.py proves that), so the failure is upstream - the
message never arrived.

That is not a hypothetical. An MV3 service worker respawns ON the
tabs.onRemoved event and runs connect() at top level, so publishClosed()
finds the socket still CONNECTING and returns without sending. The
extensions already compensate for this on the tab_changed side by
re-reporting the active tab on open; a closure had no equivalent, and
unlike a missed switch nothing later ever mentions the tab again, so the
entry was permanent.

The fix is to stop treating closures as the source of truth: each
extension sends its full live tab set on connect and the daemon
reconciles against it.
"""

from core.events.browser_tab_changed import BrowserTabChanged
from core.events.browser_tabs_alive import BrowserTabsAlive
from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.navigation_engine import NavigationEngine


def titles_walking_back(engine):
    # Reset the walk at both ends. back() is a real navigation, not a
    # query - it leaves the cursor wherever it stopped, so without this a
    # second call would start from the end of the list and report nothing
    # at all (which silently passes any "X is not in the list" assertion).
    engine.abandon_walk()

    titles = []

    while True:
        item = engine.back()

        if item is None:
            break

        titles.append(item.title)

    engine.abandon_walk()

    return titles


# ---- The reported scenario ------------------------------------------
#
# Claude, then two Brave tabs. One Brave tab is then closed WITHOUT the
# daemon ever hearing about it.

event_bus = EventBus()
engine = NavigationEngine(event_bus)

event_bus.publish(FocusChanged(app="Claude", window_id="1", title="Claude"))
event_bus.publish(FocusChanged(app="brave-browser", window_id="2", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="conn-1", window_id=10,
    tab_id=1, title="ABC Sport",
))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="conn-1", window_id=10,
    tab_id=2, title="Chris Scott",
))
event_bus.publish(FocusChanged(app="Claude", window_id="1", title="Claude"))

titles = titles_walking_back(engine)

# The bare "Brave" window entry is gone: the first tab entry for that
# window superseded it (see HistoryManager.push), so one Brave window
# yields one row per tab rather than a row per tab plus a spare.
assert titles == ["Chris Scott", "ABC Sport"], titles

# The Chris Scott tab is closed and the notification is LOST - the worker
# was respawning, so nothing is published here at all. Then the worker
# finishes connecting and reports what actually exists.
event_bus.publish(BrowserTabsAlive(connection_id="conn-1", tab_ids=frozenset({1})))

titles = titles_walking_back(engine)

assert "Chris Scott" not in titles, \
    f"closed tab survived a lost close notification: {titles}"
assert titles == ["ABC Sport"], titles

# ---- Live tabs are left strictly alone -------------------------------
#
# The reconciliation must not be a blunt "clear everything on reconnect":
# a second connect reporting the same live set must leave ABC Sport
# reachable, not quietly retire it too.

event_bus.publish(BrowserTabsAlive(connection_id="conn-1", tab_ids=frozenset({1})))

titles = titles_walking_back(engine)

assert titles == ["ABC Sport"], titles

# ---- A retired tab is not resurrected by refocusing its window -------
#
# The per-window "latest tab" cache is what lets refocusing a browser
# pick up tab activity that happened while it was in the background. If
# reconciliation leaves a retired tab sitting in there, the next focus
# event pushes it straight back in as the CURRENT entry - and
# walk_view() renders the current entry as row 0 without a liveness
# check, so the closed tab reappears at the top of the chooser.

event_bus = EventBus()
engine = NavigationEngine(event_bus)

event_bus.publish(FocusChanged(app="Claude", window_id="1", title="Claude"))
event_bus.publish(FocusChanged(app="brave-browser", window_id="2", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="conn-1", window_id=10,
    tab_id=2, title="Chris Scott",
))
event_bus.publish(FocusChanged(app="Claude", window_id="1", title="Claude"))

event_bus.publish(BrowserTabsAlive(connection_id="conn-1", tab_ids=frozenset({1})))

# Back to Brave, the ordinary way - by clicking it, not by navigating.
event_bus.publish(FocusChanged(app="brave-browser", window_id="2", title="Brave"))

assert engine.current.title != "Chris Scott", \
    "a retired tab came back as the current entry via the per-window cache"

entries, _ = engine.walk_view(8)
rendered = [item.title for item in entries]

assert "Chris Scott" not in rendered, f"retired tab rendered in the panel: {rendered}"

# ---- One browser cannot retire another's tabs ------------------------
#
# Each extension only knows its OWN tabs. Marking anything it fails to
# mention as dead would wipe every other browser's history on every
# reconnect - and reconnects are routine, not exceptional.

event_bus = EventBus()
engine = NavigationEngine(event_bus)

event_bus.publish(FocusChanged(app="brave-browser", window_id="2", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave", window_id=10,
    tab_id=1, title="Brave Tab",
))
event_bus.publish(FocusChanged(app="firefox", window_id="3", title="Firefox"))
event_bus.publish(BrowserTabChanged(
    browser="firefox", connection_id="ff", window_id=20,
    tab_id=7, title="Firefox Tab",
))

# Firefox reconnects and reports only its own single tab. Brave's tab id
# is deliberately NOT in that set: ids are per-browser, so the ONLY thing
# stopping Firefox's list from retiring Brave's entire history is the
# connection scoping.
event_bus.publish(BrowserTabsAlive(connection_id="ff", tab_ids=frozenset({7})))

titles = titles_walking_back(engine)

assert "Brave Tab" in titles, f"another browser's tab was retired: {titles}"
assert "Firefox Tab" not in titles, \
    f"Firefox Tab should be the current entry, not a back target: {titles}"

# The per-window cache is scoped the same way, and for a reason of its
# own: it is what lets refocusing a browser resume at the tab it was on.
# Purging another browser's cache entry silently downgrades that window
# to a plain window-level entry - on every reconnect, which is routine.
event_bus.publish(FocusChanged(app="brave-browser", window_id="2", title="Brave"))

assert engine.current.restore_type == "browser_tab", (
    "refocusing Brave lost its tab-level entry to Firefox's reconnect: "
    f"{engine.current}"
)
assert engine.current.title == "Brave Tab", engine.current.title

# ---- Adapter entries are not mistaken for browser tabs ---------------
#
# Konsole's restore_id is "konsole:{pid}:{session_id}" - three
# colon-separated fields ending in an integer, i.e. structurally
# identical to "{browser}:{connection_id}:{tab_id}". Only restore_type
# tells them apart, so parsing by shape would hand a Konsole session to
# whichever browser reconnected next.

from core.models.focus_item import FocusItem
from core.navigation_engine import _tab_owner


def item(restore_type, restore_id):
    return FocusItem(
        app="x", window_id="1", title="x",
        restore_type=restore_type, restore_id=restore_id,
    )


assert _tab_owner(item("browser_tab", "chromium:conn-1:7")) == ("conn-1", 7)
assert _tab_owner(item(None, None)) is None
assert _tab_owner(item("konsole_tab", "konsole:1234:5")) is None, \
    "a Konsole session parsed as a browser tab"
assert _tab_owner(item("kate_document", "kate:1234:/tmp/a.txt")) is None
assert _tab_owner(item("qpdfview_tab", "qpdfview:3:/tmp/a.pdf")) is None

# The same hazard end to end, not just at the parser: a Konsole session
# whose pid/session pair happens to look like a tab must survive a
# browser's reconnect untouched.

event_bus = EventBus()
engine = NavigationEngine(event_bus)

konsole_entry = FocusItem(
    app="org.kde.konsole", window_id="9", title="journalctl",
    restore_type="konsole_tab", restore_id="konsole:1234:5",
)
engine._history.push(konsole_entry)

event_bus.publish(FocusChanged(app="Claude", window_id="1", title="Claude"))
event_bus.publish(BrowserTabsAlive(connection_id="1234", tab_ids=frozenset()))

titles = titles_walking_back(engine)

assert "journalctl" in titles, f"a Konsole session was retired by a browser: {titles}"

# ---- A wrongly-retired tab can come back -----------------------------
#
# The reconciliation corrects in both directions. If a race ever kills a
# live tab - the query is taken a moment before a tab is recorded, say -
# the next reconnect must be able to undo it, or the only cure is
# restarting the daemon.

event_bus = EventBus()
engine = NavigationEngine(event_bus)

event_bus.publish(FocusChanged(app="brave-browser", window_id="2", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="conn-1", window_id=10,
    tab_id=1, title="Real Tab",
))
event_bus.publish(FocusChanged(app="Claude", window_id="1", title="Claude"))

event_bus.publish(BrowserTabsAlive(connection_id="conn-1", tab_ids=frozenset()))

assert "Real Tab" not in titles_walking_back(engine)

event_bus.publish(BrowserTabsAlive(connection_id="conn-1", tab_ids=frozenset({1})))

assert "Real Tab" in titles_walking_back(engine), \
    "a tab retired by mistake could never come back"

print("OK")
