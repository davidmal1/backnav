"""
The kitty adapter, with `kitty @` mocked.

kitty is the only supported application not reached over D-Bus. It owns
no bus name at all; everything here goes through its own JSON protocol on
a Unix socket. That makes the adapter the smallest in the project - `ls`
answers "which tab is active" directly, so there is no caption to parse
and no heuristic to get wrong - but it puts the risk somewhere new: in
finding the socket, and in reading a JSON tree that has more shape than
the flat answers other adapters get.

Both bugs this file guards against were found by running it against a
real kitty, not by review.
"""

import json
from unittest import mock

from adapters.kitty import KittyAdapter

# One kitty process, two OS windows. The second is the one in front, and
# each keeps its own active tab - which is the case that broke the first
# version of resolve_restore_id.
TWO_WINDOWS = [
    {
        "id": 1, "is_focused": False, "last_focused": False,
        "tabs": [
            {"id": 1, "is_active": True, "title": "~"},
            {"id": 2, "is_active": False, "title": "/tmp"},
        ],
    },
    {
        "id": 2, "is_focused": True, "last_focused": False,
        "tabs": [
            {"id": 3, "is_active": False, "title": "~/Projects"},
            {"id": 4, "is_active": True, "title": "vim"},
        ],
    },
]


def adapter(ls_payload=TWO_WINDOWS, socket="unix:/tmp/kitty-999"):
    """A KittyAdapter whose socket lookup and `kitty @` calls are faked."""
    kitty = KittyAdapter()
    calls = []

    def fake_call(pid, *args):
        calls.append((str(pid), args))

        if args and args[0] == "ls":
            return None if ls_payload is None else json.dumps(ls_payload)

        return ""          # focus-tab prints nothing on success

    kitty._call = fake_call
    kitty._socket_for = lambda pid: socket

    return kitty, calls


# ---- resolve reports the FOCUSED window's tab ------------------------

# The bug this pins: one kitty process can own several OS windows, each
# with its own active tab. Walking the whole tree and taking the first
# is_active answers a different question, and KWin hands over a pid
# rather than a window, so the adapter has to disambiguate.
#
# Observed live as a restore that had genuinely worked being reported as
# having landed somewhere else.
kitty, calls = adapter()

assert kitty.resolve_restore_id(999) == "kitty:999:4", kitty.resolve_restore_id(999)

# is_focused is false whenever kitty is not the active application, which
# is most of the time this gets asked - so last_focused has to carry it.
not_focused = json.loads(json.dumps(TWO_WINDOWS))
not_focused[1]["is_focused"] = False
not_focused[1]["last_focused"] = True

kitty, _ = adapter(not_focused)
assert kitty.resolve_restore_id(999) == "kitty:999:4"

# Neither flag set: fall back rather than returning nothing, since a tab
# is better than no entry at all.
neither = json.loads(json.dumps(TWO_WINDOWS))
neither[1]["is_focused"] = False

kitty, _ = adapter(neither)
assert kitty.resolve_restore_id(999) == "kitty:999:1"

# ---- restore focuses by id, and creates nothing ----------------------

kitty, calls = adapter()

assert kitty.restore("kitty:999:3") is True
assert calls[-1] == ("999", ("focus-tab", "--match", "id:3")), calls[-1]

# focus-tab, never new-tab or launch. Matched by id, not title: two tabs
# showing the same directory are ordinary, and a title match would pick
# whichever came first.
for _pid, args in calls:
    assert "new-tab" not in args and "launch" not in args, args
    assert not any(a.startswith("title:") for a in args), args

# A tab that no longer exists is refused rather than reported as done.
# kitty exits non-zero for an unmatched id, which _call turns into None -
# worth pinning because the neighbouring KMail investigation found an app
# whose equivalent call returns success for literally any input.
kitty, _ = adapter()
kitty._call = lambda pid, *args: None

assert kitty.restore("kitty:999:99") is False

# ---- liveness comes free from the same call --------------------------

kitty, _ = adapter()

with mock.patch.object(KittyAdapter, "_running_pids", staticmethod(lambda: ["999"])):
    live = kitty.live_targets()

# Keyed by (pid, tab) because tab ids are only unique within one kitty
# process. Two kitty processes both having a tab 1 must not be confused.
assert live == {("999", "1"), ("999", "2"), ("999", "3"), ("999", "4")}, live
assert kitty.target_of("kitty:999:4") in live
assert kitty.target_of("kitty:999:99") not in live
assert kitty.target_of("kitty:111:4") not in live, "tab ids must not cross processes"

# Unreachable kitty reports None, NOT an empty set. An empty set reads as
# "nothing is open" and would strand every kitty entry in history as dead.
kitty, _ = adapter(ls_payload=None)

with mock.patch.object(KittyAdapter, "_running_pids", staticmethod(lambda: ["999"])):
    assert kitty.live_targets() is None

# No kitty running at all is a real answer rather than a failure: pgrep
# exits 1, and the honest live set is empty.
kitty, _ = adapter()

with mock.patch.object(KittyAdapter, "_running_pids", staticmethod(lambda: [])):
    assert kitty.live_targets() == set()

# ---- an unreachable socket degrades quietly --------------------------

# Remote control off, kitty exiting mid-call, a stale socket. None of it
# may raise: this runs on a keypress path.
kitty, _ = adapter()
kitty._socket_for = lambda pid: None
kitty._call = KittyAdapter._call.__get__(kitty)   # the real one

assert kitty.resolve_restore_id(999) is None
assert kitty.restore("kitty:999:1") is False

# ---- malformed JSON is survived --------------------------------------

kitty, _ = adapter()
kitty._call = lambda pid, *args: "this is not json"

assert kitty.resolve_restore_id(999) is None

print("OK")
