from core.events.browser_tab_changed import BrowserTabChanged
from core.events.browser_tab_closed import BrowserTabClosed
from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.events.window_closed import WindowClosed
from core.navigation_engine import NavigationEngine

event_bus = EventBus()
engine = NavigationEngine(event_bus)

# 0: plain window
event_bus.publish(FocusChanged(app="org.kde.kate", window_id="1", title="architecture.md"))
# 1: a short-lived launcher popup that will close right after
event_bus.publish(FocusChanged(app="albert", window_id="2", title="Albert"))
# 2: browser tab
event_bus.publish(FocusChanged(app="brave-browser", window_id="3", title="New Tab"))
event_bus.publish(BrowserTabChanged(browser="chromium", connection_id="conn-1", window_id=99, tab_id=1, title="Tab A", url="https://a.example.com"))
# 3: a second tab that will later be closed
event_bus.publish(BrowserTabChanged(browser="chromium", connection_id="conn-1", window_id=99, tab_id=2, title="Tab B", url="https://b.example.com"))
# 4: another plain window
event_bus.publish(FocusChanged(app="org.kde.konsole", window_id="4", title="journalctl"))

assert engine.current.title == "journalctl"

# The launcher popup closes (as Albert-style windows do right after use),
# and the second browser tab gets closed too.
event_bus.publish(WindowClosed(window_id="2"))
event_bus.publish(BrowserTabClosed(connection_id="conn-1", tab_id=2))

# Walking back should skip straight past both dead entries instead of
# landing on them and silently doing nothing.
titles = []
while True:
    item = engine.back()
    if item is None:
        break
    titles.append(item.title)

assert titles == ["Tab A", "New Tab", "architecture.md"], f"got {titles}"

# Once history is exhausted, forward should retrace the same live-only path.
titles = []
while True:
    item = engine.forward()
    if item is None:
        break
    titles.append(item.title)

assert titles == ["New Tab", "Tab A", "journalctl"], f"got {titles}"

print("OK")
