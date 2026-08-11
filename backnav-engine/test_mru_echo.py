from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.navigation_engine import NavigationEngine

# --- Activation echoes must not be mistaken for user-driven switches.
#
# Every step of a walk raises a window, and KWin reports that raise with
# exactly the same windowActivated signal a genuine user switch produces.
# If one of those echoes is treated as a real switch it promotes its
# target and collapses the walk mid-gesture, which under MRU ordering
# lands you somewhere other than where the gesture was heading.

event_bus = EventBus()
engine = NavigationEngine(event_bus)


def focus(window_id, title):
    event_bus.publish(FocusChanged(app="app", window_id=window_id, title=title))


def mru():
    return [item.title for item in engine._history.all_items()]


for window_id, title in [("1", "a"), ("2", "b"), ("3", "c"), ("4", "d")]:
    focus(window_id, title)

assert mru() == ["d", "c", "b", "a"]

# --- The in-order case: step, and the echo arrives before the next step.
assert engine.step("back").title == "c"
focus("3", "c")
assert engine.current.title == "c", "echo must not move the walk"
assert mru() == ["d", "c", "b", "a"], "echo must not reorder"

assert engine.commit_walk().title == "c"
assert mru() == ["c", "d", "b", "a"]

# --- The out-of-order case, which is the one that actually bites.
#
# On a fast walk we raise "d", step straight on to "b", and only then does
# "d"'s focus event arrive. Matching that late echo against the current
# landing spot alone would fail - it names "d" while we now stand on "b" -
# and it would be treated as the user switching to "d": promoting it and
# ending the gesture one entry short of where it was going.
assert engine.step("back").title == "d"
assert engine.step("back").title == "b"

focus("4", "d")  # the stale echo, arriving two steps late

assert engine.current.title == "b", f"stale echo collapsed the walk, landed on {engine.current.title!r}"
assert mru() == ["c", "d", "b", "a"], f"stale echo reordered mid-gesture: {mru()}"

assert engine.commit_walk().title == "b"
assert mru() == ["b", "c", "d", "a"]

# --- A genuine switch to somewhere the walk never touched must still be
# --- treated as real: promoted, with any open walk abandoned.
assert engine.step("back").title == "c"
focus("1", "a")  # user clicks a window the walk never visited

assert engine.current.title == "a"
assert mru() == ["a", "b", "c", "d"]
assert engine.commit_walk() is None, "a real switch must have already closed the walk"

# --- Echo suppression is scoped to one gesture, so the next walk starts
# --- with a clean slate rather than inheriting the last one's targets.
assert engine.step("back").title == "b"
assert engine.commit_walk().title == "b"
focus("3", "c")
assert mru() == ["c", "b", "a", "d"], f"post-commit switch was swallowed: {mru()}"

print("MRU echo suppression OK")
