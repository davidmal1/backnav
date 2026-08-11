from core.models.focus_item import FocusItem


class HistoryManager:
    """
    Most-recently-used ordering, Alt+Tab style, rather than a browser's
    linear back/forward stack.

    The list is always in MRU order, index 0 being wherever focus settled
    last. There is no cursor and no forward history to truncate: revisiting
    somewhere you've already been moves that entry to the front instead of
    appending a duplicate, so the list stays as long as the number of
    distinct windows/tabs you've touched rather than growing with every
    switch.

    The one piece of real subtlety is that a gesture must NOT reorder
    anything while it is still in progress. Promoting on every step would
    make the second step swap the top two entries back, so the third step
    returns to where the first one started - you would ping-pong between
    two entries and could never reach the third. Real Alt+Tab avoids this
    by only reordering when the modifier comes up; here that "gesture has
    ended" signal has to be synthesised, because KGlobalAccel never reports
    a modifier release (measured 2026-08-10 - see OverlayController's
    docstring). So walking is a transient offset (_walk) and the promotion
    only happens in commit(), which the caller fires after an idle dwell.
    """

    def __init__(self):
        self._mru: list[FocusItem] = []

        # How far down the list an in-progress gesture has walked. 0 means
        # settled - i.e. _mru[_walk] is always "where we are right now",
        # whether or not a walk is open.
        self._walk = 0

        # Targets this walk has already activated, so their focus events
        # can be recognised as the echo of our own activation rather than
        # as a genuine user-driven switch.
        #
        # This has to be a set of everywhere the walk has been, not just a
        # comparison against the current landing spot: on a fast walk we
        # activate B, step on to C, and only then does B's focus event
        # arrive. Matching that stale echo against C alone would fail, and
        # it would be treated as the user switching to B - promoting it and
        # collapsing the gesture halfway through. That produces exactly the
        # kind of intermittent "it sometimes jumps somewhere odd" bug that
        # is miserable to reproduce after the fact.
        self._walk_activated: set[tuple] = set()

        # window_id / restore_id of targets known to no longer exist (window
        # closed, or browser tab closed). Once dead, always dead - closed
        # ids are never reused - so back()/forward() skip straight past any
        # entry naming one instead of landing on it: re-activating a closed
        # window/tab is a silent no-op, which just makes navigation look
        # stuck rather than actually doing nothing visible on purpose.
        self._dead_windows: set[str] = set()
        self._dead_tabs: set[str] = set()

    def push(self, item: FocusItem):
        landed = self._mru[self._walk] if self._walk < len(self._mru) else None

        # Same target as where we currently stand: either a metadata update
        # (e.g. a title change) or the echo of the activation we just did to
        # satisfy a walk step. Refresh in place - promoting here would
        # reorder mid-gesture, which is the exact thing _walk exists to
        # prevent.
        if landed is not None and self._is_same_target(landed, item):
            self._mru[self._walk] = item
            return

        # A late echo from earlier in this same walk (see _walk_activated).
        # Still worth taking the fresh metadata, but it must not promote or
        # reset the walk.
        if self._target_of(item) in self._walk_activated:
            for i, existing in enumerate(self._mru):
                if self._is_same_target(existing, item):
                    self._mru[i] = item
                    break
            return

        # A genuine user-driven switch: abandon any open walk and promote.
        # De-duplicating rather than appending is what replaces the browser
        # model's truncate-on-branch - there is no branch to truncate when
        # there is only ever one entry per target.
        self._walk = 0
        self._walk_activated.clear()

        for i, existing in enumerate(self._mru):
            if self._is_same_target(existing, item):
                del self._mru[i]
                break

        self._mru.insert(0, item)

    @staticmethod
    def _target_of(item: FocusItem) -> tuple:
        return (item.window_id, item.restore_id)

    @staticmethod
    def _is_same_target(a: FocusItem, b: FocusItem) -> bool:
        return HistoryManager._target_of(a) == HistoryManager._target_of(b)

    def _is_dead(self, item: FocusItem) -> bool:
        return item.window_id in self._dead_windows or (
            item.restore_id is not None and item.restore_id in self._dead_tabs
        )

    def mark_window_dead(self, window_id: str):
        self._dead_windows.add(window_id)

    def mark_tab_dead(self, restore_id: str):
        self._dead_tabs.add(restore_id)

    def _next_alive(self, start: int, step: int):
        idx = start + step

        while 0 <= idx < len(self._mru):
            if not self._is_dead(self._mru[idx]):
                return idx

            idx += step

        return None

    def _walk_to(self, idx):
        if idx is None:
            return None

        self._walk = idx
        item = self._mru[idx]

        # Recorded here rather than by the caller because every caller
        # activates what it is handed - back()/forward() returning an entry
        # IS the decision to raise it. peek() is the one exception, and it
        # snapshots/restores this set along with _walk so its speculative
        # steps leave nothing behind.
        self._walk_activated.add(self._target_of(item))

        return item

    def back(self):
        return self._walk_to(self._next_alive(self._walk, +1))

    def forward(self):
        return self._walk_to(self._next_alive(self._walk, -1))

    def commit(self):
        """
        End of gesture: promote wherever the walk landed to the front, so
        the next gesture starts counting from here. Returns the promoted
        entry, or None if the walk never moved (a shortcut that hit the end
        of the list, or a commit fired with no walk open).
        """
        self._walk_activated.clear()

        if self._walk == 0:
            return None

        item = self._mru.pop(self._walk)
        self._mru.insert(0, item)
        self._walk = 0

        return item

    @property
    def current(self):
        if not self._mru:
            return None

        return self._mru[self._walk]

    def all_items(self):
        return list(self._mru)

    # Exposed so NavigationEngine.peek() can simulate several back()/
    # forward() steps (to preview them for the overlay) and then put things
    # back exactly as it found them - see NavigationEngine.peek()'s
    # docstring for why that's done by snapshot/restore rather than by
    # duplicating the dead-entry-skipping loop. The token is deliberately
    # opaque: a walk is _walk AND _walk_activated, and restoring only the
    # first would leave the echo-suppression set polluted with entries a
    # speculative peek merely looked at.
    def snapshot_walk(self):
        return (self._walk, set(self._walk_activated))

    def restore_walk(self, state):
        walk, activated = state
        self._walk = walk
        self._walk_activated = set(activated)

    # Raw offset, exposed so NavigationEngine.walk_view() can recognise
    # which rendered row the walk is standing on. Deliberately not used as
    # a display index itself: the rendered list omits dead and no-op
    # entries, so its row numbers and this offset drift apart as soon as
    # anything is skipped.
    def walk_position(self) -> int:
        return self._walk
