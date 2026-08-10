from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.navigation_engine import NavigationEngine

# --- NavigationEngine.peek()/commit_peek(): the non-mutating preview and
# --- its matching real-commit, that the hold+repeat overlay is built on.
event_bus = EventBus()
engine = NavigationEngine(event_bus)

for i, title in enumerate(["a", "b", "c", "d", "e"]):
    event_bus.publish(FocusChanged(app="app", window_id=str(i), title=title))

# Sitting on "e" (index 4). Peeking back 3 steps should preview c, b, a
# (in the order they'd be reached, furthest-last) without moving anything.
preview = engine.peek("back", 3)
assert [item.title for item in preview] == ["d", "c", "b"], f"got {[i.title for i in preview]!r}"
assert engine.current.title == "e", f"peek() must not move the cursor, got {engine.current.title!r}"

# Repeating the exact same peek must give the exact same answer (idempotent -
# each poll of GetPeekState() calls this fresh, it must not drift/accumulate).
again = engine.peek("back", 3)
assert [item.title for item in again] == ["d", "c", "b"]

# Overshooting past the start of history should just stop there, not raise.
overshoot = engine.peek("back", 10)
assert [item.title for item in overshoot] == ["d", "c", "b", "a"], f"got {[i.title for i in overshoot]!r}"
assert engine.current.title == "e"

# commit_peek() must land exactly where peek() of the same (direction,
# count) showed as the last/highlighted entry.
landed = engine.commit_peek("back", 3)
assert landed.title == "b", f"got {landed.title!r}"
assert engine.current.title == "b"

# And peek()/commit_peek() work symmetrically for "forward" from the new
# real position.
preview_fwd = engine.peek("forward", 1)
assert [item.title for item in preview_fwd] == ["c"]
assert engine.current.title == "b"

landed_fwd = engine.commit_peek("forward", 2)
assert landed_fwd.title == "d"
assert engine.current.title == "d"

print("peek()/commit_peek() OK")
