from focus_target import FocusTarget


class NavigationEngine:
    """
    Maintains the user's navigation history.
    """

    def __init__(self):
        self._stack = []
        self._current = -1

    def record(self, target: FocusTarget):
        """
        Record a new navigation target.
        Consecutive duplicates are ignored.
        """

        # Ignore consecutive duplicates
        if (
            self._current >= 0
            and self._stack[self._current].id == target.id
        ):
            return

        # If we've gone back, discard forward history
        if self._current < len(self._stack) - 1:
            self._stack = self._stack[: self._current + 1]

        self._stack.append(target)
        self._current = len(self._stack) - 1

    def back(self):
        """
        Move backwards in the navigation stack.
        Returns the destination or None.
        """

        if self._current <= 0:
            return None

        self._current -= 1
        return self._stack[self._current]

    def forward(self):
        """
        Move forwards in the navigation stack.
        Returns the destination or None.
        """

        if self._current >= len(self._stack) - 1:
            return None

        self._current += 1
        return self._stack[self._current]

    def dump(self):
        print("Navigation Stack")
        print("----------------")

        for i, target in enumerate(self._stack):
            marker = " <==" if i == self._current else ""
            print(f"{i}: {target.app} :: {target.title}{marker}")
