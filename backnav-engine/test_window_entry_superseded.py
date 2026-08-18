"""
A specific entry supersedes the plain window-level fallback for the same
window.

The fallback is written whenever a window takes focus before anything
more specific is known about it - a browser focused in the second before
its extension connects, most often. Left in place it becomes a second row
for one window, and the worse of the two: it carries no restore_id, so
selecting it raises the window and lands you on whatever tab is current
rather than the one it is labelled with.

Reported 2026-08-17 as duplicate Thunderbird rows. Made routine rather
than rare by seeding history at startup, which creates a fallback for
every window before any extension has said anything.

Three other tests assert this incidentally, by no longer listing the
fallback in their walks. None of them would fail for the right reason if
the rule were subtly wrong - hence this one.
"""

from core.events.browser_tab_changed import BrowserTabChanged
from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.navigation_engine import NavigationEngine


def titles(engine):
    return [item.title for item in engine._history.all_items()]


def fresh():
    bus = EventBus()
    return bus, NavigationEngine(bus)


# ---- the fallback goes when a tab entry for that window arrives -------

bus, engine = fresh()

bus.publish(FocusChanged(app="org.kde.kate", window_id="1", title="notes.md"))
bus.publish(FocusChanged(app="brave-browser", window_id="2", title="Brave"))

# Before the extension says anything, the fallback is all there is - and
# it must exist, or the window would be unreachable.
assert titles(engine) == ["Brave", "notes.md"], titles(engine)

bus.publish(BrowserTabChanged(browser="chromium", connection_id="c1",
                              window_id=99, tab_id=1, title="ABC Sport"))

assert titles(engine) == ["ABC Sport", "notes.md"], titles(engine)

# A second tab adds a row rather than replacing one - tabs are distinct
# targets from each other, unlike the fallback they replaced.
bus.publish(BrowserTabChanged(browser="chromium", connection_id="c1",
                              window_id=99, tab_id=2, title="Chris Scott"))

assert titles(engine) == ["Chris Scott", "ABC Sport", "notes.md"], titles(engine)

# ---- only the fallback for the SAME window ---------------------------

bus, engine = fresh()

bus.publish(FocusChanged(app="brave-browser", window_id="2", title="Brave"))
bus.publish(FocusChanged(app="firefox", window_id="3", title="Firefox"))
bus.publish(BrowserTabChanged(browser="firefox", connection_id="ff",
                              window_id=77, tab_id=1, title="Docs"))

# Firefox's fallback is superseded; Brave's is untouched, since nothing
# more specific is known about that window.
assert titles(engine) == ["Docs", "Brave"], titles(engine)

# ---- an app with no tabs keeps its fallback forever ------------------

bus, engine = fresh()

bus.publish(FocusChanged(app="org.kde.dolphin", window_id="1", title="Files"))
bus.publish(FocusChanged(app="org.kde.kate", window_id="2", title="notes.md"))

assert titles(engine) == ["notes.md", "Files"], titles(engine)

# ---- the reverse must NOT happen -------------------------------------

# A window-level focus event arriving after a tab entry - which happens
# every time you switch back to a browser - must not throw the tab entry
# away. That would be superseding the better information with the worse,
# and would make browser tabs unreachable the moment you revisited one.
bus, engine = fresh()

bus.publish(FocusChanged(app="brave-browser", window_id="2", title="Brave"))
bus.publish(BrowserTabChanged(browser="chromium", connection_id="c1",
                              window_id=99, tab_id=1, title="ABC Sport"))
bus.publish(FocusChanged(app="org.kde.kate", window_id="1", title="notes.md"))
bus.publish(FocusChanged(app="brave-browser", window_id="2", title="Brave"))

assert "ABC Sport" in titles(engine), titles(engine)

# Returning to the browser resolves to its last known tab rather than
# writing a fresh fallback, so there is still exactly one Brave row.
assert titles(engine).count("Brave") == 0, titles(engine)

print("OK")
