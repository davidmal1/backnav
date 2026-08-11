from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.navigation_engine import NavigationEngine

# --- walk_view(): what the overlay renders.
#
# A stable list counted from the front of the MRU order, with the
# highlight moving down it - not a sliding window with the highlight
# pinned to row 0.
#
# The pinned version was the first implementation and it was observed
# live to be actively misleading: walking away from an entry scrolled it
# off the top of the panel, so the entry a bounce returns to was never
# visible, and the commit's reordering then appeared to conjure it back
# out of nowhere. The sequence below is that exact reported case.

event_bus = EventBus()
engine = NavigationEngine(event_bus)

for window_id, title in enumerate(["TB", "FF", "Kon", "Dol", "Ok"]):
    event_bus.publish(FocusChanged(app="app", window_id=str(window_id), title=title))


def view(count=4):
    entries, highlight = engine.walk_view(count)
    return [item.title for item in entries], highlight


# Settled on "Ok" at the front, nothing walked yet.
assert view() == (["Ok", "Dol", "Kon", "FF"], 0), view()

# One tap: the rows must NOT move, only the highlight.
engine.step("back")
assert view() == (["Ok", "Dol", "Kon", "FF"], 1), view()

# Committing promotes "Dol" past "Ok", so the rows genuinely do change
# here - and "Ok" lands directly beneath, which is what makes the next
# tap a bounce back to where we came from.
engine.commit_walk()
assert view() == (["Dol", "Ok", "Kon", "FF"], 0), view()

# Two taps in one gesture walk the highlight two rows down a list that
# still holds still.
engine.step("back")
assert view() == (["Dol", "Ok", "Kon", "FF"], 1), view()
engine.step("back")
assert view() == (["Dol", "Ok", "Kon", "FF"], 2), view()

engine.commit_walk()
assert view() == (["Kon", "Dol", "Ok", "FF"], 0), view()

# Walking back up an open gesture moves the highlight up, not the rows.
engine.step("back")
engine.step("back")
assert view() == (["Kon", "Dol", "Ok", "FF"], 2), view()
engine.step("forward")
assert view() == (["Kon", "Dol", "Ok", "FF"], 1), view()
engine.commit_walk()

# A walk deeper than the panel can show scrolls just far enough to keep
# the highlight on the last row, rather than losing it off the bottom and
# reporting no highlight at all.
engine._history.restore_walk((0, set()))
for _ in range(4):
    engine.step("back")

entries, highlight = engine.walk_view(3)
assert highlight == 2, f"highlight fell off the panel: {highlight}"
assert [item.title for item in entries] == ["Ok", "FF", "TB"], [i.title for i in entries]

# Rendering must never move the real walk, however far it had to look to
# find the highlighted row.
before = engine.current.title
engine.walk_view(3)
engine.walk_view(8)
assert engine.current.title == before, f"walk_view moved the walk: {engine.current.title}"

# An empty history reports nothing to highlight rather than a row index
# that points past the end of the list.
empty = NavigationEngine(EventBus())
assert empty.walk_view(8) == ([], -1)

print("walk_view() OK")
