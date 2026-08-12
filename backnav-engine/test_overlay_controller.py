import unittest.mock as mock

from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
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

        # Advanced by hand. The panel-liveness heartbeat is the one piece
        # of OverlayController that reads the clock, and a test that
        # actually slept a second to prove a one-second timeout would be
        # the slowest thing in the suite by an order of magnitude.
        self.now = 1000.0

    def time(self):
        return self.now

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

# Press opens the walk.
controller._on_pressed("kwin", "BackNavBack", 0)
assert controller._direction == "back"

# It does NOT open the panel, though. One tap to bounce to the previous
# window is the common gesture, and the panel is pure distraction for it:
# the switch is over before it renders and it then sits on screen for the
# dwell plus the QML's linger describing a single step.
assert '"active": false' in controller.state_json(), "panel shown for a bare first tap"

# ...and the rows nobody is going to see are never even built.
fake_engine.walk_view.assert_not_called()

# An unrelated shortcut's repeats must not raise our panel.
controller._on_repeated("kwin", "SomeUnrelatedShortcut", 0)
assert '"active": false' in controller.state_json(), "another shortcut's repeat raised the panel"

# Holding does, though, and the FIRST repeat is enough - no threshold of
# our own on top. Auto-repeat only begins after the keyboard's repeat
# delay (600ms here, `xset q`), so a repeat existing at all already proves
# a deliberate hold; an earlier 250ms gate on top was unreachable code.
# globalShortcutRepeated is the only evidence available that a key is
# still physically down, since KGlobalAccel never reports a release of the
# modifier.
controller._on_repeated("kwin", "BackNavBack", 0)
assert '"active": true' in controller.state_json(), "hold did not raise the panel"

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

# Repeats are the keyboard's auto-repeat (25-28/sec measured) and must
# never accumulate into steps. This is the regression guard for the
# "holding jumps many places very quickly" bug.
for _ in range(50):
    controller._on_repeated("kwin", "BackNavBack", 0)

assert controller._direction == "back"
fake_engine.step.assert_not_called()

# A repeat for the OTHER direction mid-gesture must likewise not disturb
# the in-progress gesture.
controller._on_repeated("kwin", "BackNavForward", 0)
assert controller._direction == "back"

# Releasing a HELD key does not step AT ALL - not even the single step a
# tap would make. You hold the key to stop and read the list, so being
# moved one place the instant you let go is the opposite of what the hold
# was for; reported live as "advancing 1 place is silly". A hold means
# "show me where I am" and nothing else.
with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    controller._on_released("kwin", "BackNavBack", 0)

fake_engine.step.assert_not_called()
fake_restore.assert_not_called()

# Instead the hold has opened the CHOOSER: the panel takes keyboard
# focus and the user picks from it. That is reported to the QML, which
# is what makes it apply Qt.Popup and call requestActivate().
assert controller._chooser is True
assert '"chooser": true' in controller.state_json()

# No dwell, and this is the point of the mode: a focused chooser ends on
# an explicit Enter or Escape, never on a timer. Scheduling a commit here
# would put the old clock back and reintroduce the time pressure that
# made reversing onto earlier rows impractical.
assert len(loop.live) == 0, "the chooser must not schedule a commit"

# A tap of the shortcut with the chooser open moves the highlight exactly
# like Up/Down do - and, crucially, raises nothing. Raising is what a
# focused panel cannot survive: the target takes focus, the Qt.Popup
# loses it and hides itself.
with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    controller._on_pressed("kwin", "BackNavBack", 0)
    controller._on_released("kwin", "BackNavBack", 0)

fake_engine.step.assert_called_once_with("back")
fake_restore.assert_not_called()
assert len(loop.live) == 0, "a tap inside the chooser must not start a dwell"

# Up/Down arrive over D-Bus, since KGlobalAccel never sees them.
fake_engine.step.reset_mock()
controller.move_highlight("forward")
fake_engine.step.assert_called_once_with("forward")

