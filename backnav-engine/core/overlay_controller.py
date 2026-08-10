import json

from core.navigator_service import restore_item

# How many entries of upcoming history the overlay previews. Purely a
# display window - it is NOT how far a gesture can travel, since one tap
# always commits exactly one step (see _on_repeated). Nobody needs to see
# 500 entries at once; 8 is a comfortable panel height.
_MAX_PEEK_DEPTH = 8

# KWin's registerShortcut("BackNavBack", ...)/("BackNavForward", ...)
# (see backnav-kwin/contents/code/main.js) register these two action
# names under KGlobalAccel's "kwin" component - this is the map from
# that action name back to which direction it drives here.
_SHORTCUT_DIRECTIONS = {"BackNavBack": "back", "BackNavForward": "forward"}


class OverlayController:
    """
    Drives the one-tap-one-step history overlay, entirely from the
    daemon side.

    NOT an Alt+Tab-style accumulating gesture, though it was designed as
    one and the earlier version of this docstring described it that way.
    That design assumed you could hold a modifier, tap the key N times to
    walk N entries, and commit once when the modifier came up. Measured
    on real keys (2026-08-10, nested sandbox, trace in dev/shortcut_trace.py)
    that is impossible: globalShortcutReleased tracks the KEY, not the
    combo. Holding Meta and tapping F8 twice produced two complete
    pressed->released cycles 221ms and 159ms long, each committing
    independently, and releasing Meta ~2s later emitted nothing at all.
    KGlobalAccel simply never reports the modifier's release, so there is
    no signal that could mark the end of a multi-tap gesture.

    So each tap is its own self-contained navigation of exactly one step.
    Going back five entries means five taps. This is a deliberate choice
    over the two alternatives, both rejected:

      - Accumulating via auto-repeat (hold the key, let globalShortcutRepeated
        count) does work mechanically, but repeats arrive at the keyboard
        auto-repeat rate - measured 25-28/sec here - which saturates the
        whole preview depth in under 300ms. Confirmed unusable by feel
        before it was ever measured ("holding jumps many places very
        quickly").
      - Counting taps and committing after an idle timeout would recover
        the Alt+Tab feel, but taxes the common single-tap case with a
        visible delay before anything happens.

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

    async def attach(self, bus):
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

        self._direction = direction

    def _on_repeated(self, component_unique, shortcut_unique, timestamp):
        # Deliberately does nothing, and must stay that way.
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
        # the single commit happens on release.
        return

    def _on_released(self, component_unique, shortcut_unique, timestamp):
        if _SHORTCUT_DIRECTIONS.get(shortcut_unique) != self._direction:
            return

        # Always exactly one step: this fires on each key release, so one
        # press/release cycle is one whole gesture (see class docstring).
        item = self._engine.commit_peek(self._direction, 1)
        self._direction = None

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
        activate_window_id, self._pending_activate_window_id = self._pending_activate_window_id, None

        if self._direction is None:
            return json.dumps({"active": False, "activateWindowId": activate_window_id})

        # Previews a whole windowful of upcoming history, not just the one
        # entry this tap commits to. peek() walks `count` steps and returns
        # each one, so passing the committed count (always 1 now) would
        # render a single-row panel - technically accurate and useless.
        # Showing the next _MAX_PEEK_DEPTH entries instead lets you see
        # where the following taps would land, which is the only reason
        # the overlay earns its screen space under a one-tap-one-step
        # gesture.
        entries = self._engine.peek(self._direction, _MAX_PEEK_DEPTH)

        return json.dumps({
            "active": True,
            "direction": self._direction,
            # Index 0 is this tap's destination; later rows are where
            # subsequent taps would go.
            "highlightIndex": 0 if entries else -1,
            "entries": [{"app": item.app, "title": item.title} for item in entries],
            "activateWindowId": activate_window_id,
        })
