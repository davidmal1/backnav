"""
The D-Bus surface: that each method forwards to the thing that does the
work, and that SetHighlight parses its argument.

Previously untested, which is the same hole test_websocket_server.py was
written to close - an entire boundary layer with nothing exercising it,
so "the method reaches the controller but drops its argument" was a
mutation nothing in the suite could see. Thin layers are exactly where
that goes unnoticed, because there is no logic in them to draw attention
to.

The panel is the only caller of most of this and cannot report an error
(see the overlay README on logging), so a silent mis-forward here
surfaces only as the chooser quietly not responding.
"""

from unittest import mock

from core.navigator_service import NavigatorService


def raw(service, name):
    """
    The undecorated function behind a @method().

    dbus_next replaces the attribute with a wrapper that returns None
    when called directly - the declared `-> "s"` only ever reaches a
    caller through real D-Bus dispatch. Verified here rather than
    assumed: calling svc.SetHighlight("2") does run the body (the
    forward happens) but evaluates to None, so asserting on return
    values has to reach through to the original, which dbus_next keeps
    on the descriptor.
    """
    return getattr(getattr(type(service), name), "__DBUS_METHOD").fn.__get__(service)


def service():
    engine, overlay = mock.Mock(), mock.Mock()

    return NavigatorService(engine, overlay), engine, overlay


# The wrapper really does discard the return while still running the
# body - the thing that makes raw() necessary above.
svc, engine, overlay = service()
assert svc.SetHighlight("2") is None
overlay.set_highlight.assert_called_once_with(2)

# ---- SetHighlight, the one method with any logic in it ----------------

svc, engine, overlay = service()

assert raw(svc, "SetHighlight")("2") == "ok"
overlay.set_highlight.assert_called_once_with(2)

# The row arrives as a STRING deliberately - see the comment on the
# method - so the conversion is part of the contract, not incidental.
overlay.set_highlight.reset_mock()
raw(svc, "SetHighlight")("0")
overlay.set_highlight.assert_called_once_with(0)

# Rejected rather than allowed to raise. An exception here would cross a
# D-Bus boundary into a QML caller that cannot report it.
overlay.set_highlight.reset_mock()
assert raw(svc, "SetHighlight")("not-a-row") == "bad-index"
overlay.set_highlight.assert_not_called()

# ---- Everything else is pure forwarding, and pinned as such ----------

svc, engine, overlay = service()

raw(svc, "MoveHighlight")("back")
overlay.move_highlight.assert_called_once_with("back")

raw(svc, "ConfirmSelection")()
overlay.confirm.assert_called_once_with()

raw(svc, "CancelSelection")()
overlay.cancel.assert_called_once_with()

# Not the same as cancel: dismiss raises nothing. Pinned because the two
# are one word apart at the call site and the difference is invisible
# until it drags the user off the window they just clicked.
raw(svc, "DismissSelection")()
overlay.dismiss.assert_called_once_with()
overlay.cancel.assert_called_once_with()

overlay.state_json.return_value = '{"active": false}'
assert raw(svc, "GetPeekState")() == '{"active": false}'

# ---- Navigate both moves and reports where it landed -----------------

svc, engine, overlay = service()

landed = mock.Mock(window_id="42", restore_type=None, restore_id=None)
engine.back.return_value = landed

with mock.patch("core.navigator_service.restore_item") as fake_restore:
    assert raw(svc, "Navigate")("back") == "42"
    fake_restore.assert_called_once_with(landed)

engine.back.assert_called_once_with()
engine.forward.assert_not_called()

with mock.patch("core.navigator_service.restore_item"):
    raw(svc, "Navigate")("forward")

engine.forward.assert_called_once_with()

# An exhausted history returns an empty string rather than a window id -
# KWin has nothing to raise, and must not be handed the string "None".
svc, engine, overlay = service()
engine.back.return_value = None

with mock.patch("core.navigator_service.restore_item") as fake_restore:
    assert raw(svc, "Navigate")("back") == ""
    fake_restore.assert_not_called()

print("OK")
