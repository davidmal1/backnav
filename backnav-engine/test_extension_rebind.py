"""
A browser coming back under a new instanceId must be able to re-bind.

Reported live (2026-08-12): after removing the unpacked extension and
re-adding it from a different directory - which gives it a new
instanceId - the switcher pinned one stale Brave tab at the top of the
list and never noticed another tab switch in that browser again. The tab
actually being used sat eight rows down, untouched since the reload.

The cause is that the window binding is learned once and never revised,
and _may_bind() refuses to bind a KWin window that is already spoken
for. The dead connection still owned Brave's window, so the new
connection could never claim it - permanently, until a daemon restart.
Every refocus then re-pushed the tab cached before the swap, which is
why one stale entry kept returning to the top.

Nothing here is exotic to an extension reload: an MV3 worker eviction
disconnects too, and a browser restart or a cleared profile produces a
new instanceId the same way.
"""

from core.events.browser_disconnected import BrowserDisconnected
from core.events.browser_tab_changed import BrowserTabChanged
from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.events.window_closed import WindowClosed
from core.navigation_engine import NavigationEngine

# ---- The reported scenario -------------------------------------------

event_bus = EventBus()
engine = NavigationEngine(event_bus)

event_bus.publish(FocusChanged(app="brave-browser", window_id="brave-kwin", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="old-uuid", window_id=10,
    tab_id=1, title="Extensions",
))

assert engine.current.title == "Extensions", engine.current.title

# The extension is removed and re-added from another directory. The
# daemon is NOT restarted, so it still holds everything it learned.
event_bus.publish(BrowserDisconnected(connection_id="old-uuid"))

# Same browser, same KWin window, brand new instanceId.
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="new-uuid", window_id=10,
    tab_id=2, title="ABC News",
))

assert engine.current.title == "ABC News", (
    "the reloaded extension could not re-bind - tab switches are invisible: "
    f"{engine.current.title}"
)

# Bouncing between two tabs must keep BOTH at the top of the MRU list.
# The reported symptom was one pinned at row 0 and the other stranded
# near the bottom, which is what "we never recorded the second one"
# looks like from the outside.
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="new-uuid", window_id=10,
    tab_id=1, title="Extensions",
))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="new-uuid", window_id=10,
    tab_id=2, title="ABC News",
))

entries, _ = engine.walk_view(8)
top_two = [entry.title for entry in entries[:2]]

assert set(top_two) == {"ABC News", "Extensions"}, (
    f"bouncing between two tabs did not keep both at the top: "
    f"{[e.title for e in entries]}"
)

# ---- The stale cached tab goes too -----------------------------------
#
# Refocusing the window after the swap must not resurrect the tab that
# was cached under the dead connection - that is the mechanism that kept
# dragging "Extensions" back to row 0.

event_bus = EventBus()
engine = NavigationEngine(event_bus)

event_bus.publish(FocusChanged(app="brave-browser", window_id="brave-kwin", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="old-uuid", window_id=10,
    tab_id=1, title="Stale Tab",
))
event_bus.publish(FocusChanged(app="Claude", window_id="claude-kwin", title="Claude"))

event_bus.publish(BrowserDisconnected(connection_id="old-uuid"))
event_bus.publish(FocusChanged(app="brave-browser", window_id="brave-kwin", title="Brave"))

assert engine.current.title != "Stale Tab", \
    "a tab cached under a dead connection was pushed as a live entry"
assert engine.current.restore_type is None, (
    "expected a plain window entry until the new extension reports: "
    f"{engine.current}"
)

# ---- One browser disconnecting must not unbind another ---------------

event_bus = EventBus()
engine = NavigationEngine(event_bus)

event_bus.publish(FocusChanged(app="brave-browser", window_id="brave-kwin", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave", window_id=10,
    tab_id=1, title="Brave Tab",
))
event_bus.publish(FocusChanged(app="Vivaldi-snap", window_id="vivaldi-kwin", title="Vivaldi"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="vivaldi", window_id=20,
    tab_id=1, title="Vivaldi Tab",
))

