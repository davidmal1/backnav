from core.events.browser_tab_changed import BrowserTabChanged
from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.navigation_engine import NavigationEngine

event_bus = EventBus()
engine = NavigationEngine(event_bus)

# Plain window switches, no browser involved.
event_bus.publish(FocusChanged(app="org.kde.kate", window_id="1", title="architecture.md"))
event_bus.publish(FocusChanged(app="org.kde.konsole", window_id="2", title="journalctl"))

# Brave gains focus with no tab info yet - falls back to the window title.
event_bus.publish(FocusChanged(app="brave-browser", window_id="3", title="New Tab"))

# Tab-switching while Brave is focused should be recorded.
event_bus.publish(BrowserTabChanged(browser="chromium", connection_id="test-instance-1", window_id=99, tab_id=1, title="GitHub - BackNav", url="https://github.com"))
event_bus.publish(BrowserTabChanged(browser="chromium", connection_id="test-instance-1", window_id=99, tab_id=2, title="Docs", url="https://docs.example.com"))

# Switching away and back to Brave should pick up the last known tab.
event_bus.publish(FocusChanged(app="org.kde.kate", window_id="1", title="architecture.md"))
event_bus.publish(FocusChanged(app="brave-browser", window_id="3", title="New Tab"))

# Tab activity while Brave is NOT focused should be cached but not recorded.
event_bus.publish(FocusChanged(app="org.kde.konsole", window_id="2", title="journalctl"))
event_bus.publish(BrowserTabChanged(browser="chromium", connection_id="test-instance-1", window_id=99, tab_id=3, title="Ignored while unfocused", url="https://example.com"))

# Repeated activation of the same window (KWin can fire windowActivated
# more than once for one switch) must collapse into a single entry.
event_bus.publish(FocusChanged(app="Claude", window_id="4", title="Claude"))
event_bus.publish(FocusChanged(app="Claude", window_id="4", title="Claude"))
event_bus.publish(FocusChanged(app="Claude", window_id="4", title="Claude"))

titles = []
while True:
    current = engine.current
    titles.append(current.title if current else None)
    if engine.back() is None:
        break

titles.reverse()
print("Recorded history:", titles)

expected = [
    "architecture.md",
    "journalctl",
    "New Tab",
    "GitHub - BackNav",
    "Docs",
    "architecture.md",
    "Docs",
    "journalctl",
    "Claude",
]

assert titles == expected, f"expected {expected}, got {titles}"
print("OK")
