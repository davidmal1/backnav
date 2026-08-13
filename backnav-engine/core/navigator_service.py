import asyncio

from dbus_next.service import ServiceInterface, method

from adapters.registry import ADAPTERS_BY_RESTORE_TYPE
from core.websocket_server import activate_tab

SERVICE_NAME = "com.backnav.Navigator"
OBJECT_PATH = "/com/backnav/Navigator"


def restore_item(item):
    """
    The non-window-raising half of "make `item` the active thing":
    browser-tab entries need the owning browser told to switch its
    active tab (over the existing WebSocket connection - KWin can't see
    or do this), and adapter-tracked entries (Konsole session, Kate/
    qpdfview tab, ...) need the adapter's own restore() called. Shared
    by Navigate() (KWin-initiated, synchronous back()/forward()) and
    OverlayController's release handler (daemon-initiated, off the back
    of a step()) - both need the exact same restore side effects,
    just triggered from opposite directions.

    Raising the KWin window itself is deliberately NOT done here -
    KWin is the only thing that can do that on Wayland, so callers still
    need to get item.window_id to KWin one way or another afterwards.
    """
    if item.restore_type == "browser_tab":
        browser, connection_id, tab_id = item.restore_id.split(":", 2)
        asyncio.ensure_future(activate_tab(connection_id, int(tab_id)))
    else:
        adapter = ADAPTERS_BY_RESTORE_TYPE.get(item.restore_type)
        if adapter is not None:
            adapter.restore(item.restore_id)


class NavigatorService(ServiceInterface):
    """
    Exposes NavigationEngine.back()/forward() over D-Bus so the KWin
    script can request a navigation and then activate the returned
    window itself - KWin is the only thing that can raise a window on
    Wayland, so control has to flow this way rather than the daemon
    pushing commands into KWin.

    Browser-tab entries additionally need the owning browser to switch
    its active tab, which KWin can't see or do - that side effect is
    dispatched here, over the existing WebSocket connection, before
    the window id is handed back for KWin to raise.

    GetPeekState() is the read side of the hold+repeat overlay: KWin's
    declarativescript QML (see backnav-overlay/) has no way to receive a
    D-Bus signal push directly, so it polls this on a short QML Timer
    instead of the daemon pushing updates to it - see
    core/overlay_controller.py's docstring for the full rationale.
    """

    def __init__(self, engine, overlay):
        super().__init__(SERVICE_NAME)
        self._engine = engine
        self._overlay = overlay

    @method()
    def Navigate(self, direction: "s") -> "s":
        item = self._engine.back() if direction == "back" else self._engine.forward()

        if item is None:
            return ""

        restore_item(item)

        return item.window_id

    @method()
    def GetPeekState(self) -> "s":
        return self._overlay.state_json()

    # ---- Chooser, driven by the focused overlay panel ------------------
    #
    # Only meaningful while GetPeekState() reports chooser: true. The
    # daemon cannot see Up/Down/Enter/Escape itself - KGlobalAccel reports
    # only the two BackNav shortcuts - so the panel, which does have
    # keyboard focus in that mode, reads them and calls these.
    #
    # All three no-op unless the chooser is actually open, so a stale
    # panel or a duplicate call cannot navigate anything.

    # All three return "s" rather than nothing purely to match
    # GetPeekState/Navigate, the call shapes proven to work from
    # KWinComponents.DBusCall. Whether a void-returning method works there
    # is genuinely untested - the one attempt was made while the QML was
    # silently running from a stale cache, so it proved nothing either
    # way. Not worth re-litigating for a return value nobody reads.

    @method()
    def MoveHighlight(self, direction: "s") -> "s":
        self._overlay.move_highlight(direction)
        return "ok"

    @method()
    def ConfirmSelection(self) -> "s":
        self._overlay.confirm()
        return "ok"

    @method()
    def CancelSelection(self) -> "s":
        self._overlay.cancel()
        return "ok"

    # Not the same as CancelSelection: this one raises nothing. Called by
    # the panel's own poll loop when it notices it has lost keyboard
    # focus, where the window the user just clicked is already frontmost
    # and Cancel's "put me back where I started" would drag them off it.
    @method()
    def DismissSelection(self) -> "s":
        self._overlay.dismiss()
        return "ok"

    # The mouse's counterpart to MoveHighlight. The pointer names an
    # absolute row rather than a direction, because "the row under the
    # cursor" is not reachable by asking for "one further down".
    # A STRING, not an "i", despite naming a number. Every call shape
    # proven to work from KWinComponents.DBusCall in this project passes
    # strings, and a QML number arriving as a QVariant double would fail
    # to match an int32 signature - a failure mode with no diagnostic on
    # the QML side at all (see the overlay README on logging). Not worth
    # the risk for one int.
    @method()
    def SetHighlight(self, index: "s") -> "s":
        try:
            row = int(index)
        except ValueError:
            return "bad-index"

        self._overlay.set_highlight(row)

        return "ok"
