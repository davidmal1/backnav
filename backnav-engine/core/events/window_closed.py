from dataclasses import dataclass

from .base import Event


@dataclass(slots=True, kw_only=True)
class WindowClosed(Event):
    window_id: str
