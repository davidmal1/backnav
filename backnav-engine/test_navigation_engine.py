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
event_bus.publish(BrowserTabChanged(browser="chromium", connection_id="test-instance-1", window_id=99, tab_id=1, title="GitHub - BackNav"))
event_bus.publish(BrowserTabChanged(browser="chromium", connection_id="test-instance-1", window_id=99, tab_id=2, title="Docs"))

# Switching away and back to Brave should pick up the last known tab.
event_bus.publish(FocusChanged(app="org.kde.kate", window_id="1", title="architecture.md"))
event_bus.publish(FocusChanged(app="brave-browser", window_id="3", title="New Tab"))

# Tab activity while Brave is NOT focused should be cached but not recorded.
event_bus.publish(FocusChanged(app="org.kde.konsole", window_id="2", title="journalctl"))
event_bus.publish(BrowserTabChanged(browser="chromium", connection_id="test-instance-1", window_id=99, tab_id=3, title="Ignored while unfocused"))

# Repeated activation of the same window (KWin can fire windowActivated
# more than once for one switch) must collapse into a single entry.
event_bus.publish(FocusChanged(app="Claude", window_id="4", title="Claude"))
event_bus.publish(FocusChanged(app="Claude", window_id="4", title="Claude"))
event_bus.publish(FocusChanged(app="Claude", window_id="4", title="Claude"))

# Ordering is most-recently-used, front first - not a linear log of every
# switch. Revisiting somewhere promotes its existing entry instead of
# appending a second one, so Kate and Konsole each appear once despite
# being visited twice.
#
# Brave's window-level "New Tab" fallback is NOT here, and that is the
# point of this expectation rather than an omission. It was written when
# Brave took focus before the extension had reported anything, and the
# first real tab entry for that window superseded it - see
# HistoryManager.push.
#
# It used to survive, at the back of the list. That was wrong in use: two
# rows appeared for one Brave window, and the fallback could not do what
# its title said. Selecting "New Tab" raises the window and lands you on
# whatever tab is current, because a fallback carries no restore_id to
# return to a specific tab with. Reported 2026-08-17 as duplicate
# Thunderbird rows.
#
# The cost, stated honestly: the moment before Brave's tabs were known is
# no longer a place you can walk back to. It was never restorable as
# labelled, so what is lost is a position, not a capability.
expected_mru = [
    "Claude",
    "journalctl",
    "Docs",
    "architecture.md",
    "GitHub - BackNav",
]

mru = [item.title for item in engine._history.all_items()]
print("MRU order:", mru)
assert mru == expected_mru, f"expected {expected_mru}, got {mru}"

# Walking back from the front must visit exactly that order, and stop at
# the end rather than wrapping.
walked = [engine.current.title]
while True:
    item = engine.back()
    if item is None:
        break
    walked.append(item.title)

assert walked == expected_mru, f"expected {expected_mru}, got {walked}"

# That walk was never committed, so it must have left the ordering
# untouched - see HistoryManager on why reordering mid-gesture would make
# most of this list unreachable.
assert [item.title for item in engine._history.all_items()] == expected_mru

print("OK")
