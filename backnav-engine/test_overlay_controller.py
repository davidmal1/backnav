import os
import unittest.mock as mock

# Before importing anything that reads it. Points the config at a path that
# cannot exist, so the suite runs against the shipped defaults instead of
# whatever ~/.config/backnavrc happens to say on this machine - otherwise
# these tests would start passing or failing according to the developer's
# own tuning, which is a horrible way to find out you changed a setting.
os.environ["BACKNAV_CONFIG"] = "/nonexistent/backnavrc"

from core.events.event_bus import EventBus  # noqa: E402
from core.events.focus_changed import FocusChanged  # noqa: E402
from core.overlay_controller import _MAX_PEEK_DEPTH, OverlayController  # noqa: E402

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
    def _uncancelled(self):
        return [h for h in self.handles if not h.cancelled]

    @property
    def live(self):
        """
        Pending DWELLS, which is what every assertion here means by a live
        timer.

        Filtered by callback rather than just counting handles, because
        two different timers now share this loop: the dwell that ends a
        gesture, and the hold detector armed on every press. Counting both
        together would make "no commit is scheduled" fail whenever a press
        happened to still be down, which says nothing about commits.
        """
        return [h for h in self._uncancelled if h.callback.__name__ == "_commit"]

    @property
    def holds(self):
        return [h for h in self._uncancelled if h.callback.__name__ == "_become_hold"]

    def fire(self):
        """
        Expire the dwell, and only the dwell.

        Firing every pending handle would fire the hold detector too, so a
        test that taps and then expires the gesture would silently be
        testing a hold instead.
        """
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
        mock.Mock(app="org.kde.konsole", title="top", window_id="10"),
        mock.Mock(app="org.kde.kate", title="one", window_id="11"),
        mock.Mock(app="firefox", title="two", window_id="12"),
        mock.Mock(app="org.kde.dolphin", title="three", window_id="13"),
    ],
    2,
)
state = controller.state_json()
fake_engine.walk_view.assert_called_once_with(_MAX_PEEK_DEPTH)
assert '"active": true' in state and '"direction": "back"' in state, state
assert '"highlightIndex": 2' in state, state
assert '"top"' in state and '"three"' in state, state

# windowId rides along per entry so the panel can find the KWin window and
# draw its icon. A Mock would serialise fine as an attribute but not as
# JSON, so this also pins that the field is a real string.
assert '"windowId": "10"' in state, state
assert '"windowId": "13"' in state, state

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

# ---- The mouse names an absolute row, not a direction ----------------
#
# Hovering row N has to become "step from wherever the highlight is to
# N", because the daemon owns the highlight and only knows how to move
# it one entry at a time. Stepping rather than assigning the walk
# position is deliberate - see OverlayController.set_highlight().

# Four rows, highlight on row 2 (the fixture set above).
fake_engine.step.reset_mock()
controller.set_highlight(0)
assert fake_engine.step.call_args_list == [mock.call("forward")] * 2, (
    f"hovering two rows up should step forward twice: "
    f"{fake_engine.step.call_args_list}"
)

fake_engine.step.reset_mock()
controller.set_highlight(3)
assert fake_engine.step.call_args_list == [mock.call("back")], (
    f"hovering one row down should step back once: "
    f"{fake_engine.step.call_args_list}"
)

# Hovering the row already highlighted is not a movement.
fake_engine.step.reset_mock()
controller.set_highlight(2)
fake_engine.step.assert_not_called()

# A row that does not exist is ignored rather than clamped. Clamping
# would silently move the highlight somewhere the pointer was not, and
# the panel and the daemon can legitimately disagree for one poll after
# the list changes under a stationary cursor.
for out_of_range in (-1, 4, 99):
    fake_engine.step.reset_mock()
    controller.set_highlight(out_of_range)
    fake_engine.step.assert_not_called()

# A highlight that is off-screen reports -1, and there is no delta to
# measure from that - so hovering must do nothing rather than step
# blindly.
fake_engine.step.reset_mock()
saved_walk_view = fake_engine.walk_view.return_value
fake_engine.walk_view.return_value = (saved_walk_view[0], -1)
controller.set_highlight(1)
fake_engine.step.assert_not_called()
fake_engine.walk_view.return_value = saved_walk_view

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

