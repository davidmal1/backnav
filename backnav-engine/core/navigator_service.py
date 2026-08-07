import asyncio

from dbus_next.service import ServiceInterface, method

from adapters.registry import ADAPTERS_BY_RESTORE_TYPE
from core.websocket_server import activate_tab

SERVICE_NAME = "com.backnav.Navigator"
OBJECT_PATH = "/com/backnav/Navigator"


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
    """

    def __init__(self, engine):
        super().__init__(SERVICE_NAME)
        self._engine = engine

    @method()
    def Navigate(self, direction: "s") -> "s":
        item = self._engine.back() if direction == "back" else self._engine.forward()

        if item is None:
            return ""

        if item.restore_type == "browser_tab":
            browser, connection_id, tab_id = item.restore_id.split(":", 2)
            asyncio.ensure_future(activate_tab(connection_id, int(tab_id)))
        else:
            adapter = ADAPTERS_BY_RESTORE_TYPE.get(item.restore_type)
            if adapter is not None:
                adapter.restore(item.restore_id)

        return item.window_id
