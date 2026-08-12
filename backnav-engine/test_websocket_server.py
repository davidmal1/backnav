"""
The WebSocket handler's message dispatch and connection bookkeeping.

Previously untested, which is how "a disconnect is never announced to the
engine" could sit here unnoticed - every engine-level test published
BrowserDisconnected by hand, so the whole suite passed with nothing
actually publishing it.
"""

import asyncio
import json

from core.events.browser_disconnected import BrowserDisconnected
from core.events.browser_tab_changed import BrowserTabChanged
from core.events.browser_tab_closed import BrowserTabClosed
from core.events.browser_tabs_alive import BrowserTabsAlive
from core.events.event_bus import EventBus
from core import websocket_server
from core.websocket_server import _make_handler


class Recorder:
    """Collects everything published, in order."""

    def __init__(self, event_bus):
        self.events = []

        for event_type in (
            BrowserTabChanged, BrowserTabClosed, BrowserTabsAlive, BrowserDisconnected,
        ):
            event_bus.subscribe(event_type, self.events.append)

    def of(self, event_type):
        return [e for e in self.events if isinstance(e, event_type)]


class FakeSocket:
    """
    Minimal stand-in for a websockets connection: async-iterates the
    messages it was given, then ends - which is what a close looks like
    from the handler's point of view.

    `pause` lets a test hold one socket open partway through so a second
    can connect underneath it, which is the fast-reconnect case below.
    """

    def __init__(self, messages, pause=None):
        self._messages = messages
        self._pause = pause

    async def __aiter__(self):
        for message in self._messages:
            yield message

        if self._pause is not None:
            await self._pause.wait()


def reset():
    websocket_server.clients.clear()
    websocket_server.connections.clear()

    event_bus = EventBus()

    return event_bus, Recorder(event_bus), _make_handler(event_bus)


def tab(**overrides):
    message = {
        "event": "tab", "instanceId": "inst-1", "browser": "chromium",
        "id": 7, "windowId": 3, "title": "A Tab", "url": "https://a.example",
    }
    message.update(overrides)

    return json.dumps(message)


# ---- Each message type reaches the bus in the right shape ------------

event_bus, recorder, handler = reset()

asyncio.run(handler(FakeSocket([
    tab(),
    json.dumps({"event": "keepalive", "instanceId": "inst-1"}),
    json.dumps({"event": "tab_closed", "instanceId": "inst-1", "id": 7}),
    json.dumps({"event": "tabs_alive", "instanceId": "inst-1", "ids": [1, 2, 3]}),
])))

changed = recorder.of(BrowserTabChanged)
assert len(changed) == 1, [type(e).__name__ for e in recorder.events]
assert changed[0].connection_id == "inst-1"
assert changed[0].tab_id == 7
assert changed[0].title == "A Tab"

closed = recorder.of(BrowserTabClosed)
assert len(closed) == 1 and closed[0].tab_id == 7

alive = recorder.of(BrowserTabsAlive)
assert len(alive) == 1
assert alive[0].tab_ids == frozenset({1, 2, 3}), alive[0].tab_ids
assert alive[0].connection_id == "inst-1"

# A keepalive is traffic and nothing else. It must not be parsed as a tab
# message - it carries none of those fields, so doing so would KeyError
# and kill the connection outright.
assert len(recorder.events) == 4, [type(e).__name__ for e in recorder.events]

# ---- Closing announces itself ----------------------------------------

disconnects = recorder.of(BrowserDisconnected)

assert len(disconnects) == 1, "the engine was never told the extension went away"
assert disconnects[0].connection_id == "inst-1"
assert recorder.events[-1] is disconnects[0], "disconnect should be last"
assert not websocket_server.connections, websocket_server.connections

# ---- A fast reconnect must not disconnect the LIVE connection --------
#
# An MV3 worker respawns with a brand new socket under the same
# instanceId, and the new one can register before the old one's close is
# processed. Announcing that close would tell the engine to release a
# connection that is currently working - unbinding a live browser.


async def fast_reconnect():
    event_bus, recorder, handler = reset()

    resume = asyncio.Event()

    # The old socket sends, then hangs around unclosed.
    old = asyncio.create_task(handler(FakeSocket([tab()], pause=resume)))
    await asyncio.sleep(0)

    # The new socket connects under the same instanceId and completes,
    # replacing the mapping.
    await handler(FakeSocket([tab(title="Reconnected")]))

    # Only now does the old one finally close.
    resume.set()
    await old

    return recorder


recorder = asyncio.run(fast_reconnect())
disconnects = recorder.of(BrowserDisconnected)

assert len(disconnects) == 1, (
    "expected exactly one disconnect - the superseded socket must stay "
    f"quiet: {len(disconnects)}"
)

reset()

print("OK")