event_bus.publish(BrowserDisconnected(connection_id="vivaldi"))

# Brave's binding must be untouched: a tab switch there still lands.
event_bus.publish(FocusChanged(app="brave-browser", window_id="brave-kwin", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave", window_id=10,
    tab_id=2, title="Brave Tab Two",
))

assert engine.current.title == "Brave Tab Two", (
    "Vivaldi disconnecting unbound Brave as well: " f"{engine.current.title}"
)

# The check above proves less than it looks: Brave was FOCUSED when its
# next tab event arrived, so even if the disconnect had wrongly dropped
# Brave's binding, _may_bind() would have silently re-learned it before
# anything could observe the loss. A too-aggressive purge repairs itself
# there and the test still passes.
#
# The two checks below remove that escape route by keeping focus on some
# other app, which is the one situation with no route back: re-binding
# requires the browser to be the focused window.


def two_browsers():
    """Brave and Vivaldi both bound and cached, focus parked elsewhere."""
    event_bus = EventBus()
    engine = NavigationEngine(event_bus)

    event_bus.publish(FocusChanged(app="brave-browser", window_id="brave-kwin", title="Brave"))
    event_bus.publish(BrowserTabChanged(
        browser="chromium", connection_id="brave", window_id=10,
        tab_id=1, title="Brave Tab",
    ))
    event_bus.publish(FocusChanged(app="Vivaldi-snap", window_id="vivaldi-kwin", title="Vivaldi"))
    event_bus.publish(BrowserTabChanged(
        browser="chromium", connection_id="vivaldi", window_id=20,
        tab_id=1, title="Vivaldi Tab",
    ))
    event_bus.publish(FocusChanged(app="Claude", window_id="claude-kwin", title="Claude"))

    return event_bus, engine


# Brave's BINDING must survive: a background tab event still has to be
# attributed to Brave's window while Claude holds focus.
event_bus, engine = two_browsers()

event_bus.publish(BrowserDisconnected(connection_id="vivaldi"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave", window_id=10,
    tab_id=3, title="Brave Background Tab",
))
event_bus.publish(FocusChanged(app="brave-browser", window_id="brave-kwin", title="Brave"))

assert engine.current.title == "Brave Background Tab", (
    "Vivaldi's disconnect dropped Brave's binding, so a background tab "
    f"event could not be attributed to any window: {engine.current}"
)

# Brave's CACHED TAB must survive too. Same setup, but nothing re-caches
# after the disconnect - so refocusing Brave falls back to a plain window
# entry if the purge took more than it owned.
event_bus, engine = two_browsers()

event_bus.publish(BrowserDisconnected(connection_id="vivaldi"))
event_bus.publish(FocusChanged(app="brave-browser", window_id="brave-kwin", title="Brave"))

assert engine.current.restore_type == "browser_tab", (
    "Vivaldi's disconnect purged Brave's cached tab, so refocusing Brave "
    f"produced a plain window entry: {engine.current}"
)
assert engine.current.title == "Brave Tab", engine.current.title

# ---- A closed window releases its binding ----------------------------
#
# Hygiene rather than a wedge - KWin never reuses a window id - but the
# "already spoken for" set is exactly what made the connection bug
# invisible, so it should not accumulate entries naming dead windows.

event_bus = EventBus()
engine = NavigationEngine(event_bus)

event_bus.publish(FocusChanged(app="brave-browser", window_id="brave-kwin", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave", window_id=10,
    tab_id=1, title="Brave Tab",
))

assert engine._kwin_window_for_browser_window

event_bus.publish(WindowClosed(window_id="brave-kwin"))

assert not engine._kwin_window_for_browser_window, (
    "a closed window left its binding behind: "
    f"{engine._kwin_window_for_browser_window}"
)

print("OK")
