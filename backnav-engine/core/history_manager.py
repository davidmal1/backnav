from core.models.focus_item import FocusItem


class HistoryManager:
    def __init__(self):
        self._history: list[FocusItem] = []
        self._index = -1

        # window_id / restore_id of targets known to no longer exist (window
        # closed, or browser tab closed). Once dead, always dead - closed
        # ids are never reused - so back()/forward() skip straight past any
        # entry naming one instead of landing on it: re-activating a closed
        # window/tab is a silent no-op, which just makes navigation look
        # stuck rather than actually doing nothing visible on purpose.
        self._dead_windows: set[str] = set()
        self._dead_tabs: set[str] = set()

    def push(self, item: FocusItem):
        current = self._history[self._index] if self._index != -1 else None

        # Same target as wherever we currently sit in the stack: either a
        # metadata update (e.g. a title change) or - critically - the echo
        # of our own back()/forward() call. Raising a window or switching a
        # browser's active tab to satisfy a navigation request fires the
        # exact same focus/tab-changed events a genuine user-driven switch
        # would, and that event flows straight back in here. This must be
        # checked against the CURRENT entry before any truncation: if we
        # truncated first, going back and then having that activation echo
        # arrive would wipe out the forward history we just navigated away
        # from, even though nothing actually new happened.
        if current is not None and self._is_same_target(current, item):
            self._history[self._index] = item
            return

        if self._index < len(self._history) - 1:
            self._history = self._history[: self._index + 1]

        self._history.append(item)
        self._index = len(self._history) - 1

    @staticmethod
    def _is_same_target(a: FocusItem, b: FocusItem) -> bool:
        return (a.window_id, a.restore_id) == (b.window_id, b.restore_id)

    def _is_dead(self, item: FocusItem) -> bool:
        return item.window_id in self._dead_windows or (
            item.restore_id is not None and item.restore_id in self._dead_tabs
        )

    def mark_window_dead(self, window_id: str):
        self._dead_windows.add(window_id)

    def mark_tab_dead(self, restore_id: str):
        self._dead_tabs.add(restore_id)

    def back(self):
        idx = self._index

        while idx > 0:
            idx -= 1
            if self._is_dead(self._history[idx]):
                continue

            self._index = idx
            return self._history[self._index]

        return None

    def forward(self):
        idx = self._index

        while idx < len(self._history) - 1:
            idx += 1
            if self._is_dead(self._history[idx]):
                continue

            self._index = idx
            return self._history[self._index]

        return None

    @property
    def current(self):
        if self._index == -1:
            return None

        return self._history[self._index]

    def all_items(self):
        return list(self._history)

    # Exposed so NavigationEngine.peek() can simulate several back()/
    # forward() steps (to preview them for the hold+repeat overlay) and
    # then put the cursor back exactly where it found it - see
    # NavigationEngine.peek()'s docstring for why that's done by
    # snapshotting/restoring _index rather than duplicating back()/
    # forward()'s own dead-entry-skipping loop.
    def snapshot_index(self) -> int:
        return self._index

    def restore_index(self, index: int):
        self._index = index