# Hover with the chooser CLOSED must do nothing. The panel lingers on
# screen for the dwell after a tap-driven walk, and the pointer may well
# be sitting over it - so rows can be hovered at a moment when there is
# no chooser to drive, and moving the walk then would rewrite history
# behind a panel that is already on its way out.
fake_engine.step.reset_mock()
controller.set_highlight(1)
fake_engine.step.assert_not_called()

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
# and must not have quietly disabled navigation itself.
#
fake_item = mock.Mock(title="d", window_id="42", restore_type=None, restore_id=None)
fake_engine.step.return_value = fake_item

with mock.patch("core.overlay_controller.restore_item") as fake_restore:
    for _ in range(4):
        controller._on_pressed("kwin", "BackNavBack", 0)
        controller._on_released("kwin", "BackNavBack", 0)

assert fake_engine.step.call_args_list == [mock.call("back")] * 4
assert fake_restore.call_args_list == [mock.call(fake_item)] * 4

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

# The window id still rides out even though the panel is not shown, and
# that is exactly what makes a hidden overlay work: KWin raises the window
# through this field, so were it withheld on an inactive report, tapping
# would step the history and move nothing on screen.
assert '"activateWindowId": "42"' in state_during_dwell, state_during_dwell

# Four taps and still no panel. Taps never summon it however many there
# are - see the header: tap to act, hold to look.
assert '"active": false' in state_during_dwell, state_during_dwell
assert controller._overlay_armed is False

# activateWindowId is popped, not left in place - the next poll must not
# report the same activation twice.
assert '"activateWindowId": null' in controller.state_json()

# The dwell expiring ends the gesture and promotes the walk.
loop.fire()
fake_engine.commit_walk.assert_called_once_with()
assert controller._direction is None
assert '"active": false' in controller.state_json()

# ...and the gesture resets, so the next one starts from scratch.
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

TAPS = 12

with mock.patch("core.overlay_controller.restore_item"):
    # No number of taps summons the panel. Asserted after EVERY tap, and
    # both mid-press and after the release, because the arming that used
    # to happen did so as a press began - so a threshold creeping back in
    # would be visible in that window and nowhere else.
    #
    # Twelve is well past any threshold anyone would plausibly reintroduce
    # (the two that shipped were 2 and 4), so this fails loudly rather
    # than happening to run short of a new one.
    for n in range(TAPS):
        controller._on_pressed("kwin", "BackNavForward", 0)

        assert '"active": false' in controller.state_json(), (
            f"tap {n + 1} showed the panel while the press was down"
        )

        controller._on_released("kwin", "BackNavForward", 0)

        assert '"active": false' in controller.state_json(), (
            f"tap {n + 1} showed the panel"
        )

# Every one of them still navigated - hiding the panel must not have cost
# the walk itself.
assert fake_engine.step.call_args_list == [mock.call("forward")] * TAPS
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

# ---- tap to act, hold to look ----------------------------------------
#
# The two gestures side by side in one controller, which is the clearest
# statement of the model there is: the same key, the same session, and the
# panel turns on for exactly one of them.
#
# Worth having even though the taps above already assert their half,
# because what matters is the CONTRAST. A regression that armed on taps
# would still leave "hold shows the panel" true, and a regression that
# never armed at all would still leave "taps stay quiet" true; only the
# pair catches both.

gesture_engine = mock.Mock()
gesture_engine.walk_view.return_value = ([], -1)
gesture_engine.step.return_value = mock.Mock(
    title="x", window_id="1", restore_type=None, restore_id=None,
)

gesture_controller = OverlayController(gesture_engine)
gesture_controller._loop = FakeLoop()

with mock.patch("core.overlay_controller.restore_item"):
    for _ in range(10):
        gesture_controller._on_pressed("kwin", "BackNavBack", 0)
        gesture_controller._on_released("kwin", "BackNavBack", 0)

assert gesture_controller._overlay_armed is False, "taps summoned the panel"
assert '"active": false' in gesture_controller.state_json()

