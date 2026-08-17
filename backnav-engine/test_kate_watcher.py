"""
The documentClosed subscription: that the right signal prunes the token
cache, and that nothing else does.

The handler is fed by another application's D-Bus surface, on the same bus
connection that serves NavigatorService and the KGlobalAccel
subscriptions. So the interesting cases are the hostile ones - a signal
with an empty body, a wrong-typed token, a method call that happens to
share a member name - because any of those raising would take the
daemon's message loop with it, and consuming a message that is not ours
would break the other subscribers.

attach() itself is not exercised here: it does one AddMatch call and hands
the handler to dbus_next, so a test of it would be a test of dbus_next.
make_handler exists to keep the part with judgement in it separable.
"""

from unittest import mock

from dbus_next import MessageType

from adapters.kate import KateAdapter
from core.kate_watcher import MATCH_RULE, make_handler


def signal(interface="org.kde.Kate.Application", member="documentClosed",
           body=("TOKEN-A",), message_type=MessageType.SIGNAL):
    return mock.Mock(
        message_type=message_type,
        interface=interface,
        member=member,
        body=list(body),
    )


def loaded_adapter():
    """A KateAdapter with two documents already tokenised."""
    kate = KateAdapter()
    kate._tokens = {
        (456, "/tmp/a.txt"): "TOKEN-A",
        (456, "/tmp/b.txt"): "TOKEN-B",
    }

    return kate, make_handler(kate)


# ---- the match rule has to be right or nothing is ever delivered -----

# Asserted literally because a typo here fails silently: the bus simply
# never forwards the signal, the handler never runs, and closed documents
# quietly keep appearing in the switcher with nothing in any log.
assert MATCH_RULE == (
    "type='signal',interface='org.kde.Kate.Application',member='documentClosed'"
), MATCH_RULE

# No sender= clause - that is what makes one rule cover every Kate
# process, including ones started later.
assert "sender=" not in MATCH_RULE

# ---- the signal prunes exactly the document it names -----------------

kate, handle = loaded_adapter()

assert handle(signal(body=("TOKEN-A",))) is None, "the handler must not consume messages"
assert kate.live_targets() == {(456, "/tmp/b.txt")}, kate._tokens

# The pruned entry is now unrestorable, which is the point - restore has
# no token to activate with.
assert kate.restore("kate:456:/tmp/a.txt") is False

# ...and its sibling is untouched. A signal for one document must not
# clear the cache wholesale.
assert kate._tokens[(456, "/tmp/b.txt")] == "TOKEN-B"

# An unknown token is not an error. Kate emits documentClosed once per
# outstanding token, so repeats for one we have already dropped are the
# normal case rather than a fault.
assert handle(signal(body=("TOKEN-A",))) is None
assert handle(signal(body=("NEVER-SEEN",))) is None
assert kate.live_targets() == {(456, "/tmp/b.txt")}

# ---- everything else is ignored, and ignored WITHOUT raising ---------

kate, handle = loaded_adapter()
untouched = dict(kate._tokens)

for description, message in [
    ("a method call sharing the member name", signal(message_type=MessageType.METHOD_CALL)),
    ("another interface's documentClosed", signal(interface="org.kde.Other")),
    ("a different Kate signal", signal(member="exiting")),
    ("an empty body", signal(body=())),
    ("a non-string token", signal(body=(12345,))),
    ("a None token", signal(body=(None,))),
]:
    assert handle(message) is None, description
    assert kate._tokens == untouched, f"{description} changed the cache"

# ---- what the engine's skip loop sees --------------------------------

kate, handle = loaded_adapter()

# target_of has to line up with live_targets or the comparison in
# NavigationEngine silently reports everything dead. Pinned together,
# since they are only ever correct relative to each other.
assert kate.target_of("kate:456:/tmp/a.txt") in kate.live_targets()

# The pid is part of the identity, not decoration: the same path open in a
# different Kate process is a different document.
assert kate.target_of("kate:999:/tmp/a.txt") not in kate.live_targets()

handle(signal(body=("TOKEN-A",)))
assert kate.target_of("kate:456:/tmp/a.txt") not in kate.live_targets()

# Never None, unlike qpdfview's live_targets - there is no query to fail,
# so there is no "could not tell" to report. Worth pinning because the
# engine treats None as "assume alive" and would skip nothing.
assert kate.live_targets() is not None
assert KateAdapter().live_targets() == set()

# ---- reopening by hand brings it back --------------------------------

# Forgetting must not be recorded as "dead forever". A restore_id names a
# file path, so reopening the same file yields the identical id - and a
# permanent dead-mark would skip past the reopened document for good.
kate, handle = loaded_adapter()
handle(signal(body=("TOKEN-A",)))

assert kate.target_of("kate:456:/tmp/a.txt") not in kate.live_targets()

kate._call = lambda pid, path, member, *a: (
    "/tmp/a.txt" if member.endswith("windowFilePath") else "TOKEN-A2"
)
assert kate.resolve_restore_id(456) == "kate:456:/tmp/a.txt"
assert kate.target_of("kate:456:/tmp/a.txt") in kate.live_targets(), (
    "a reopened document stayed dead"
)

print("OK")
