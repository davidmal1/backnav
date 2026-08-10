import unittest.mock as mock

from core.overlay_controller import OverlayController

# --- OverlayController's press/repeat/release state machine, tested
# --- against a fake NavigationEngine (peek()/commit_peek() stubbed) and
# --- the raw KGlobalAccel signal handlers directly - attach() itself
# --- (the real D-Bus subscription) isn't exercised here, same as the
# --- adapters' _call being mocked out in their own tests.

fake_engine = mock.Mock()
fake_engine.peek.return_value = []

controller = OverlayController(fake_engine)

# Before anything happens, the overlay must report itself inactive.
assert controller.state_json() == '{"active": false, "activateWindowId": null}', controller.state_json()

# A signal for some other component/shortcut entirely (e.g. a completely
# unrelated global shortcut also owned by kglobalaccel) must be ignored.
controller._on_pressed("kwin", "SomeUnrelatedShortcut", 0)
assert controller._direction is None

# Press starts a peek at count=1.
controller._on_pressed("kwin", "BackNavBack", 0)
assert controller._direction == "back"
assert controller._count == 1

fake_engine.peek.return_value = [mock.Mock(app="org.kde.kate", title="b-entry")]
fake_engine.peek.assert_not_called()  # not called yet - only state_json() calls it
state = controller.state_json()
fake_engine.peek.assert_called_once_with("back", 1)
assert '"active": true' in state and '"direction": "back"' in state, state

# Repeats (real key-repeat while held, or distinct re-taps while the
# modifier stays down - both arrive as globalShortcutRepeated) advance
# the count, up to the sanity cap.
for _ in range(3):
    controller._on_repeated("kwin", "BackNavBack", 0)
assert controller._count == 4

# A repeat for the OTHER direction mid-gesture must be ignored rather
# than corrupting the in-progress count - e.g. a stray signal, or (in
# principle) both shortcuts' keys briefly overlapping.
controller._on_repeated("kwin", "BackNavForward", 0)
assert controller._count == 4

# Release commits exactly (direction, count) via the engine, restores/
# activates the result, and resets - then the NEXT state_json() poll
# must report the window to activate exactly once.
fake_item = mock.Mock(title="d", window_id="42", restore_type=None, restore_id=None)
fake_engine.commit_peek.return_value = fake_item

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    controller._on_released("kwin", "BackNavBack", 0)
    fake_engine.commit_peek.assert_called_once_with("back", 4)
    fake_restore.assert_called_once_with(fake_item)

assert controller._direction is None
assert controller._count == 0

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

print("OverlayController OK")
