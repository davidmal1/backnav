"""
Escape out of the chooser must not raise anything when nothing was focused.

Reported live 2026-08-22: minimise every window, hold the shortcut to open
the chooser, press Escape - and a window un-minimises. Nothing was
selected, so nothing should have moved.

The cause is a correct behaviour meeting a case it did not anticipate.
Cancelling raises the entry the gesture started on, deliberately: the
panel takes keyboard focus, so closing it has to hand focus back or you
are left typing into nothing. But that assumes the gesture started from a
focused window. From an empty desktop there is nowhere to hand focus back
TO, and raising _mru[0] anyway picks a window nobody chose.

The daemon could not previously tell the two apart. KWin fires
windowActivated(null) when the last window is minimised, and the KWin
script dropped it - so the daemon went on believing the last window it
had heard about still had focus. The blur event exists for this.
"""

from core.events.browser_tab_changed import BrowserTabChanged
from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.events.focus_lost import FocusLost
from core.navigation_engine import NavigationEngine


def engine_with_history():
    bus = EventBus()
    engine = NavigationEngine(bus)

    for n in (1, 2, 3):
        bus.publish(FocusChanged(app=f"app{n}", window_id=str(n),
                                 title=f"Window {n}"))

    return bus, engine


# ---- the bug: everything minimised, then Escape ----------------------

bus, engine = engine_with_history()

# Minimising the last window leaves KWin with no active window at all.
bus.publish(FocusLost())

assert engine.abandon_walk() is None, (
    "cancelling from an empty desktop returned something to raise"
)

# History itself is untouched - the windows still exist and are still
# worth navigating to. Being able to Meta+Tab out of an empty desktop is
# the whole point; forgetting focus must not mean forgetting the list.
assert len(engine._history.all_items()) == 3
assert engine.current is not None, "history was cleared along with focus"

# ---- the ordinary case still hands focus back ------------------------

# The reason cancel raises anything at all. Escape from a chooser opened
# over a real window must return focus to that window, or the panel closes
# and leaves the keyboard pointing at nothing.
bus, engine = engine_with_history()

item = engine.abandon_walk()

assert item is not None, "cancelling over a focused window raised nothing"
assert item.title == "Window 3", item.title

# ---- focus coming back re-arms it ------------------------------------

# Un-minimise something and the ordinary behaviour must return. A latch
# that stayed set would break cancel for the rest of the session.
bus, engine = engine_with_history()

bus.publish(FocusLost())
assert engine.abandon_walk() is None

bus.publish(FocusChanged(app="app2", window_id="2", title="Window 2"))

item = engine.abandon_walk()

assert item is not None, "focus returned but cancel stayed inert"
assert item.title == "Window 2", item.title

# ---- the panel itself must not count as focus ------------------------

# The chooser is a non-normal window, and taking keyboard focus is exactly
# what it does. If that counted, the empty-desktop case would look focused
# again the moment the panel opened - which is the moment before Escape.
bus, engine = engine_with_history()

bus.publish(FocusLost())
bus.publish(FocusChanged(app="backnav-overlay", window_id="panel",
                         title="", normal=False))

assert engine.abandon_walk() is None, (
    "the chooser panel taking focus was mistaken for a real window"
)

# ---- losing focus does not disturb tab attribution -------------------

# _on_focus_lost clears _current_app, which _report_discard() also reads.
# A tab event arriving on an empty desktop must stay silent rather than
# complaining that None claims nothing - the same blind-daemon guard.
import io
from contextlib import redirect_stdout

bus, engine = engine_with_history()
bus.publish(FocusLost())

buffer = io.StringIO()

with redirect_stdout(buffer):
    for n in range(1, 10):
        bus.publish(BrowserTabChanged(browser="chromium", connection_id="c1",
                                      window_id=1, tab_id=n, title=f"Tab {n}"))

assert buffer.getvalue() == "", f"complained on an empty desktop: {buffer.getvalue()!r}"

print("OK")
