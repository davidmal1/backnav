from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.navigation_engine import NavigationEngine

# --- NavigationEngine.peek()/step()/commit_walk(): the non-mutating
# --- preview, the per-tap walk, and the end-of-gesture promotion that
# --- MRU ordering is built on.
event_bus = EventBus()
engine = NavigationEngine(event_bus)

for i, title in enumerate(["a", "b", "c", "d", "e"]):
    event_bus.publish(FocusChanged(app="app", window_id=str(i), title=title))


def mru():
    # Reaching past the engine deliberately: the MRU order is the thing
    # under test here, and nothing in production needs to read it out.
    return [item.title for item in engine._history.all_items()]


# MRU order is now e, d, c, b, a - "e" was focused last, so it's the front.
assert mru() == ["e", "d", "c", "b", "a"]

# Peeking back 3 previews d, c, b without moving anything.
preview = engine.peek("back", 3)
assert [item.title for item in preview] == ["d", "c", "b"], f"got {[i.title for i in preview]!r}"
assert engine.current.title == "e", f"peek() must not move the walk, got {engine.current.title!r}"

# Repeating the exact same peek must give the exact same answer (idempotent -
# each poll of GetPeekState() calls this fresh, it must not drift/accumulate).
again = engine.peek("back", 3)
assert [item.title for item in again] == ["d", "c", "b"]

# Overshooting past the end of the list should just stop there, not raise.
overshoot = engine.peek("back", 10)
assert [item.title for item in overshoot] == ["d", "c", "b", "a"], f"got {[i.title for i in overshoot]!r}"
assert engine.current.title == "e"

# Three taps walk to where peek() said they would, one entry at a time.
assert engine.step("back").title == "d"
assert engine.step("back").title == "c"
assert engine.step("back").title == "b"
assert engine.current.title == "b"

# ...but crucially nothing has been reordered yet. An open walk must leave
# the list alone, otherwise the taps above would have been swapping the
# front two entries and "c" would never have been reachable.
assert mru() == ["e", "d", "c", "b", "a"]

# Committing promotes only the entry we landed on, leaving the others in
# their existing relative order - exactly Alt+Tab's behaviour on release.
assert engine.commit_walk().title == "b"
assert mru() == ["b", "e", "d", "c", "a"]
assert engine.current.title == "b"

# Walking back up an open gesture (the Alt+Shift+Tab direction) and then
# committing where we started is a no-op on ordering, not a promotion of
# something we merely passed through.
assert engine.step("back").title == "e"
assert engine.step("forward").title == "b"
assert engine.commit_walk() is None
assert mru() == ["b", "e", "d", "c", "a"]

# A committed walk starts the next gesture from the new front: one tap back
# from "b" now reaches "e", the entry it displaced.
assert engine.step("back").title == "e"
assert engine.commit_walk().title == "e"
assert mru() == ["e", "b", "d", "c", "a"]

# The single most common gesture: bounce between the two front entries.
# Each tap+commit swaps them, and it must keep doing so indefinitely rather
# than drifting further down the list.
for expected in ["b", "e", "b", "e"]:
    assert engine.step("back").title == expected
    assert engine.commit_walk().title == expected

assert mru() == ["e", "b", "d", "c", "a"]

# --- abandon_walk(): Escape out of the chooser -----------------------
#
# The counterpart to commit_walk(). Where committing promotes the entry
# the walk landed on, abandoning throws the walk away and leaves the MRU
# order byte-for-byte as it was, however far the user wandered first.
before = mru()
assert engine.step("back").title == "b"
assert engine.step("back").title == "d"
assert engine.current.title == "d"

# It returns the entry to go back TO, not the one walked to. The chooser
# has taken keyboard focus off that window by this point, so cancelling
# has to hand it back explicitly - which needs the entry, not just a
# reset. Returning None here would leave focus stranded on the panel.
assert engine.abandon_walk().title == "e"
assert mru() == before, f"abandoning must not reorder, got {mru()!r}"
assert engine.current.title == "e", "abandoning must return the walk home"

# And the walk is genuinely closed, not merely rewound: the next tap
# starts from the front again rather than resuming from "d".
assert engine.step("back").title == "b"
assert engine.abandon_walk().title == "e"

# Abandoning with no walk open is harmless - a duplicate Escape, or one
# arriving from a stale panel, must not move or reorder anything.
assert engine.abandon_walk().title == "e"
assert mru() == before

# Abandoning must also disarm echo suppression, not just rewind the walk.
# Every step() arms the entry it lands on, so that the focus event caused
# by raising it is not mistaken for the user switching windows. A chooser
# walk raises nothing, so those arms are never spent - left behind, the
# next GENUINE switch to any window merely walked past would be swallowed
# as an echo and silently fail to promote.
assert engine.step("back").title == "b"
assert engine.step("back").title == "d"
engine.abandon_walk()

event_bus.publish(FocusChanged(app="app", window_id="3", title="d"))
assert mru()[0] == "d", f"a real switch after abandoning must promote, got {mru()!r}"

print("peek()/step()/commit_walk() OK")
