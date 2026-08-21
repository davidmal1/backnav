"""
History is capped, and the dead-id sets are capped with it.

The cap is not about memory. An entry is a few hundred bytes, ten
thousand would cost under 4MB, and a long Python list cannot corrupt
anything. Two other things drove it:

Deep history has no use. Reaching the thirtieth entry means thirty taps
or visually scanning a scrolling eight-row panel, and both lose to just
clicking the window. BackNav is faster than the mouse for the last
handful of places and stops being faster long before 20.

And the dead-id sets genuinely leaked. mark_window_dead() only ever
added, so every window and tab closed since the daemon started left a
permanent trace - unbounded, never reclaimed, and invisible until a
long-lived daemon is unaccountably fatter than a fresh one. Trimming the
list is what makes those sets collectable, so the two are one fix.
"""

from core.history_manager import MAX_HISTORY, HistoryManager
from core.models.focus_item import FocusItem


def window(n):
    return FocusItem(app=f"app{n}", window_id=str(n), title=f"Window {n}")


def tab(n, connection="c1"):
    return FocusItem(
        app="brave-browser", window_id="100", title=f"Tab {n}",
        restore_id=f"chromium:{connection}:{n}", restore_type="browser_tab",
    )


def titles(history):
    return [item.title for item in history.all_items()]


# ---- the cap holds, and holds the RIGHT end --------------------------

history = HistoryManager()

for n in range(1, MAX_HISTORY * 3):
    history.push(window(n))

assert len(history.all_items()) == MAX_HISTORY, len(history.all_items())

# Newest first, oldest evicted. Under MRU the oldest is the least useful
# thing in the list, so it is the correct end to lose.
assert titles(history)[0] == f"Window {MAX_HISTORY * 3 - 1}", titles(history)[:3]
assert titles(history)[-1] == f"Window {MAX_HISTORY * 3 - MAX_HISTORY}", titles(history)[-3:]

# ---- revisiting does not consume capacity ----------------------------

# The cap counts distinct targets, not switches. Bouncing between two
# windows forever must not evict anything, or heavy use of two apps would
# quietly destroy the history of everything else.
history = HistoryManager()

for n in range(1, 6):
    history.push(window(n))

before = titles(history)

for _ in range(200):
    history.push(window(1))
    history.push(window(2))

assert len(history.all_items()) == 5, titles(history)
assert set(titles(history)) == set(before), titles(history)

# ---- dead entries are evicted BEFORE live ones -----------------------

# This is what makes a small cap safe. Dead entries are skipped rather
# than removed, so a cap that counted them would not be a cap on places
# you can actually reach: close enough tabs and 20 entries could be 14
# corpses and 6 destinations, leaving the panel with fewer rows than it
# has room for.
history = HistoryManager()

for n in range(1, MAX_HISTORY + 1):
    history.push(tab(n))

# Kill the older half, then push enough to force eviction.
for n in range(1, MAX_HISTORY // 2):
    history.mark_tab_dead(f"chromium:c1:{n}")

for n in range(MAX_HISTORY + 1, MAX_HISTORY + 6):
    history.push(tab(n))

assert len(history.all_items()) == MAX_HISTORY

# Five pushes evict five entries. All five must come from the nine dead
# ones - not one live entry may be lost while a corpse is still held.
survivors = set(titles(history))
expected_live = {f"Tab {n}" for n in range(MAX_HISTORY // 2, MAX_HISTORY + 6)}

assert expected_live <= survivors, (
    f"live entries were evicted while dead ones survived: "
    f"missing {sorted(expected_live - survivors)}"
)

dead_left = [i for i in history.all_items() if history._is_dead(i)]

assert len(dead_left) == (MAX_HISTORY // 2 - 1) - 5, (
    f"wrong number of dead entries evicted: {len(dead_left)} left"
)

# ---- the leak: dead-id sets do not grow without bound ----------------

# The actual reason this exists. Churn far more windows than the cap and
# close every one of them; the sets must not accumulate every id ever
# seen.
history = HistoryManager()

for n in range(1, 501):
    history.push(window(n))
    history.mark_window_dead(str(n))

assert len(history.all_items()) <= MAX_HISTORY, len(history.all_items())
assert len(history._dead_windows) <= MAX_HISTORY, (
    f"dead-window set kept growing: {len(history._dead_windows)} ids "
    f"after 500 closed windows"
)

# Same for tabs, which churn far faster than windows in real use.
history = HistoryManager()

for n in range(1, 501):
    history.push(tab(n))
    history.mark_tab_dead(f"chromium:c1:{n}")

assert len(history._dead_tabs) <= MAX_HISTORY, (
    f"dead-tab set kept growing: {len(history._dead_tabs)} ids"
)

# ---- an id still referenced stays marked dead ------------------------

# The cleanup must forget only ids nothing refers to any more. Forgetting
# one that is still in the list would resurrect a closed window as a
# navigable entry, and landing on it is a silent no-op - navigation that
# looks stuck for no visible reason.
history = HistoryManager()

history.push(window(1))
history.mark_window_dead("1")

for n in range(2, MAX_HISTORY):
    history.push(window(n))

assert "1" in history._dead_windows, "a referenced dead id was forgotten"
assert history._is_dead(history.all_items()[-1])

# ---- trimming never disturbs an open walk ----------------------------

# push() only trims on the genuine-switch path, which resets _walk to 0
# first - but if that ever changed, a trim during a gesture could delete
# the entry the walk is standing on.
history = HistoryManager()

for n in range(1, MAX_HISTORY + 1):
    history.push(window(n))

history.back()
history.back()
landed = history.current

assert landed is not None
assert history.current is landed, "the walk moved under itself"

print("OK")
