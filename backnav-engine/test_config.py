"""
backnavrc parsing, validation and live reload.

The point of this file is that a config parser fails in the direction of
taking the daemon down with it: a stray character in a hand-edited file
reaching a call_later() as a string, or an out-of-range number wedging the
gesture. Every bad input below is asserted to fall back to the default
rather than raise, because the alternative is BackNav refusing to start
over a typo.

Live reload is the other half. It is not a watcher, it is a stat on every
read, so the tests drive it by writing the file again and asserting the
next read sees the change - with no restart, no signal, and no reload
call in between.
"""

import io
import os
import tempfile
from contextlib import redirect_stdout

os.environ["BACKNAV_CONFIG"] = "/nonexistent/backnavrc"

from core.config import (  # noqa: E402
    CONFIG,
    DEFAULT_DWELL_MS,
    DEFAULT_HOLD_MS,
    Config,
    config_path,
)

DEFAULT_DWELL_SECONDS = DEFAULT_DWELL_MS / 1000.0

scratch = tempfile.mkdtemp(prefix="backnav-config-")
RC = os.path.join(scratch, "backnavrc")


def write(text):
    with open(RC, "w", encoding="utf-8") as handle:
        handle.write(text)


def using_file():
    """A fresh Config pointed at the scratch rc."""
    os.environ["BACKNAV_CONFIG"] = RC
    return Config()


def quietly(call):
    """Run something that may complain to the journal, and capture it."""
    buffer = io.StringIO()

    with redirect_stdout(buffer):
        result = call()

    return result, buffer.getvalue()


# ---- a missing file is the normal case -------------------------------

os.environ["BACKNAV_CONFIG"] = "/nonexistent/backnavrc"
absent = Config()

assert absent.dwell_seconds() == DEFAULT_DWELL_SECONDS

# Silently, too. A missing backnavrc is the shipped state, so warning about
# it would mean warning every user who never wrote one.
_, noise = quietly(absent.dwell_seconds)
assert noise == "", f"a missing file complained: {noise!r}"

# ---- ordinary values -------------------------------------------------

write("DwellMs = 1200\n")
config = using_file()

assert config.dwell_seconds() == 1.2

# ---- live reload, the whole reason this exists -----------------------

# Same instance, no restart and no reload call - just a changed file.
write("DwellMs = 300\n")

assert config.dwell_seconds() == 0.3, "an edited file was not picked up"

# Deleting it reverts to defaults, so removing backnavrc undoes everything
# in it rather than freezing the last values read.
os.remove(RC)

assert config.dwell_seconds() == DEFAULT_DWELL_SECONDS

# ...and writing it again is picked up just as well, so the revert above is
# not a one-way door.
write("DwellMs = 900\n")
assert config.dwell_seconds() == 0.9

# ---- the file is hand-edited, so it is read forgivingly --------------

write(
    "# a comment\n"
    "; another comment\n"
    "[BackNav]\n"
    "\n"
    "   dwellms   =   250   \n"
)
config = using_file()

# Case-insensitive keys, surrounding whitespace ignored, comments and a
# KDE-style section header tolerated rather than fatal.
assert config.dwell_seconds() == 0.25

# ---- bad input degrades, never raises --------------------------------

write("DwellMs = eight hundred\n")
config = using_file()

value, noise = quietly(config.dwell_seconds)
assert value == DEFAULT_DWELL_SECONDS
assert "not a whole number" in noise, noise

# Out of range is refused rather than honoured - far likelier to be
# seconds written where milliseconds were meant than an intention.
write("DwellMs = 8\n")
config = using_file()

value, noise = quietly(config.dwell_seconds)
assert value == DEFAULT_DWELL_SECONDS
assert "outside" in noise, noise

write("DwellMs = 999999\n")
config = using_file()
assert quietly(config.dwell_seconds)[0] == DEFAULT_DWELL_SECONDS

# A line with no '=' is skipped, and does not take the rest of the file
# with it - the good setting below it still lands.
write("this is not a setting\nDwellMs = 1500\n")
config = using_file()

value, noise = quietly(config.dwell_seconds)
assert value == 1.5, "a malformed line discarded the settings after it"
assert "no '='" in noise, noise

# An unknown key is simply not asked for, so it cannot break anything.
write("DwellMs = 1100\nSomeFutureSetting = yes\n")
config = using_file()
assert config.dwell_seconds() == 1.1

# ---- HoldMs, validated the same way ----------------------------------

write("HoldMs = 400\n")
config = using_file()
assert config.hold_seconds() == 0.4

# Its own bounds, not the dwell's - a 100ms hold is perfectly sensible
# where a 100ms dwell is the floor, so the two cannot share a range.
write("HoldMs = 10\n")
config = using_file()

value, noise = quietly(config.hold_seconds)
assert value == DEFAULT_HOLD_MS / 1000.0
assert "HoldMs" in noise and "outside" in noise, noise

write("HoldMs = 99999\n")
config = using_file()
assert quietly(config.hold_seconds)[0] == DEFAULT_HOLD_MS / 1000.0

# The two settings are independent: a bad one must not poison the good one
# sitting next to it in the same file.
write("DwellMs = 1300\nHoldMs = nonsense\n")
config = using_file()

assert config.dwell_seconds() == 1.3
assert quietly(config.hold_seconds)[0] == DEFAULT_HOLD_MS / 1000.0

# ---- a bad value must not flood the journal --------------------------

# This is read on every keypress. Complaining each time would turn one
# typo into thousands of lines.
write("DwellMs = nonsense\n")
config = using_file()

first = quietly(config.dwell_seconds)[1]
repeats = "".join(quietly(config.dwell_seconds)[1] for _ in range(20))

assert first != "", "the first bad read said nothing"
assert repeats == "", f"a bad value complained repeatedly: {repeats!r}"

# But a CHANGED file earns a fresh hearing - otherwise a user who fixes the
# typo and gets it wrong again a second time would hear nothing.
write("DwellMs = still nonsense\n")
assert quietly(config.dwell_seconds)[1] != "", "a re-edited file stayed silent"

# ---- where the file lives --------------------------------------------

os.environ.pop("BACKNAV_CONFIG", None)
os.environ["XDG_CONFIG_HOME"] = "/tmp/xdg-probe"
assert config_path() == "/tmp/xdg-probe/backnavrc"

os.environ.pop("XDG_CONFIG_HOME", None)
assert config_path() == os.path.expanduser("~/.config/backnavrc")

# The shared singleton is a Config like any other.
assert isinstance(CONFIG, Config)

os.environ["BACKNAV_CONFIG"] = "/nonexistent/backnavrc"

for leftover in (RC,):
    if os.path.exists(leftover):
        os.remove(leftover)

os.rmdir(scratch)

print("OK")
