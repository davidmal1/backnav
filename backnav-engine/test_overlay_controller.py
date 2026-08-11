import unittest.mock as mock

from core.overlay_controller import _MAX_PEEK_DEPTH, OverlayController

# --- OverlayController's press/repeat/release state machine, tested
# --- against a fake NavigationEngine (peek()/step()/commit_walk() stubbed)
# --- and the raw KGlobalAccel signal handlers directly - attach() itself
# --- (the real D-Bus subscription) isn't exercised here, same as the
# --- adapters' _call being mocked out in their own tests.
#
# The gesture under test is Alt+Tab-style: each tap walks and raises one
# entry immediately, and the MRU reordering is deferred until the gesture
# goes quiet for _DWELL_SECONDS. Real-hardware measurement showed
# KGlobalAccel never reports a modifier's release, so that idle dwell is
# the only available stand-in for "the user let go of Alt". See
# OverlayController's docstring.


class FakeHandle:
    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class FakeLoop:
    """
    Stand-in for the asyncio loop, so the dwell can be fired on demand
    rather than by sleeping - a real 600ms wait per assertion would make
    this file slow and flaky for no added confidence.
    """

    def __init__(self):
        self.handles = []

    def call_later(self, delay, callback):
        handle = FakeHandle(delay, callback)
        self.handles.append(handle)
        return handle

    @property
    def live(self):
        return [h for h in self.handles if not h.cancelled]

    def fire(self):
        for handle in self.live:
            handle.callback()
        self.handles = []


fake_engine = mock.Mock()
fake_engine.walk_view.return_value = ([], -1)

loop = FakeLoop()
controller = OverlayController(fake_engine)
controller._loop = loop

# Before anything happens, the overlay must report itself inactive.
assert controller.state_json() == '{"active": false, "activateWindowId": null}', controller.state_json()

# A signal for some other component/shortcut entirely (e.g. a completely
# unrelated global shortcut also owned by kglobalaccel) must be ignored.
controller._on_pressed("kwin", "SomeUnrelatedShortcut", 0)
assert controller._direction is None

# Press opens the preview.
controller._on_pressed("kwin", "BackNavBack", 0)
assert controller._direction == "back"

# An empty history previews nothing and highlights nothing, rather than
# reporting a highlightIndex that points past the end of the list.
empty_state = controller.state_json()
assert '"highlightIndex": -1' in empty_state, empty_state
assert '"entries": []' in empty_state, empty_state

# The panel renders the MRU list from the front with the highlight on
# whichever row the walk currently stands on - a stable list with a moving
# highlight, NOT a sliding window pinned to row 0. Regressing to the
# latter hides the entry the gesture just walked away from, which is the
# one a bounce needs to be able to see.
fake_engine.walk_view.reset_mock()
fake_engine.walk_view.return_value = (
    [
        mock.Mock(app="org.kde.konsole", title="top"),
        mock.Mock(app="org.kde.kate", title="one"),
        mock.Mock(app="firefox", title="two"),
        mock.Mock(app="org.kde.dolphin", title="three"),
    ],
    2,
)
state = controller.state_json()
fake_engine.walk_view.assert_called_once_with(_MAX_PEEK_DEPTH)
assert '"active": true' in state and '"direction": "back"' in state, state
assert '"highlightIndex": 2' in state, state
assert '"top"' in state and '"three"' in state, state

# Repeats are the keyboard's auto-repeat (25-28/sec measured) and must be
# discarded entirely - a hold walks one step, exactly like a tap. This is
# the regression guard for the "holding jumps many places very quickly"
# bug.
for _ in range(50):
    controller._on_repeated("kwin", "BackNavBack", 0)

assert controller._direction == "back"
fake_engine.step.assert_not_called()

# A repeat for the OTHER direction mid-gesture must likewise not disturb
# the in-progress gesture.
controller._on_repeated("kwin", "BackNavForward", 0)
assert controller._direction == "back"

# Release walks exactly ONE step regardless of how many repeats arrived,
# restores/activates the result, and schedules the commit - then the next
# state_json() poll must report the window to activate exactly once.
fake_item = mock.Mock(title="d", window_id="42", restore_type=None, restore_id=None)
fake_engine.step.return_value = fake_item

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    controller._on_released("kwin", "BackNavBack", 0)
    fake_engine.step.assert_called_once_with("back")
    fake_restore.assert_called_once_with(fake_item)

# Raising happens immediately, but the reorder does NOT - a single tap must
# feel instant while still leaving the gesture open for a follow-up tap.
fake_engine.commit_walk.assert_not_called()
assert controller._direction == "back", "overlay must stay up during the dwell"
assert len(loop.live) == 1 and loop.live[0].delay > 0

state_during_dwell = controller.state_json()
assert '"activateWindowId": "42"' in state_during_dwell, state_during_dwell
assert '"active": true' in state_during_dwell, state_during_dwell

# activateWindowId is popped, not left in place - the next poll must not
# report the same activation twice.
assert '"activateWindowId": null' in controller.state_json()

# The dwell expiring ends the gesture: the walk is promoted and the overlay
# goes away.
loop.fire()
fake_engine.commit_walk.assert_called_once_with()
assert controller._direction is None
assert '"active": false' in controller.state_json()

# Release with no matching in-progress press (e.g. a shortcut that was
# never actually pressed through this controller, or a duplicate/late
# release) must not touch the engine at all.
fake_engine.step.reset_mock()
controller._on_released("kwin", "BackNavForward", 0)
fake_engine.step.assert_not_called()

# Two taps in quick succession are ONE gesture of two steps, not two
# gestures of one - the second tap must cancel the first's pending commit
# rather than letting it fire mid-gesture. This is the whole reason the
# dwell exists: committing between the taps would swap the front two
# entries and send the second tap straight back where it started.
fake_engine.step.reset_mock()
fake_engine.commit_walk.reset_mock()
loop.handles = []

with mock.patch("core.overlay_controller.restore_item"):
    for _ in range(2):
        controller._on_pressed("kwin", "BackNavForward", 0)
        controller._on_released("kwin", "BackNavForward", 0)

assert fake_engine.step.call_args_list == [mock.call("forward"), mock.call("forward")]
fake_engine.commit_walk.assert_not_called()
assert len(loop.live) == 1, f"expected one live dwell, got {len(loop.live)}"

loop.fire()
fake_engine.commit_walk.assert_called_once_with()

# Tapping the opposite direction mid-gesture walks back up the SAME open
# walk (the Alt+Shift+Tab equivalent) instead of starting a fresh one.
fake_engine.step.reset_mock()
fake_engine.commit_walk.reset_mock()
loop.handles = []

with mock.patch("core.overlay_controller.restore_item"):
    controller._on_pressed("kwin", "BackNavBack", 0)
    controller._on_released("kwin", "BackNavBack", 0)
    controller._on_pressed("kwin", "BackNavForward", 0)
    controller._on_released("kwin", "BackNavForward", 0)

assert fake_engine.step.call_args_list == [mock.call("back"), mock.call("forward")]
fake_engine.commit_walk.assert_not_called()
assert len(loop.live) == 1

print("OverlayController OK")