# Enter commits: it raises where the highlight stands AND promotes it.
# The entry has to be read BEFORE commit_walk(), which moves it to the
# front - reading after would always raise whatever ended up at index 0.
#
# `current` is deliberately made to CHANGE across commit_walk() here, the
# way the real engine's does once the walk collapses. Left as a constant
# the two orderings are indistinguishable and this pins nothing.
fake_engine.step.reset_mock()
fake_engine.commit_walk.reset_mock()
landed = mock.Mock(title="landed", window_id="99", restore_type=None, restore_id=None)
after_commit = mock.Mock(
    title="after_commit", window_id="100", restore_type=None, restore_id=None
)
fake_engine.current = landed
fake_engine.commit_walk.side_effect = lambda: setattr(
    fake_engine, "current", after_commit
)

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    controller.confirm()
    fake_restore.assert_called_once_with(landed)

fake_engine.commit_walk.side_effect = None

fake_engine.commit_walk.assert_called_once_with()
assert controller._chooser is False
assert '"active": false' in controller.state_json()
assert '"activateWindowId": "99"' not in controller.state_json(), "popped once only"

# Escape cancels: back where the gesture started, MRU order untouched.
# It still has to RAISE that entry - nothing was raised while the chooser
# was open, but the panel took keyboard focus, so something must hand it
# back.
fake_engine.commit_walk.reset_mock()
origin = mock.Mock(title="origin", window_id="7", restore_type=None, restore_id=None)
fake_engine.abandon_walk.return_value = origin

controller._on_pressed("kwin", "BackNavBack", 0)
controller._on_repeated("kwin", "BackNavBack", 0)
assert controller._chooser is True

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    controller.cancel()
    fake_restore.assert_called_once_with(origin)

fake_engine.abandon_walk.assert_called_once_with()
assert not fake_engine.commit_walk.called, "cancel must not reorder the MRU"
assert controller._chooser is False

# The chooser operations are inert unless the chooser is actually open, so
# a stale panel or a duplicate call cannot navigate anything.
fake_engine.step.reset_mock()
fake_engine.commit_walk.reset_mock()
fake_engine.abandon_walk.reset_mock()

controller.move_highlight("back")
controller.confirm()
controller.cancel()

fake_engine.step.assert_not_called()
fake_engine.commit_walk.assert_not_called()
fake_engine.abandon_walk.assert_not_called()

# --- An orphaned chooser must not wedge the shortcut ------------------
#
# The chooser has no timeout, which is what makes it comfortable to read
# and also what makes it the one piece of state that can stick forever.
# The panel reports its own dismissal, but a panel DESTROYED outright - a
# KWin script reload, a crash - never gets to. _chooser then stays True
# and every later tap moves the highlight of a panel that isn't there
# while raising nothing, so the shortcut presents as completely dead.
# Reported live (2026-08-12) as "meta-tab doesn't do anything now".
fake_engine.step.reset_mock()
fake_engine.abandon_walk.reset_mock()
loop.handles = []

controller._on_pressed("kwin", "BackNavBack", 0)
controller._on_repeated("kwin", "BackNavBack", 0)
controller._on_released("kwin", "BackNavBack", 0)
assert controller._chooser is True

# The panel is alive as long as it keeps polling, so a tap here is an
# ordinary chooser tap: it moves the highlight and raises nothing.
controller.state_json()
loop.now += 0.4
fake_engine.step.reset_mock()

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    controller._on_pressed("kwin", "BackNavBack", 0)
    controller._on_released("kwin", "BackNavBack", 0)

fake_engine.step.assert_called_once_with("back")
fake_restore.assert_not_called()
assert controller._chooser is True, "a polling panel is a live panel"

# Now the panel stops polling. The very next tap must behave as a normal
# tap of a fresh gesture - walk one and raise it - not as the second tap
# of a chooser nobody can see.
loop.now += 5.0
fake_engine.step.reset_mock()
landed_again = mock.Mock(
    title="landed_again", window_id="55", restore_type=None, restore_id=None
)
fake_engine.step.return_value = landed_again

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    controller._on_pressed("kwin", "BackNavBack", 0)
    assert controller._chooser is False, "a silent panel must not hold the chooser open"
    controller._on_released("kwin", "BackNavBack", 0)
    fake_restore.assert_called_once_with(landed_again)

fake_engine.step.assert_called_once_with("back")
assert '"activateWindowId": "55"' in controller.state_json()

