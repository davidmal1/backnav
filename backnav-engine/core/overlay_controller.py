import json

from core.navigator_service import restore_item

# How many steps ahead the overlay will ever preview/allow paging into -
# just a sanity cap (nobody needs to see 500 entries at once), not tied
# to anything KWin- or D-Bus-specific.
_MAX_PEEK_DEPTH = 8

# KWin's registerShortcut("BackNavBack", ...)/("BackNavForward", ...)
# (see backnav-kwin/contents/code/main.js) register these two action
# names under KGlobalAccel's "kwin" component - this is the map from
# that action name back to which direction it drives here.
_SHORTCUT_DIRECTIONS = {"BackNavBack": "back", "BackNavForward": "forward"}


class OverlayController:
    """
    Drives the Alt+Tab-style hold+repeat-taps+release-commits overlay,
    entirely from the daemon side.

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
    keyboard-repeat rate) and globalShortcutReleased. So the daemon
    subscribes to those directly instead of going through the KWin
    script at all for this - the KWin script's registerShortcut()
    callback is untouched and keeps doing its own simple "single press =
    jump immediately" thing for a quick tap-and-release, since a
    Pressed+Released pair with zero Repeated events in between still
    also drives this state machine to the exact same end result (peek
    one step, then immediately commit that one step).

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
        self._count = 0
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
        self._count = 1

    def _on_repeated(self, component_unique, shortcut_unique, timestamp):
        # Ignores a repeat that doesn't match the direction we think is
        # currently held - e.g. a stray/out-of-order signal, or the
        # other direction's shortcut somehow firing mid-gesture - rather
        # than letting it corrupt an in-progress count.
        if _SHORTCUT_DIRECTIONS.get(shortcut_unique) != self._direction:
            return

        self._count = min(self._count + 1, _MAX_PEEK_DEPTH)

    def _on_released(self, component_unique, shortcut_unique, timestamp):
        if _SHORTCUT_DIRECTIONS.get(shortcut_unique) != self._direction:
            return

        item = self._engine.commit_peek(self._direction, self._count)
        self._direction = None
        self._count = 0

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

        entries = self._engine.peek(self._direction, self._count)

        return json.dumps({
            "active": True,
            "direction": self._direction,
            "highlightIndex": len(entries) - 1,
            "entries": [{"app": item.app, "title": item.title} for item in entries],
            "activateWindowId": activate_window_id,
        })
