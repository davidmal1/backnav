"""
Listens for Kate closing a document, so closed documents stop being
offered in the switcher.

Without this a closed Kate document is not harmful - restore() calls
activate(token), which does nothing for a token Kate no longer knows (see
adapters/kate.py) - but it is not right either. The row stays in the
chooser, and selecting it still raises the Kate WINDOW, so you land in
Kate looking at whatever document happens to be current rather than the
one you picked. Pruning turns that into the entry simply not being there.

ONE match rule for every Kate process, rather than a subscription per
pid. Kate processes come and go while the daemon runs, and tracking that
would mean introspecting each new pid from the KWin monitor thread and
tearing the subscription down again on exit - a lot of lifecycle for a
signal we can catch by interface alone. The signal carries the token, the
token identifies the document by itself, so the sender does not matter.

The other reason to avoid per-pid work: resolve_restore_id runs on the
KWin monitor thread, not the event loop, so kicking off an async
subscription from there would need call_soon_threadsafe and a queue. This
needs none of that - the rule is added once at startup and the handler
runs on the loop.
"""

from dbus_next import Message, MessageType

from adapters.kate import KateAdapter
from adapters.registry import ADAPTERS_BY_APP

_INTERFACE = "org.kde.Kate.Application"
_MEMBER = "documentClosed"

# No sender= clause on purpose: that is what makes this one rule cover
# every Kate process, including ones started after the daemon.
MATCH_RULE = f"type='signal',interface='{_INTERFACE}',member='{_MEMBER}'"


async def attach(bus, adapter=None):
    """
    Subscribe for the lifetime of the daemon. There is no detach - the
    rule costs nothing while no Kate is running, since a rule that matches
    nothing delivers nothing.
    """
    if adapter is None:
        adapter = ADAPTERS_BY_APP.get(KateAdapter.app_name)

    if adapter is None:
        return None

    # The bus only forwards signals someone has asked for, so without this
    # the handler below is simply never called - and silently, which is
    # the failure mode to watch for if closed Kate rows come back.
    await bus.call(Message(
        destination="org.freedesktop.DBus",
        path="/org/freedesktop/DBus",
        interface="org.freedesktop.DBus",
        member="AddMatch",
        signature="s",
        body=[MATCH_RULE],
    ))

    handler = make_handler(adapter)
    bus.add_message_handler(handler)

    return handler


def make_handler(adapter):
    """
    Built separately from attach() so it can be tested without a bus - the
    filtering below is the part with any judgement in it, and standing up
    a real D-Bus connection to exercise it would test dbus_next rather
    than this.
    """
    def handle(message):
        # Returning None lets the message carry on to other handlers.
        # Returning anything else would consume it, which is not ours to
        # do on a shared bus connection - the same connection is serving
        # NavigatorService and the KGlobalAccel subscriptions.
        if message.message_type is not MessageType.SIGNAL:
            return None

        if message.interface != _INTERFACE or message.member != _MEMBER:
            return None

        # Checked rather than assumed - this is fed by another
        # application's D-Bus surface, and an IndexError here would take
        # the daemon's whole message loop with it.
        if not message.body:
            return None

        # No type check on the token, deliberately. One was written here
        # and removed after it survived mutation testing: forget_token
        # compares with ==, which cannot raise and cannot match a
        # non-string against the strings in the cache, so an isinstance
        # guard had no observable effect at all. A wrong-typed token
        # already does nothing.
        adapter.forget_token(message.body[0])

        return None

    return handle
