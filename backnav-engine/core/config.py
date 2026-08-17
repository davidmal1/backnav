"""
~/.config/backnavrc - the handful of numbers worth tuning by feel.

One setting so far: the dwell that ends a gesture. It is a value arrived
at by trying it rather than by reasoning, it has no right answer, and it
was changed twice during development by editing a constant and restarting
the daemon. That cycle is what this exists to remove.

Deliberately not a home for everything that could be a knob. A setting is
a promise to keep a behaviour working forever and a question the user now
has to answer, so the bar is "genuinely a matter of taste". The panel's
tap threshold briefly lived here and was not that - it turned out the
right value was "no threshold at all", and a setting would have preserved
a bad idea behind a default (see overlay_controller's header).

Re-read on ACCESS rather than watched, and lazily: every read stats the
file and re-parses only when its mtime or size has changed. No inotify, no
watcher thread, no reload signal - one stat() against a page-cached file
is cheap enough to do on a keypress, and it means an edit takes effect on
the next gesture with nothing to restart and nothing to notify.

A missing file is the normal case, not an error - the defaults below ARE
the shipped behaviour, and the file only has to exist to disagree with
them.

Nothing here can break the daemon. A malformed line, an unknown key, a
non-numeric or out-of-range value: each is reported once to the journal
and then ignored in favour of the default. Getting this wrong should cost
you a log line, not a working navigation daemon.
"""

import os

# The defaults, and the documentation of what each value means. Kept here
# rather than in overlay_controller so there is one place to look for
# "what is tunable and what does it default to".
#
# 800ms: long enough that a deliberate two-tap walk is not split into two
# separate one-tap gestures, short enough that the ordinary bounce between
# two windows does not feel like it lags before it settles. 600 was the
# first value hand-tested and accepted; it was raised to give a two-tap
# walk more room.
DEFAULT_DWELL_MS = 800

# How long the shortcut must be held, with no release, before it counts as
# a hold and raises the panel.
#
# 250ms because a deliberate hold is unambiguous by then while a tap is
# long gone - key-down times for ordinary typing sit well under 150ms.
# That was the reasoning; the value was then used and accepted on
# 2026-08-17 ("hold feels faster.. perfectly fine"), so it is a tried
# number rather than only an argued one. No search for an optimum was
# made, and none is claimed - if it is ever wrong it will be wrong in an
# obvious direction, either sluggish or flashing the panel at ordinary
# taps, and HoldMs is the dial.
#
# This exists because the alternative was worse. The hold used to be
# detected from the first auto-repeat, which cannot arrive until the
# keyboard's own repeat DELAY has elapsed - 600ms by default - and once
# holding became the ONLY way to summon the panel, inheriting that made it
# feel sluggish. Repeats are still honoured as a backstop, so a system with
# a repeat delay shorter than this still shows the panel at that point
# instead.
DEFAULT_HOLD_MS = 250

# Bounds, not preferences. A dwell under ~100ms cannot survive the gap
# between two deliberate taps, so the gesture would fragment into
# single-tap walks; over 5s the panel outstays any plausible gesture and
# feels wedged. Values outside this are far likelier to be a typo (a stray
# zero, or seconds written where milliseconds were meant) than an
# intention, so they are refused rather than honoured.
_DWELL_MS_MIN = 100
_DWELL_MS_MAX = 5000

# Below ~50ms an ordinary tap would register as a hold, which would put the
# panel on screen for every single navigation. The upper bound is the point
# past which auto-repeat has already arrived on a default system and the
# setting has stopped doing anything.
_HOLD_MS_MIN = 50
_HOLD_MS_MAX = 2000

_ENV_PATH = "BACKNAV_CONFIG"


def config_path():
    """
    Where the file lives. BACKNAV_CONFIG overrides, which is how the tests
    pin themselves to a path that does not exist - otherwise a suite run on
    a machine with a real backnavrc would read whatever the user happens to
    have set, and pass or fail accordingly.
    """
    override = os.environ.get(_ENV_PATH)

    if override is not None:
        return override

    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")

    return os.path.join(base, "backnavrc")


class Config:
    def __init__(self):
        self._stamp = None
        self._values = {}
        self._complained = set()

    def dwell_seconds(self):
        ms = self._int("dwellms", DEFAULT_DWELL_MS)

        if not _DWELL_MS_MIN <= ms <= _DWELL_MS_MAX:
            self._complain(
                "dwellms",
                f"DwellMs={ms} outside {_DWELL_MS_MIN}-{_DWELL_MS_MAX}, "
                f"using {DEFAULT_DWELL_MS}",
            )
            ms = DEFAULT_DWELL_MS

        return ms / 1000.0

    def hold_seconds(self):
        ms = self._int("holdms", DEFAULT_HOLD_MS)

        if not _HOLD_MS_MIN <= ms <= _HOLD_MS_MAX:
            self._complain(
                "holdms",
                f"HoldMs={ms} outside {_HOLD_MS_MIN}-{_HOLD_MS_MAX}, "
                f"using {DEFAULT_HOLD_MS}",
            )
            ms = DEFAULT_HOLD_MS

        return ms / 1000.0

    # ---- reading -------------------------------------------------------

    def _int(self, key, default):
        self._refresh()

        raw = self._values.get(key)

        if raw is None:
            return default

        try:
            return int(raw)
        except ValueError:
            self._complain(key, f"{key}={raw!r} is not a whole number, using {default}")
            return default

    def _refresh(self):
        """
        Re-parse only when the file has actually changed.

        Keyed on (mtime_ns, size) rather than mtime alone: two edits inside
        one filesystem timestamp tick are unlikely but a size change catches
        the common case of it happening anyway. A vanished file resets to
        defaults, so deleting backnavrc is a valid way to undo everything in
        it.
        """
        path = config_path()

        try:
            info = os.stat(path)
            stamp = (info.st_mtime_ns, info.st_size)
        except OSError:
            if self._stamp is not None:
                self._stamp = None
                self._values = {}
                self._complained = set()
            return

        if stamp == self._stamp:
            return

        self._stamp = stamp

        # A changed file earns a fresh hearing: a complaint about a value
        # the user has since corrected should not be suppressed forever.
        self._complained = set()
        self._values = self._parse(path)

    def _parse(self, path):
        values = {}

        try:
            with open(path, encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError as error:
            self._complain("_read", f"cannot read {path}: {error}")
            return values

        for number, line in enumerate(lines, start=1):
            line = line.strip()

            # Section headers are tolerated and ignored. KDE rc files carry
            # them, so someone will write one out of habit; refusing to
            # start over a cosmetic [BackNav] would be needless.
            if not line or line.startswith(("#", ";", "[")):
                continue

            key, separator, value = line.partition("=")

            if not separator:
                self._complain(f"_line{number}", f"{path}:{number}: no '=', ignored")
                continue

            # Keys are matched case-insensitively so DwellMs, dwellms and
            # DWELLMS all work - this is a hand-edited file and the casing
            # in the docs is a suggestion, not a requirement.
            values[key.strip().lower()] = value.strip()

        return values

    def _complain(self, key, message):
        # Once per key per file version. A bad value is read on every
        # keypress, and this must not turn a typo into a journal flood.
        if key in self._complained:
            return

        self._complained.add(key)

        print(f"backnav: backnavrc: {message}", flush=True)


# One instance, shared. The file is global state and pretending otherwise
# would mean threading a config object through the whole daemon for no
# benefit.
CONFIG = Config()