# Then a hold, mid-gesture, with no reset in between - so this is the same
# walk changing its mind rather than a fresh start.
gesture_controller._on_repeated("kwin", "BackNavBack", 0)

assert gesture_controller._overlay_armed is True, "a hold did not raise the panel"
assert gesture_controller._chooser is True, "a hold must enter chooser mode"

# ---- a hold is detected by the clock, not just by auto-repeat --------
#
# Everything above drives holds through _on_repeated, which is how they
# were detected until 2026-08-17. That path cannot fire until the
# keyboard's own repeat delay elapses - 600ms by default - and once
# holding became the only way to summon the panel, inheriting that made it
# sluggish. So a press now also starts a timer.
#
# The distinction these tests have to hold onto: a tap and a hold begin
# IDENTICALLY. The only thing separating them is whether a release arrives
# before the timer does.


def held_setup():
    engine = mock.Mock()
    engine.walk_view.return_value = ([], -1)
    engine.step.return_value = mock.Mock(
        title="h", window_id="7", restore_type=None, restore_id=None,
    )

    made = OverlayController(engine)
    made._loop = FakeLoop()

    return made, engine


# A press alone arms the timer, and has not yet decided anything.
hold_controller, hold_engine = held_setup()
hold_controller._on_pressed("kwin", "BackNavBack", 0)

assert len(hold_controller._loop.holds) == 1, "a press did not arm the hold timer"
assert hold_controller._overlay_armed is False, "a press alone raised the panel"

# Letting go before it fires cancels it - this is a tap, and taps never
# show the panel however long they took.
hold_controller._on_released("kwin", "BackNavBack", 0)

assert hold_controller._loop.holds == [], "the release did not cancel the hold timer"
assert hold_controller._overlay_armed is False

# Holding past the threshold is what raises it. Fired by hand rather than
# by waiting, same as the dwell.
hold_controller, hold_engine = held_setup()
hold_controller._on_pressed("kwin", "BackNavBack", 0)
hold_controller._loop.holds[0].callback()

assert hold_controller._overlay_armed is True, "the hold timer did not raise the panel"
assert hold_controller._chooser is True
assert hold_controller._held is True, "a timed hold must mark the press as held"

# ...and marking it held is what stops the release from stepping. Without
# that, letting go of a hold would navigate, which is the "advancing 1
# place is silly" behaviour that holds exist to avoid.
hold_controller._on_released("kwin", "BackNavBack", 0)
hold_engine.step.assert_not_called()

# The repeat path still works and agrees with the timer. It is the backstop
# for a machine whose repeat delay is SHORTER than HoldMs, where the repeat
# is the earlier evidence - so it must not have been replaced.
repeat_controller, _ = held_setup()
repeat_controller._on_pressed("kwin", "BackNavBack", 0)
repeat_controller._on_repeated("kwin", "BackNavBack", 0)

assert repeat_controller._overlay_armed is True, "the repeat path stopped working"

# Both firing in one press is normal, not an error: the timer goes at
# 250ms and the first repeat lands at 600ms saying the same thing.
repeat_controller._loop.holds and repeat_controller._loop.holds[0].callback()
repeat_controller._on_repeated("kwin", "BackNavBack", 0)

assert repeat_controller._overlay_armed is True and repeat_controller._chooser is True

# A timer left pending by one gesture must not fire into the next. The
# reset clears it, so a tap after an abandoned gesture stays a tap.
stale_controller, _ = held_setup()
stale_controller._on_pressed("kwin", "BackNavBack", 0)

assert len(stale_controller._loop.holds) == 1

stale_controller._reset_gesture()

assert stale_controller._loop.holds == [], "a hold timer survived the gesture reset"

# Repeated presses do not stack timers - only the newest press is pending,
# so a burst of taps cannot leave a queue of them waiting to fire.
burst_controller, _ = held_setup()

for _ in range(5):
    burst_controller._on_pressed("kwin", "BackNavBack", 0)

assert len(burst_controller._loop.holds) == 1, (
    f"presses stacked hold timers: {len(burst_controller._loop.holds)}"
)

print("OverlayController OK")
