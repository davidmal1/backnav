"""
The real KateAdapter's D-Bus behaviour: that it mints a token while the
document is open, caches it, and restores with activate() rather than
openUrl().

test_kate_adapter.py does NOT cover this. It substitutes a FakeKateAdapter
and exercises the engine's integration with a Kate-shaped adapter, which
left the real class with no coverage at all - the same hole
test_navigator_service.py was written to close. Proven by the change this
file accompanies: swapping restore() from openUrl to activate broke nothing
in the suite, because nothing was watching.

Which method name goes on the wire is the entire point here. openUrl means
"open this file" and reopens a document the user has closed; activate means
"switch to it if it still exists" and creates nothing. Those differ by one
word at the call site and are invisible until a closed tab comes back from
the dead, so they are asserted explicitly rather than through behaviour.
"""

from adapters.kate import KateAdapter

WINDOW_FILE_PATH = "org.qtproject.Qt.QWidget.windowFilePath"
TOKEN_OPEN_URL = "org.kde.Kate.Application.tokenOpenUrl"
ACTIVATE = "org.kde.Kate.Application.activate"
OPEN_URL = "org.kde.Kate.Application.openUrl"


def adapter(*results):
    """
    A KateAdapter whose qdbus6 calls are scripted rather than run.

    _call is a staticmethod, so a plain function on the INSTANCE shadows it
    with the same signature - no self is passed either way.
    """
    kate = KateAdapter()
    calls = []
    queued = list(results)

    def fake_call(pid, object_path, member, *args):
        calls.append((str(pid), member, args))
        return queued.pop(0) if queued else None

    kate._call = fake_call

    return kate, calls


def members(calls):
    return [member for _, member, _ in calls]


# ---- resolve mints a token, once ------------------------------------

kate, calls = adapter("/tmp/a.txt", "TOKEN-A")

assert kate.resolve_restore_id(456) == "kate:456:/tmp/a.txt"
assert members(calls) == [WINDOW_FILE_PATH, TOKEN_OPEN_URL]

# The token is minted against the path just read, not against anything
# stale - it is the document that is provably open right now.
assert calls[1][2] == ("/tmp/a.txt", "")
assert kate._tokens == {(456, "/tmp/a.txt"): "TOKEN-A"}

# Resolving the same document again must NOT mint again. Beyond saving a
# subprocess, tokenOpenUrl emits a caption change, and caption changes are
# what trigger resolution in the first place - minting every time risks
# feeding itself.
kate, calls = adapter("/tmp/a.txt", "TOKEN-A", "/tmp/a.txt")

kate.resolve_restore_id(456)
kate.resolve_restore_id(456)

# Two resolves, but only ONE tokenOpenUrl between them. Asserted over the
# whole call list rather than by counting, so an extra mint cannot hide.
assert members(calls) == [WINDOW_FILE_PATH, TOKEN_OPEN_URL, WINDOW_FILE_PATH], members(calls)

# A DIFFERENT document in the same Kate does get its own token.
kate, calls = adapter("/tmp/a.txt", "TOKEN-A", "/tmp/b.txt", "TOKEN-B")
kate.resolve_restore_id(456)
kate.resolve_restore_id(456)
assert kate._tokens == {(456, "/tmp/a.txt"): "TOKEN-A", (456, "/tmp/b.txt"): "TOKEN-B"}

# ---- restore activates, and never opens ------------------------------

# activate() is void, so a real qdbus6 prints nothing and _call hands back
# an empty string - which is a success, distinct from the None it returns
# when the call actually fails.
kate, calls = adapter("/tmp/a.txt", "TOKEN-A", "")
kate.resolve_restore_id(456)
calls.clear()

assert kate.restore("kate:456:/tmp/a.txt") is True
assert members(calls) == [ACTIVATE]

# The token, not the path. Passing the path here would still "work" often
# enough to look right, since Kate would just reopen the file.
assert calls[0][2] == ("TOKEN-A",)

# Stated as its own assertion because it is the actual bug: openUrl must
# not appear on the wire at all.
assert OPEN_URL not in members(calls)

# ---- no token means do nothing, NOT reopen ---------------------------

# Only reachable if the mint failed, since resolve always attempts one.
# Falling back to openUrl here is what would resurrect a closed file, so
# the adapter deliberately gives up instead.
kate, calls = adapter("/tmp/a.txt", None)

assert kate.resolve_restore_id(456) == "kate:456:/tmp/a.txt"
assert kate._tokens == {}

calls.clear()
assert kate.restore("kate:456:/tmp/a.txt") is False
assert calls == [], f"a tokenless restore touched D-Bus: {calls}"

# An entry for a Kate that has since exited resolves to a different pid and
# so finds no token either - same silent no-op rather than a reopen.
kate, calls = adapter("/tmp/a.txt", "TOKEN-A")
kate.resolve_restore_id(456)
calls.clear()

assert kate.restore("kate:999:/tmp/a.txt") is False
assert calls == []

# ---- an unresolvable path resolves to nothing ------------------------

# An unsaved "Untitled" buffer has no backing file. Nothing to tokenise and
# nothing to restore to, so the caller falls back to a window-level entry.
kate, calls = adapter("")

assert kate.resolve_restore_id(456) is None
assert members(calls) == [WINDOW_FILE_PATH]
assert TOKEN_OPEN_URL not in members(calls)
assert kate._tokens == {}

print("OK")
