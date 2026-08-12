from dataclasses import dataclass

from .base import Event


@dataclass(slots=True, kw_only=True)
class BrowserTabsAlive(Event):
    """
    The complete set of tab ids an extension can currently see, sent every
    time it (re)connects.

    A correction, not a notification. BrowserTabClosed is best-effort and
    is provably lost in one common case - an MV3 service worker respawns ON
    the tabs.onRemoved event, runs connect() at top level, and the send
    that follows finds the socket still CONNECTING and drops it. Unlike a
    lost tab_changed, which the next tab switch corrects, nothing ever
    re-reports a closure, so the entry stays in history forever.

    This lets the daemon reconcile against ground truth instead of relying
    on every individual closure arriving.
    """

    connection_id: str
    tab_ids: frozenset[int]