# The walk that the dead chooser had opened is abandoned rather than
# committed - the user never chose anything, so promoting whatever the
# invisible highlight happened to rest on would silently reorder the MRU.
fake_engine.abandon_walk.assert_called_once_with()

fake_engine.step.return_value = mock.Mock(
    title="x", window_id="1", restore_type=None, restore_id=None
)
fake_engine.step.reset_mock()
fake_engine.abandon_walk.reset_mock()
fake_engine.commit_walk.reset_mock()
loop.handles = []

# The same must hold when no panel has EVER polled, not just when one
# stopped. That is not a hypothetical: the overlay is a separate KWin
# script and BackNav has to keep working with it unloaded, uninstalled,
# or broken. Holding the shortcut then opens a chooser with nothing on
# screen to drive it, and without this the very first hold would wedge
# the shortcut permanently on a fresh daemon.
controller._last_poll = None
controller._on_pressed("kwin", "BackNavBack", 0)
controller._on_repeated("kwin", "BackNavBack", 0)
controller._on_released("kwin", "BackNavBack", 0)
assert controller._chooser is True

controller._last_poll = None

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    controller._on_pressed("kwin", "BackNavBack", 0)
    assert controller._chooser is False, (
        "a chooser no panel ever polled must not survive the next press"
    )
    controller._on_released("kwin", "BackNavBack", 0)
    fake_restore.assert_called_once()

fake_engine.step.reset_mock()
fake_engine.abandon_walk.reset_mock()
fake_engine.commit_walk.reset_mock()
controller._reset_gesture()
controller.state_json()
loop.handles = []

# --- Clicking another window closes the chooser -----------------------
#
# The case the two mechanisms above both miss. Clicking away does not
# destroy the panel and does not even unfocus it as far as the QML can
# tell - measured live, it kept polling and kept receiving hover events,
# reporting no `active` change whatsoever. So the panel cannot be the one
# to notice, and the heartbeat sees a perfectly healthy panel. KWin's
# focus stream is the only place the truth exists.
bus = EventBus()
focus_engine = mock.Mock()
focus_engine.walk_view.return_value = ([], -1)
focus_loop = FakeLoop()
focus_controller = OverlayController(focus_engine, bus)
focus_controller._loop = focus_loop

bus.publish(FocusChanged(app="konsole", window_id="origin", title="Konsole"))

focus_controller._on_pressed("kwin", "BackNavBack", 0)
focus_controller._on_repeated("kwin", "BackNavBack", 0)
focus_controller._on_released("kwin", "BackNavBack", 0)
assert focus_controller._chooser is True

# A dialog or other non-normal window is not a focus change -
# NavigationEngine ignores those for the same reason.
focus_controller.state_json()
bus.publish(FocusChanged(app="konsole", window_id="dialog", title="Save?", normal=False))
assert focus_controller._chooser is True, "a transient dialog must not close the chooser"

# Clicking a real, different window does close it - abandoning the walk,
# because the user picked with the mouse rather than choosing from the
# list, so nothing in the panel should be promoted.
with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    bus.publish(FocusChanged(app="signal", window_id="clicked", title="Signal"))

    # Crucially it raises NOTHING. The clicked window already has focus;
    # cancel()'s "put me back where I started" would drag the user
    # straight off it again.
    fake_restore.assert_not_called()

assert focus_controller._chooser is False, "clicking away must close the chooser"
focus_engine.abandon_walk.assert_called_once_with()
assert '"active": false' in focus_controller.state_json()
assert '"activateWindowId": null' in focus_controller.state_json()

# And the shortcut is immediately usable again - the whole point.
focus_engine.step.reset_mock()
landed = mock.Mock(title="next", window_id="88", restore_type=None, restore_id=None)
focus_engine.step.return_value = landed

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    focus_controller._on_pressed("kwin", "BackNavBack", 0)
    focus_controller._on_released("kwin", "BackNavBack", 0)
    fake_restore.assert_called_once_with(landed)

focus_engine.step.assert_called_once_with("back")

