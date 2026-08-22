from dataclasses import dataclass

from .base import Event


@dataclass(slots=True, kw_only=True)
class FocusLost(Event):
    """
    KWin has no active window at all - every window minimised, or the last
    one closed with nothing behind it.

    Carries nothing but its timestamp: the fact IS the event. It exists
    because "no window is focused" is otherwise indistinguishable from
    "the last window I heard about still has focus", and the difference
    decides whether cancelling a chooser should hand focus back to
    something or leave the desktop alone.
    """
