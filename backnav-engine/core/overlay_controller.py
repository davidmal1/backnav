import asyncio
import json

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
# Holding otherwise does nothing (a hold navigates exactly one step, same
# as a tap - see _on_repeated), so this gives it the obvious meaning of
# "show me the list" without letting it navigate.

# KWin's registerShortcut("BackNavBack", ...)/("BackNavForward", ...)
# (see backnav-kwin/contents/code/main.js) register these two action
# names under KGlobalAccel's "kwin" component - this is the map from
# that action name back to which direction it drives here.
_SHORTCUT_DIRECTIONS = {"BackNavBack": "back", "BackNavForward": "forward"}


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
        not wholly inert - it raises the panel - but a hold moves the
        highlight nowhere and commits exactly one step on release, the
        same as a tap.
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

    def __init__(self, engine):
        self._engine = engine
        self._direction = None
        self._pending_activate_window_id = None

        # Overlay visibility, latched for the length of one gesture. Once
        # armed it stays armed until the walk commits: re-deciding per poll
        # would let the panel wink out mid-walk at the 80ms poll rate.
        self._presses = 0
        self._overlay_armed = False

        # Captured in attach() rather than fetched per call: the signal
        # handlers below are sync callbacks invoked by dbus_next from the
        # loop, so get_running_loop() would work there too, but holding the
        # reference makes it obvious there is exactly one loop involved.
        self._loop = None
        self._commit_handle = None

    async def attach(self, bus):
        self._loop = asyncio.get_running_loop()

        introspection = await bus.introspect("org.kde.kglobalaccel", "/component/kwin")
        proxy = bus.get_proxy_object("org.kde.kglobalaccel", "/component/kwin", introspection)
        component = proxy.get_interface("org.kde.kglobalaccel.Component")

        component.on_global_shortcut_pressed(self._on_pressed)
        component.on_global_shortcut_repeated(self._on_repeated)
        component.on_global_shortcut_released(self._on_released)

    def _on_pressed(self, component_unique, shortcut_unique, timestamp):
        direction = _SHORTCUT_DIRECTIONS.get(shortcut_unique)

        if direction is None:
            return

        # Counted across the whole gesture, not per direction: tapping the
        # opposite way mid-walk is still the user driving the same walk,
        # and is if anything a stronger sign they want to see the list.
        self._presses += 1

        if self._presses >= _OVERLAY_AFTER_PRESSES:
            self._overlay_armed = True

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
        # physically down, so a hold long enough to be deliberate raises
        # the panel. The first repeat arms it with no threshold of our
        # own on top - see the _OVERLAY_AFTER_PRESSES comment block for
        # why any such threshold would be unreachable dead code.
        if _SHORTCUT_DIRECTIONS.get(shortcut_unique) is None:
            return

        self._overlay_armed = True

    def _on_released(self, component_unique, shortcut_unique, timestamp):
        direction = _SHORTCUT_DIRECTIONS.get(shortcut_unique)

        if direction is None or direction != self._direction:
            return

        # One tap, one step - raised straight away, so a single tap feels
        # like a single Alt+Tab. Only the MRU reordering waits for the
        # dwell below.
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

    def _commit(self):
        self._commit_handle = None
        self._direction = None
        self._presses = 0
        self._overlay_armed = False
        self._engine.commit_walk()

    def state_json(self) -> str:
        """
        Polled by the overlay QML's Timer (see backnav-overlay/). Includes
        activateWindowId exactly once per commit - popped here rather
        than left in place, since the poller has no separate "ack" call
        to tell this to clear it (see this class's docstring for why
        that's a deliberate simplification, not an oversight).
        """
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
            "highlightIndex": highlight,
            "entries": [{"app": item.app, "title": item.title} for item in entries],
            "activateWindowId": activate_window_id,
        })
