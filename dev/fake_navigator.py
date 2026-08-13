#!/usr/bin/env python3
"""
A fake com.backnav.Navigator D-Bus service, for testing the QML overlay
(backnav-kwin-overlay/contents/ui/main.qml) without needing the real
backnav-engine daemon or real navigation history.

Only implements the two methods the overlay/KWin scripts actually call:
GetPeekState() (polled by the overlay's Timer) and Navigate() (called by
backnav-kwin/contents/code/main.js on a plain tap). Both just return
canned/fixed data - this is a rendering/lifecycle test double, not a
behavioral stand-in for NavigationEngine.

Usage:
    python3 fake_navigator.py [state.json]

If a state.json path is given, its contents are served verbatim from
GetPeekState() (must already be the exact JSON string shape
OverlayController.state_json() produces). Otherwise a fixed built-in
state with a few fake entries is served, so the overlay has something
non-empty to render by default.

Meant to be run with DBUS_SESSION_BUS_ADDRESS pointed at the sandbox bus
kwin-sandbox.sh sets up (see its `fake-nav` subcommand) - never run this
against your real session bus, it will squat on the real
com.backnav.Navigator name and break the real daemon if it's running.
"""
import asyncio
import json
import os
import sys

from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method

DEFAULT_STATE = {
    "active": True,
    "direction": "back",
    "entries": [
        {"app": "org.kde.konsole", "title": "fake entry one"},
        {"app": "org.kde.kate", "title": "fake entry two"},
        {"app": "firefox", "title": "fake entry three"},
    ],
    "highlightIndex": 1,
    "activateWindowId": None,
}


def load_state():
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            return json.load(f)
    return DEFAULT_STATE


class FakeNavigator(ServiceInterface):
    def __init__(self, state):
        super().__init__("com.backnav.Navigator")
        self._state_json = json.dumps(state)

    @method()
    def GetPeekState(self) -> "s":
        return self._state_json

    @method()
    def Navigate(self, direction: "s") -> "s":
        return ""


async def main():
    state = load_state()

    bus = await MessageBus().connect()
    bus.export("/com/backnav/Navigator", FakeNavigator(state))
    await bus.request_name("com.backnav.Navigator")

    # Unbuffered-ish: sandbox script greps this to confirm startup.
    print("fake navigator up on", os.environ.get("DBUS_SESSION_BUS_ADDRESS"), flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
