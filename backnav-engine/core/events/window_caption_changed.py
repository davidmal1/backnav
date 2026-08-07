from dataclasses import dataclass

from .base import Event


@dataclass(slots=True, kw_only=True)
class WindowCaptionChanged(Event):
    """
    A window's title changed while it stayed focused - KWin only reports
    focus changes for whole-window switches (see FocusChanged), so this is
    how an in-place tab switch inside an already-focused, adapter-tracked
    app (Konsole, eventually others) gets noticed at all. Only emitted for
    a small allowlist of apps (see TABBED_APPS in the KWin script) since
    most apps change their title for reasons that have nothing to do with
    tabs.
    """

    app: str
    window_id: str
    pid: int
    title: str