# Clicking straight back onto the window the chooser opened OVER closes
# it too. This is the case that shipped broken: an earlier version kept
# an "anchor" - the window focused when the chooser opened - and ignored
# focus events matching it, on the theory that they were echoes of a
# raise rather than the user. But the panel holds focus while the chooser
# is open, so focus arriving at the origin window is just as much a
# departure as focus arriving anywhere else. Measured live (2026-08-12):
# it wedged the shortcut until some third window happened to be focused
# minutes later.
focus_engine.abandon_walk.reset_mock()
focus_controller._on_pressed("kwin", "BackNavBack", 0)
focus_controller._on_repeated("kwin", "BackNavBack", 0)
focus_controller._on_released("kwin", "BackNavBack", 0)
assert focus_controller._chooser is True

# "clicked" is the window focused when this chooser opened - it was the
# last focus event published, above.
bus.publish(FocusChanged(app="signal", window_id="clicked", title="Signal"))
assert focus_controller._chooser is False, (
    "clicking the window the chooser opened over must still close it"
)
focus_engine.abandon_walk.assert_called_once_with()

# --- dismiss(): the panel noticing it lost focus ----------------------
#
# The second detector, and the one that covers what KWin's focus stream
# structurally cannot see. The panel is not a managed window, so KWin's
# active window never changes while the chooser is up - click back onto
# the window it already considers active and no windowActivated fires at
# all. Measured live (2026-08-12): the chooser stayed open for 90 seconds
# while the user typed into that window, with nothing logged.
focus_engine.abandon_walk.reset_mock()
focus_controller._on_pressed("kwin", "BackNavBack", 0)
focus_controller._on_repeated("kwin", "BackNavBack", 0)
focus_controller._on_released("kwin", "BackNavBack", 0)
assert focus_controller._chooser is True

# Drain the activateWindowId left pending by the tap further up, so the
# assertion below is about what dismiss() does rather than about history.
focus_controller.state_json()

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    focus_controller.dismiss()

    # Raises nothing, unlike cancel(). Focus has already moved to
    # whatever the user clicked; putting them back where they started
    # would drag them off it.
    fake_restore.assert_not_called()

assert focus_controller._chooser is False
focus_engine.abandon_walk.assert_called_once_with()
assert not focus_engine.commit_walk.called, "dismiss must not reorder the MRU"
assert '"activateWindowId": null' in focus_controller.state_json()

# Idempotent, because both detectors can fire for the same event - they
# deliberately overlap rather than being mutually exclusive.
focus_engine.abandon_walk.reset_mock()
focus_controller.dismiss()
focus_controller.dismiss()
focus_engine.abandon_walk.assert_not_called()
loop.handles = []

# ...but a TAP still steps. The removal above has to be specific to holds
# and must not have quietly disabled navigation itself. Two taps here so
# the panel is armed for the activateWindowId assertions below.
fake_item = mock.Mock(title="d", window_id="42", restore_type=None, restore_id=None)
fake_engine.step.return_value = fake_item

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    controller._on_pressed("kwin", "BackNavBack", 0)
    controller._on_released("kwin", "BackNavBack", 0)
    controller._on_pressed("kwin", "BackNavBack", 0)
    controller._on_released("kwin", "BackNavBack", 0)

assert fake_engine.step.call_args_list == [mock.call("back"), mock.call("back")]
assert fake_restore.call_args_list == [mock.call(fake_item), mock.call(fake_item)]

# A tap that follows a hold must be a real tap again - the held flag is
# per press, not per gesture, so it cannot leak forward and mute later
# taps.
assert controller._held is False

# Raising happens immediately, but the reorder does NOT - a tap must feel
# instant while still leaving the gesture open for a follow-up tap.
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

# ...and the panel is re-armed from scratch for the next gesture, so the
# next single tap is silent again rather than inheriting this walk's
# visibility.
assert controller._overlay_armed is False and controller._presses == 0

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
    controller._on_pressed("kwin", "BackNavForward", 0)
    controller._on_released("kwin", "BackNavForward", 0)

    # One tap, landed, no hold - still nothing on screen. This is the
    # gesture the hiding exists for.
    assert '"active": false' in controller.state_json(), "one completed tap showed the panel"

    controller._on_pressed("kwin", "BackNavForward", 0)

    # The second press is the tell that this is a walk rather than a
    # bounce, and the panel comes up as that tap BEGINS - so it is
    # already on screen when the step lands, not after it.
    assert '"active": true' in controller.state_json(), "second tap did not raise the panel"

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
