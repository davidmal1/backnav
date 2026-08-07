from core.events.event_bus import EventBus
from core.events.browser_tab_changed import BrowserTabChanged
from core.events.focus_changed import FocusChanged
from core.navigation_engine import NavigationEngine

# Reproduces the real-world sequence that got stuck: a plain window-level
# entry for the browser (recorded before any tab info arrived for that
# window) sitting right next to a real tab entry for the same window.
# Bouncing back/forward between them should never be a dead end - there's
# a genuinely different app (Konsole) one more step further back.

event_bus = EventBus()
engine = NavigationEngine(event_bus)

# 0: some other app
event_bus.publish(FocusChanged(app="org.kde.konsole", window_id="1", title="Konsole"))

# 1: browser window gains focus, no tab info cached yet - window-level fallback.
event_bus.publish(FocusChanged(app="brave-browser", window_id="2", title="Some Tab"))

# 2: now a real tab shows up for that same window.
event_bus.publish(BrowserTabChanged(browser="chromium", connection_id="conn-1", window_id=99, tab_id=1, title="Real Tab", url="https://example.com"))

assert engine.current.title == "Real Tab"

# Sitting on "Real Tab" (index 2) the whole time - the browser window never
# lost focus, so the window-level fallback at index 1 is a guaranteed no-op.
back1 = engine.back()
assert back1.title == "Konsole", f"expected to skip the dead-end fallback entry, got {back1.title!r}"

fwd1 = engine.forward()
assert fwd1.title == "Real Tab", f"got {fwd1.title!r}"

back2 = engine.back()
assert back2.title == "Konsole", f"got {back2.title!r}"

print("OK")
