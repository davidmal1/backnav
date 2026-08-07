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

    # See FocusChanged.normal - a transient/modal dialog's caption changing
    # (rare, but e.g. a "Save As" filename field updating the title) is
    # just as misattributable as its focus gain would be. Defaults to True
    # for callers (tests, mainly) that don't care about the distinction.
    normal: bool = True
