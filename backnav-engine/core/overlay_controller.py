import asyncio
import json

from core.events.focus_changed import FocusChanged
from core.navigator_service import restore_item

# How many entries the overlay shows at once: where the gesture currently
# stands, plus the next _MAX_PEEK_DEPTH - 1 places further taps would land.
# Purely a display window, not a limit on how far a gesture can travel.
# Nobody needs to see 500 entries at once; 8 is a comfortable panel height.
_MAX_PEEK_DEPTH = 8

# How long the gesture stays open after the last tap before the landed
# entry is promoted to the front of the MRU list.
#
# This is a stand-in for releasing Alt in a real Alt+Tab, which is not
# available to us: KGlobalAccel never reports a modifier's release (see
# the class docstring), so the end of a multi-tap gesture has to be
# inferred from the user stopping. It is the single value worth tuning by
# feel. Too short and a deliberate two-tap walk gets split into two
# separate one-tap gestures, which just swaps back and forth; too long and
# the ordinary bounce between two windows feels like it lags before it
# settles. Not a measured optimum - 600ms was the first value hand-tested
# and accepted, then raised to 800ms to give a two-tap walk more room.
_DWELL_SECONDS = 0.8

# When the panel is allowed to appear at all.
#
# The common gesture is one tap to bounce to the previous window, and for
# that the panel is pure distraction: the switch is already over by the
# time it renders, and it then sits there for _DWELL_SECONDS plus the
# QML's own linger (~1.5s total) describing a journey of one step. So it
# stays hidden until the gesture gives some sign of actually being a walk.
#
# NOT a plain elapsed-time delay measured from the start of the gesture,
# which is the obvious implementation and cannot work here. The gesture
# stays open for the whole _DWELL_SECONDS after the last tap, so any
# threshold below 800ms is met by every single-tap gesture too (it just
# shows the panel late, which is worse than showing it promptly), and any
# threshold above 800ms is never met at all because the walk has already
# committed. There is no usable value between those two: the dwell
# sandwiches it. What separates a bounce from a walk is not time spent in
# the gesture, it's whether the user is still driving it - so the two
# triggers below are engagement, not wall-clock.
#
# Second press, i.e. the panel appears as the second tap begins rather
# than when it lands, so it is already up when the step happens.
_OVERLAY_AFTER_PRESSES = 2

# ...or the key being held, for which the trigger is simply the arrival of
# the FIRST globalShortcutRepeated - deliberately with no threshold of our
# own on top, which would be dead code. Auto-repeat does not begin until
# the keyboard's repeat DELAY has elapsed (600ms on this machine: `xset q`
# reports "auto repeat delay: 600, repeat rate: 25", the rate matching the
# 25-28/sec measured earlier), so a repeat existing at all already proves
# a hold far longer than any threshold worth setting. An earlier version
# gated these on a 250ms hold and the condition was unreachable - the
# first repeat is 600ms late by construction.
#
# Reusing the system delay is the better behaviour anyway, not just the
# simpler one: "how long before holding a key means something" is a
# preference the user already owns in System Settings > Keyboard, so a
# fast repeat delay gets a correspondingly quick peek, and BackNav grows
# no knob of its own for it.
#
# Raising the panel is the ONLY thing holding does - see _on_released, a
# hold does not navigate at all. So the gesture reads exactly as "show me
# the list", and nothing moves until you tap.

# KWin's registerShortcut("BackNavBack", ...)/("BackNavForward", ...)
# (see backnav-kwin/contents/code/main.js) register these two action
# names under KGlobalAccel's "kwin" component - this is the map from
# that action name back to which direction it drives here.
_SHORTCUT_DIRECTIONS = {"BackNavBack": "back", "BackNavForward": "forward"}

# How long GetPeekState() can go unpolled before the overlay panel is
# presumed dead - see _panel_is_gone(). The QML polls every 80ms, so this
# is twelve missed polls: long enough that a stalled compositor or a busy
# moment cannot trip it, short enough that the user never gets a second
# dead keypress. Deliberately NOT a chooser timeout; it only ever fires
# for a panel that has stopped existing.
_PANEL_HEARTBEAT_SECONDS = 1.0


