import unittest.mock as mock

from core.overlay_controller import _MAX_PEEK_DEPTH, OverlayController

# --- OverlayController's press/repeat/release state machine, tested
# --- against a fake NavigationEngine (peek()/commit_peek() stubbed) and
# --- the raw KGlobalAccel signal handlers directly - attach() itself
# --- (the real D-Bus subscription) isn't exercised here, same as the
# --- adapters' _call being mocked out in their own tests.
#
# The gesture under test is one-tap-one-step. An earlier version of this
# file asserted an accumulating hold+repeat gesture instead; that design
# was abandoned once real-hardware measurement showed KGlobalAccel never
# reports a modifier's release, so there is no signal that could end a
# multi-tap gesture. See OverlayController's docstring.

fake_engine = mock.Mock()
fake_engine.peek.return_value = []

controller = OverlayController(fake_engine)

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

# The panel previews a whole windowful of upcoming history - NOT just the
# single entry this tap commits to - so the user can see where subsequent
# taps would land. Guards against regressing to peek(direction, 1), which
# renders a useless one-row panel.
fake_engine.peek.reset_mock()
fake_engine.peek.return_value = [
    mock.Mock(app="org.kde.kate", title="one"),
    mock.Mock(app="firefox", title="two"),
    mock.Mock(app="org.kde.dolphin", title="three"),
]
state = controller.state_json()
fake_engine.peek.assert_called_once_with("back", _MAX_PEEK_DEPTH)
assert '"active": true' in state and '"direction": "back"' in state, state
# Index 0 is this tap's destination; the rest are future taps' targets.
assert '"highlightIndex": 0' in state, state
assert '"one"' in state and '"three"' in state, state

# Repeats are the keyboard's auto-repeat (25-28/sec measured) and must be
# discarded entirely - a hold navigates one step, exactly like a tap.
# This is the regression guard for the "holding jumps many places very
# quickly" bug.
for _ in range(50):
    controller._on_repeated("kwin", "BackNavBack", 0)

assert controller._direction == "back"
fake_engine.peek.reset_mock()
controller.state_json()
fake_engine.peek.assert_called_once_with("back", _MAX_PEEK_DEPTH)

# A repeat for the OTHER direction mid-gesture must likewise not disturb
# the in-progress gesture.
controller._on_repeated("kwin", "BackNavForward", 0)
assert controller._direction == "back"

# Release commits exactly ONE step regardless of how many repeats arrived,
# restores/activates the result, and resets - then the NEXT state_json()
# poll must report the window to activate exactly once.
fake_item = mock.Mock(title="d", window_id="42", restore_type=None, restore_id=None)
fake_engine.commit_peek.return_value = fake_item

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    controller._on_released("kwin", "BackNavBack", 0)
    fake_engine.commit_peek.assert_called_once_with("back", 1)
    fake_restore.assert_called_once_with(fake_item)

assert controller._direction is None

state_after_commit = controller.state_json()
assert '"activateWindowId": "42"' in state_after_commit, state_after_commit
assert '"active": false' in state_after_commit

# activateWindowId is popped, not left in place - the next poll must not
# report the same activation twice.
assert '"activateWindowId": null' in controller.state_json()

# Release with no matching in-progress press (e.g. a shortcut that was
# never actually pressed through this controller, or a duplicate/late
# release) must not touch the engine at all.
fake_engine.commit_peek.reset_mock()
controller._on_released("kwin", "BackNavForward", 0)
fake_engine.commit_peek.assert_not_called()

# Two taps in a row are two independent one-step gestures - the shape a
# real "hold Meta, tap twice" produces, since each key release ends its
# own gesture.
fake_engine.commit_peek.reset_mock()
fake_engine.commit_peek.return_value = fake_item

with mock.patch("core.overlay_controller.restore_item"):
    for _ in range(2):
        controller._on_pressed("kwin", "BackNavForward", 0)
        controller._on_released("kwin", "BackNavForward", 0)

assert fake_engine.commit_peek.call_count == 2
assert fake_engine.commit_peek.call_args_list == [
    mock.call("forward", 1),
    mock.call("forward", 1),
]

print("OverlayController OK")
