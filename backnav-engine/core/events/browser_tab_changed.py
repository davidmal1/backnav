from dataclasses import dataclass

from .base import Event


@dataclass(slots=True, kw_only=True)
class BrowserTabChanged(Event):
    browser: str
    connection_id: str
    window_id: int
    tab_id: int
    title: str
    url: str
