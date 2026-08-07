from dataclasses import dataclass

from .base import Event


@dataclass(slots=True, kw_only=True)
class FocusChanged(Event):
    app: str
    window_id: str
    title: str
    # Process id of the window's owning process - needed to address
    # per-app D-Bus services that are keyed by pid (e.g. Konsole's
    # org.kde.konsole-<pid>) when resolving a restorable tab for apps
    # that have an adapter. Defaults to 0 for callers (tests, mainly)
    # that don't care about tab-adapter apps.
    pid: int = 0
