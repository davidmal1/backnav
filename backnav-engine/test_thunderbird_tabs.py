from core.events.browser_tab_changed import BrowserTabChanged
from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.navigation_engine import NavigationEngine

# Thunderbird isn't a browser, but its MailExtension APIs (tabs.onActivated/
# onRemoved) report real, stable tab ids exactly like a browser extension
# does - unlike Kate/Konsole, which only have a fragile window-caption hook
# to notice a tab switch at all. So it's tracked via the SAME
# TAB_EXTENSION_APPS + BrowserTabChanged path as browsers, not a new
# mechanism - this test proves that generalization holds rather than
# re-proving behavior (dead-tab skipping, etc.) already covered generically
# by the browser tests.

event_bus = EventBus()
engine = NavigationEngine(event_bus)

# 0: plain window, no extension involved.
event_bus.publish(FocusChanged(app="org.kde.konsole", window_id="1", title="Konsole"))

# 1: Thunderbird gains focus, no tab info cached yet - window-level fallback.
event_bus.publish(FocusChanged(app="thunderbird", window_id="2", title="New window"))

# 2: the extension reports the mail tab itself.
event_bus.publish(BrowserTabChanged(
    browser="thunderbird", connection_id="tb-instance-1", window_id=1, tab_id=1,
    title="Inbox - Unified Folders", url="",
))
assert engine.current.restore_id == "thunderbird:tb-instance-1:1"

# 3: a message opened in its own tab.
event_bus.publish(BrowserTabChanged(
    browser="thunderbird", connection_id="tb-instance-1", window_id=1, tab_id=2,
    title="Re: quarterly report", url="",
))
assert engine.current.title == "Re: quarterly report"

titles = []
while True:
    item = engine.back()
    if item is None:
        break
    titles.append(item.title)

# "New window" (the window-level fallback recorded before any tab info
# arrived) is a guaranteed no-op here - the window never lost focus and a
# real tab entry for it exists right next door - so it's skipped, same as
# the equivalent browser case in test_noop_browser_window_skip.py.
assert titles == ["Inbox - Unified Folders", "Konsole"], f"got {titles}"

titles = []
while True:
    item = engine.forward()
    if item is None:
        break
    titles.append(item.title)

assert titles == ["Inbox - Unified Folders", "Re: quarterly report"], f"got {titles}"

print("OK")
