from dataclasses import dataclass

from .base import Event


@dataclass(slots=True, kw_only=True)
class BrowserDisconnected(Event):
    """
    An extension's WebSocket has gone away.

    Published so the engine can release what it learned about that
    connection. Without it, a browser that comes back under a NEW
    instanceId - an extension reloaded, reinstalled, or loaded from a
    different path - can never re-bind: the KWin window it lives in is
    still recorded as belonging to the dead connection, and _may_bind()
    refuses to let a second browser window claim a window that is already
    spoken for. Tab tracking for that browser then stays broken until the
    daemon restarts.

    Reported live (2026-08-12) after re-adding the extension from a
    different directory: the switcher pinned one stale tab at the top and
    never saw another tab switch in that browser again.
    """

    connection_id: str
