from dataclasses import dataclass

from .base import Event


@dataclass(slots=True, kw_only=True)
class BrowserTabClosed(Event):
    connection_id: str
    tab_id: int