class OverlayController:
    """
    Drives the Alt+Tab-style MRU history overlay, entirely from the
    daemon side.

    Each tap of the shortcut walks one entry down the MRU list and raises
    what it lands on immediately, so a single tap behaves exactly like a
    single Alt+Tab: you bounce to the previous window with no delay. What
    the dwell defers is only the *reordering* - see HistoryManager, but in
    short, promoting the landed entry on every tap would swap the top two
    entries back and forth and make the third entry unreachable.

    The panel is not shown for every gesture. A one-tap bounce to the
    previous window is the common case and does not need a list drawn for
    it, so the overlay stays hidden until a second press or a held key
    says this is a walk - see _OVERLAY_AFTER_PRESSES. Window raising is
    unaffected either way, since activateWindowId is reported even while
    the overlay is inactive.

    The end of a gesture has to be inferred, because it cannot be
    observed. Measured on real keys (2026-08-10, nested sandbox, trace in
    dev/shortcut_trace.py): globalShortcutReleased tracks the KEY, not the
    combo. Holding Meta and tapping F8 twice produced two complete
    pressed->released cycles 221ms and 159ms long, and releasing Meta ~2s
    later emitted nothing at all. KGlobalAccel simply never reports the
    modifier's release, so "the user let go of Alt" is not a signal that
    exists here. _DWELL_SECONDS of quiet stands in for it.

    Two alternatives were tried and rejected before landing on this:

      - Accumulating via auto-repeat (hold the key, let globalShortcutRepeated
        count) does work mechanically, but repeats arrive at the keyboard
        auto-repeat rate - measured 25-28/sec here - which saturates the
        whole preview depth in under 300ms. Confirmed unusable by feel
        before it was ever measured ("holding jumps many places very
        quickly"). _on_repeated therefore still never navigates. It is
        not wholly inert - it raises the panel - but a hold moves
        nothing, on release or otherwise.
      - Committing one step per tap against a browser-style back/forward
        stack. That works, and is what `main` currently does, but it keeps
        a linear history with forward-truncation rather than recency
        ordering - a different mental model to Alt+Tab, and not the one
        this branch is exploring.

    Why this lives here rather than in the KWin script: KWin's JS
    scripting API's registerShortcut() callback only ever fires once per
    press (it's wired to the underlying QAction's triggered() signal),
    with no equivalent for "still held"/"just released" - confirmed
    against the actual KWin 6 scripting API docs, which expose no
    keyPressed/keyRelease/held hooks of any kind. Alt+Tab itself gets
    around this by being native C++ (KWin's TabBox), not a script.

    What actually carries hold/repeat/release information is one level
    down: every global shortcut - regardless of whether it was
    registered via KWin's JS registerShortcut(), a QML ShortcutHandler,
    or a plain QAction - is ultimately owned by KGlobalAccel, and
    KGlobalAccel's own org.kde.kglobalaccel.Component D-Bus interface
    (confirmed live via `qdbus6 org.kde.kglobalaccel /component/kwin
    org.freedesktop.DBus.Introspectable.Introspect` against this actual
    machine - "BackNavBack"/"BackNavForward" already show up there,
    registered by the existing registerShortcut() calls) emits three
    signals per shortcut: globalShortcutPressed, globalShortcutRepeated
    (fired for as long as the physical key(s) stay down, at the normal
    keyboard-repeat rate) and globalShortcutReleased. All three are
    confirmed to fire live on real hardware (2026-08-10). So the daemon
    subscribes to those directly instead of going through the KWin
    script at all for this.

    This class is now the ONE and ONLY thing that navigates. The KWin
    script's registerShortcut() callbacks are deliberately empty (see
    backnav-kwin/contents/code/main.js). An earlier version had them
    call Navigate() as well, on the theory that a Pressed+Released pair
    with no Repeated events in between would drive both paths to the
    same end result. That was wrong - they are additive, not idempotent
    - and every quick tap therefore navigated exactly two entries
    instead of one. A hold was worse still: triggered() fires at press,
    so it jumped immediately, before the gesture had finished.

    The other half of the puzzle - getting the *result* (what to show,
    when to raise a window) across to KWin - has the same shape problem
    in reverse: a plain KWin script can't create arbitrary on-screen
    QML (no createDialog()/component-loader in the JS scripting API),
    and a declarativescript-mode QML script (which *can* draw an
    on-screen Window - see backnav-overlay/) has no way to receive a
    D-Bus signal push either (KWinComponents.DBusCall is call-out-only).
    So this is deliberately poll-based: the QML overlay's own Timer
    calls NavigatorService.GetPeekState() every ~80ms and renders
    whatever it gets back; state_json() below is what it receives.
    """

    def __init__(self, engine, event_bus=None):
        self._engine = engine
        self._direction = None
        self._pending_activate_window_id = None

        # Overlay visibility, latched for the length of one gesture. Once
        # armed it stays armed until the walk commits: re-deciding per poll
        # would let the panel wink out mid-walk at the 80ms poll rate.
        self._presses = 0
        self._overlay_armed = False

        # Whether the press currently down has produced auto-repeats, i.e.
        # is a hold rather than a tap. Per PRESS, not per gesture: a walk
        # can mix taps and holds, and only the press being released right
        # now decides whether that release steps.
        self._held = False

        # Chooser mode: the panel has keyboard focus and the user is
        # picking from it, rather than walking past it.
        #
        # Entered by HOLDING the shortcut, never by tapping. The two
        # modes have to stay separate because they want opposite things
        # from window raising, and raising is what makes them
        # incompatible: a focused panel that raises a window loses focus
        # to it immediately and (being a Qt.Popup) hides itself. Measured
        # live - the panel "kept disappearing".
        #
        #   tap    - raise on every step, no focus, dwell commits.
        #            Fast and unchanged; this is the common gesture.
        #   hold   - raise NOTHING until Enter, focus, no dwell at all.
        #            Escape returns where you started.
        #
        # So a hold is now "open the chooser", which is the natural end of
        # it having stopped being a slow tap (see _on_released).
        self._chooser = False

        # Captured in attach() rather than fetched per call: the signal
        # handlers below are sync callbacks invoked by dbus_next from the
        # loop, so get_running_loop() would work there too, but holding the
        # reference makes it obvious there is exactly one loop involved.
        self._loop = None
        self._commit_handle = None

        # When the overlay QML last polled state_json(). It polls every
        # 80ms while loaded, so this doubles as a liveness heartbeat for
        # the panel - see _panel_is_gone().
        self._last_poll = None

        # Optional so the existing tests, which drive the KGlobalAccel
        # handlers directly with no bus in sight, keep constructing this
        # unchanged. Without one the chooser simply loses its
        # focus-moved-away detection; nothing else here reads the bus.
        if event_bus is not None:
            event_bus.subscribe(FocusChanged, self._on_focus_changed)

    async def attach(self, bus):
        self._loop = asyncio.get_running_loop()

        introspection = await bus.introspect("org.kde.kglobalaccel", "/component/kwin")
        proxy = bus.get_proxy_object("org.kde.kglobalaccel", "/component/kwin", introspection)
        component = proxy.get_interface("org.kde.kglobalaccel.Component")

        component.on_global_shortcut_pressed(self._on_pressed)
        component.on_global_shortcut_repeated(self._on_repeated)
        component.on_global_shortcut_released(self._on_released)

    def _on_focus_changed(self, event):
        """
        KWin's focus stream, watched to notice the chooser being
        orphaned. Nothing here touches history - NavigationEngine owns
        that and subscribes separately.

        One of TWO detectors, and neither is sufficient alone:

          - this one fires when focus moves to a DIFFERENT window than
            KWin currently considers active. Fast and reliable when it
            applies.
          - the QML's polled `active` check (see the poll Timer in
            main.qml) covers the case this one is blind to.

        The blind spot is structural. The panel is not a managed window,
        so KWin's notion of the active window never changes while the
        chooser is up. Click back onto the window KWin still thinks is
        active and there is no windowActivated event at all - measured
        live (2026-08-12), the chooser sat open for 90 seconds while the
        user typed into that window, with not one focus event logged.

        Deliberately does NOT raise anything on the way out. The user has
        just chosen a window by clicking it; cancel()'s "put me back where
        I started" would yank them straight off it again.
        """
        if not event.normal:
            return

        # ANY normal focus event closes the chooser, including one for the
        # window the chooser opened over.
        #
        # An earlier version compared against an "anchor" - the window
        # focused when the chooser opened - and ignored matches, meaning
        # to tolerate a late echo from a raise by a tap preceding the
        # hold. It was wrong twice over. Wrong in principle: the panel had
        # focus, so focus arriving anywhere else is a departure regardless
        # of destination. And wrong in practice - measured live
        # (2026-08-12), clicking straight back onto the window the chooser
        # opened over matched the anchor, was ignored, and wedged the
        # shortcut until the user happened to focus some third window
        # minutes later ("it fixed itself while typing this out").
        #
        # The echo it guarded against cannot reach here anyway. Nothing is
        # raised in chooser mode, and a hold cannot open the chooser until
        # the keyboard's 600ms auto-repeat delay has elapsed, by which
        # time any preceding tap's echo has long landed. The same journal
        # confirms it directly: neither chooser open produced a focus
        # event, the first arrivals being 10s and 12s later.
        # The one thing that would break this outright is KWin reporting
        # the PANEL itself as a normal focus change - the chooser would
        # then close the instant it opened. It does not: the panel is not
        # a KWin-managed window, so it never enters this stream at all.
        # Confirmed by logging every focus event reaching here across a
        # full round of chooser testing (2026-08-12) - every one named a
        # real application, none named the overlay.
        if self._chooser:
            self.dismiss()

    def _panel_is_gone(self):
        """
        Whether the overlay QML has stopped polling, i.e. the panel that
        was supposed to be driving the open chooser no longer exists.

        The chooser has no timeout by design - it ends on Enter or Escape
        and nothing else - which makes it the one piece of state that can
        wedge permanently. The panel normally reports its own dismissal
        (see onActiveChanged in the QML), but that cannot cover the panel
        being destroyed outright: a KWin script reload, a KWin restart, a
        crash. Then nobody ever sends Escape, _chooser stays True, and
        every later tap silently moves the highlight of a panel that
        isn't there while raising nothing - the shortcut appears dead.
        Reported live (2026-08-12) as "meta-tab doesn't do anything now".

        Uses the existing 80ms GetPeekState poll as the heartbeat rather
        than adding a timeout, so there is still no clock the user has to
        beat - only a check that the other end is alive at all.
        """
        if self._last_poll is None or self._loop is None:
            return True

        return self._loop.time() - self._last_poll > _PANEL_HEARTBEAT_SECONDS

    def _on_pressed(self, component_unique, shortcut_unique, timestamp):
        direction = _SHORTCUT_DIRECTIONS.get(shortcut_unique)

        if direction is None:
            return

        # Recover from an orphaned chooser before the press is counted, so
        # this reads as an ordinary first press of a fresh gesture rather
        # than a continuation of the dead one.
        if self._chooser and self._panel_is_gone():
            self._engine.abandon_walk()
            self._reset_gesture()

        # Counted across the whole gesture, not per direction: tapping the
        # opposite way mid-walk is still the user driving the same walk,
        # and is if anything a stronger sign they want to see the list.
        self._presses += 1

        if self._presses >= _OVERLAY_AFTER_PRESSES:
            self._overlay_armed = True

        self._held = False
        self._direction = direction

    def _on_repeated(self, component_unique, shortcut_unique, timestamp):
        # Deliberately does not NAVIGATE, and must stay that way.
        #
        # This is the keyboard's auto-repeat, measured at 25-28/sec on
        # this machine, so treating each repeat as a step made a hold
        # travel the entire history in a fraction of a second - the
        # "holding jumps many places very quickly" behaviour. Throttling
        # it to a readable rate was considered and rejected: it makes
        # how far you travel depend on how long you happened to hold a
        # key, which is far harder to aim than simply tapping N times.
        #
        # Holding the shortcut therefore navigates exactly one step,
        # same as tapping it - the repeats in between are discarded and
        # the single step happens on release.
        #
        # They are read for one thing only, which is not navigation:
        # they are the sole evidence available that a key is still
        # physically down. That drives two things: raising the panel, and
        # marking this press as a hold so its release does not step (see
        # _on_released). The first repeat arms it with no threshold of our
        # own on top - see the _OVERLAY_AFTER_PRESSES comment block for
        # why any such threshold would be unreachable dead code.
        if _SHORTCUT_DIRECTIONS.get(shortcut_unique) is None:
            return

        self._held = True
        self._overlay_armed = True
        self._chooser = True

    def _on_released(self, component_unique, shortcut_unique, timestamp):
        direction = _SHORTCUT_DIRECTIONS.get(shortcut_unique)

        if direction is None or direction != self._direction:
            return

        # With the chooser open, a tap of the shortcut is just another way
        # to move the highlight - exactly what Up/Down do - and raises
        # nothing. Returning here also means no commit is scheduled: a
        # focused chooser ends on Enter or Escape and never on a timer,
        # so there is no clock to beat while you read the list.
        if self._chooser:
            if not self._held:
                self._engine.step(direction)

            return

        # A hold peeks; it does not travel.
        #
        # It used to step once on release, on the reasoning that a hold
        # should at least do what a tap does. In practice that is worse
        # than doing nothing: you hold the key to STOP and look at the
        # list, and then get moved one place anyway the instant you let
        # go - reported live as "advancing 1 place is silly". Holding now
        # means only "show me where I am", and travel is always something
        # you asked for explicitly by tapping.
        #
        # Still falls through to _schedule_commit() below, so a gesture
        # that mixes taps and a final hold still commits wherever the taps
        # left it. A hold on its own leaves _walk at 0 and HistoryManager.
        # commit() then returns None, reordering nothing.
        if not self._held:
            # One tap, one step - raised straight away, so a single tap
            # feels like a single Alt+Tab. Only the MRU reordering waits
            # for the dwell below.
            item = self._engine.step(direction)

            if item is not None:
                restore_item(item)
                self._pending_activate_window_id = item.window_id

        # Each tap pushes the commit further out, so a run of taps is one
        # gesture rather than several. Tapping the opposite direction
        # mid-gesture walks back up the same open walk (the equivalent of
        # Alt+Shift+Tab) rather than starting a new one, since _direction
        # is only cleared when the walk actually commits.
        self._schedule_commit()

    def _schedule_commit(self):
        if self._commit_handle is not None:
            self._commit_handle.cancel()

        self._commit_handle = self._loop.call_later(_DWELL_SECONDS, self._commit)

    def _reset_gesture(self):
        if self._commit_handle is not None:
            self._commit_handle.cancel()
            self._commit_handle = None

        self._direction = None
        self._presses = 0
        self._overlay_armed = False
        self._chooser = False
        self._held = False

    def _commit(self):
        self._commit_handle = None
        self._reset_gesture()
        self._engine.commit_walk()

    # ---- Chooser operations, driven by the focused panel over D-Bus ----
    #
    # These exist because a focused panel is the only place a
    # select/confirm/cancel gesture can come from. KGlobalAccel reports
    # only the two BackNav shortcuts, so Up/Down/Enter/Escape are not
    # visible to the daemon at all - the QML has keyboard focus, reads
    # them, and calls these. See NavigatorService.

    def move_highlight(self, direction):
        """
        Up/Down in the chooser. Moves the walk WITHOUT raising anything -
        that deferral is the whole reason the chooser can hold focus.
        """
        if not self._chooser:
            return

        self._engine.step(direction)

    def confirm(self):
        """
        Enter in the chooser: raise where the highlight stands and promote
        it, the same end state a tap-driven walk reaches via its dwell.
        """
        if not self._chooser:
            return

        # Read BEFORE committing - commit_walk() promotes the landed entry
        # to the front, after which "where the highlight was" is no longer
        # recoverable from the walk offset.
        item = self._engine.current

        self._engine.commit_walk()
        self._reset_gesture()

        if item is not None:
            restore_item(item)
            self._pending_activate_window_id = item.window_id

    def dismiss(self):
        """
        Close the chooser without raising anything and without reordering.

        The difference from cancel() is entirely about focus. Escape means
        "I did not want any of these, put me back", so cancel() raises the
        window you started from. Dismiss means "focus already went
        somewhere else" - clicking another window, or the panel losing
        keyboard focus - so the right window is already frontmost and
        raising would drag the user off it.

        Idempotent, because both detectors can fire for the same event:
        the QML's polled check and KWin's focus stream are deliberately
        overlapping (see _on_focus_changed).
        """
        if not self._chooser:
            return

        self._engine.abandon_walk()
        self._reset_gesture()

    def set_highlight(self, index):
        """
        Put the highlight on an absolute row - what the mouse needs, since
        the pointer names a row directly rather than a direction.

        Implemented by STEPPING there rather than by assigning the walk
        position, deliberately. walk_view() renders by walking with back(),
        so the rows on screen are exactly the ones a real navigation can
        land on; setting the walk position straight to a row index would
        bypass the dead- and no-op-entry skipping that produced that list,
        and could park the highlight on a row no keypress could reach.

        A no-op when the highlight is not currently on screen - a walk
        deeper than the panel shows reports -1, and there is no delta to
        measure from that.
        """
        if not self._chooser:
            return

        entries, highlight = self._engine.walk_view(_MAX_PEEK_DEPTH)

        if highlight < 0 or not 0 <= index < len(entries):
            return

        delta = index - highlight
        direction = "back" if delta > 0 else "forward"

        for _ in range(abs(delta)):
            self._engine.step(direction)

    def cancel(self):
        """
        Escape in the chooser: back where you started, MRU order untouched.

        Raises explicitly rather than just closing the panel. Nothing was
        raised while the chooser was open, so the window you started on is
        still the right one - but the panel took keyboard focus off it, so
        somebody has to give it back.
        """
        if not self._chooser:
            return

        item = self._engine.abandon_walk()

        self._reset_gesture()

        if item is not None:
            restore_item(item)
            self._pending_activate_window_id = item.window_id

    def state_json(self) -> str:
        """
        Polled by the overlay QML's Timer (see backnav-overlay/). Includes
        activateWindowId exactly once per commit - popped here rather
        than left in place, since the poller has no separate "ack" call
        to tell this to clear it (see this class's docstring for why
        that's a deliberate simplification, not an oversight).
        """
        # Being called at all is the panel proving it is alive - see
        # _panel_is_gone(). Stamped before the early return below, since a
        # panel polling an inactive overlay is just as alive as one
        # polling an active it.
        if self._loop is not None:
            self._last_poll = self._loop.time()

        activate_window_id, self._pending_activate_window_id = self._pending_activate_window_id, None

        # activateWindowId still rides out on an inactive report, which is
        # what makes a hidden overlay work at all: a one-tap bounce raises
        # its window through exactly this path without the panel ever
        # being drawn.
        if self._direction is None or not self._overlay_armed:
            return json.dumps({"active": False, "activateWindowId": activate_window_id})

        # A stable list with a moving highlight, not a sliding window with
        # a pinned one - see NavigationEngine.walk_view() for why the
        # latter was wrong. The rows stay put across the taps of a gesture
        # and the highlight walks down them, so the entry you came from
        # stays visible above the highlight the whole time.
        entries, highlight = self._engine.walk_view(_MAX_PEEK_DEPTH)

        return json.dumps({
            "active": True,
            "direction": self._direction,

            # Tells the panel to take keyboard focus and accept
            # Up/Down/Enter/Escape. False for a tap-driven walk, which
            # must stay unfocused - see the _chooser comment in __init__
            # for why focus and per-step raising cannot coexist.
            "chooser": self._chooser,

            "highlightIndex": highlight,

            # windowId rides along so the panel can find the KWin window
            # and draw ITS icon. Deliberately not an icon name resolved
            # here: matching a resource class to a .desktop file misses
            # real apps (measured 2026-08-13 - "Claude" and "code" both
            # resolve to nothing, and snap-packaged apps land on absolute
            # PNG paths), whereas KWin has already done this work for
            # every window it manages and is what the task manager draws.
            "entries": [
                {"app": item.app, "title": item.title, "windowId": item.window_id}
                for item in entries
            ],
            "activateWindowId": activate_window_id,
        })
