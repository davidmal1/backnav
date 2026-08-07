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

    # KWin's window.normalWindow - False for transient/modal dialogs (an
    # app's "Open File"/"Close Document" prompts, etc). These report the
    # exact same `app` resourceClass as their owning window, so without
    # this an adapter-tracked app's dialog would get misattributed to
    # whatever the app's *main* window happens to have open right now -
    # see NavigationEngine._on_focus_changed. Defaults to True for callers
    # (tests, mainly) that don't care about the distinction.
    normal: bool = True
