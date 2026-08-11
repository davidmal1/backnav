"""
Minimal real-component harness for exercising OverlayController's
hold/repeat/release state machine against genuine physical key events
inside the isolated kwin-sandbox.sh bus.

This is NOT the full backnav.py. The real daemon also starts KWinMonitor,
which follows the REAL session's `journalctl -u plasma-kwin_wayland.service`
- irrelevant and unwanted here, since the sandbox has no windows of its
own and we do not want the sandbox's behaviour entangled with the real
desktop's window events.

It is also NOT a mock: it wires up the actual NavigationEngine,
OverlayController and NavigatorService, and merely seeds them with a
handful of fake FocusChanged events so peek()/step() have real
history to walk. What is under test is the D-Bus/signal plumbing.

Usage (from the repo root):
    dev/kwin-sandbox.sh start
    dev/kwin-sandbox.sh exec python3 dev/sandbox_daemon.py &
    dev/kwin-sandbox.sh load-js backnav-kwin/contents/code/main.js backnav-dev
    dev/kwin-sandbox.sh load backnav-kwin-overlay/contents/ui/main.qml backnav-overlay-dev

Then focus the sandbox window and use the sandbox's own shortcuts
(Ctrl+Alt+Shift+B / Ctrl+Alt+Shift+N by default - see kwin-sandbox.sh;
they deliberately differ from the real session's Meta+Tab, because the
outer compositor matches global shortcuts first and swallows anything it
already claims).
"""
import asyncio
import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backnav-engine"),
)

from dbus_next.aio import MessageBus

from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.navigation_engine import NavigationEngine
from core.navigator_service import OBJECT_PATH, SERVICE_NAME, NavigatorService
from core.overlay_controller import OverlayController

# Deliberately more entries than the overlay's 8-row preview window, and
# far more than any one test needs. An earlier 5-entry version kept
# running out mid-session: a few taps walk the cursor to the oldest entry,
# after which back() correctly returns None and the overlay renders
# nothing - which looks exactly like "the gesture is broken" and cost two
# separate rounds of false diagnosis. With this many, a test can tap
# freely without the history quietly becoming the variable under test.
FAKE_WINDOWS = [
    ("org.kde.konsole", "fake-1", "Konsole - session A"),
    ("org.kde.kate", "fake-2", "Kate - notes.md"),
    ("firefox", "fake-3", "Firefox - BackNav issue tracker"),
    ("org.kde.dolphin", "fake-4", "Dolphin - Home"),
    ("org.kde.okular", "fake-5", "Okular - manual.pdf"),
    ("org.kde.konsole", "fake-6", "Konsole - session B"),
    ("org.kde.gwenview", "fake-7", "Gwenview - screenshot.png"),
    ("firefox", "fake-8", "Firefox - KWin scripting docs"),
    ("org.kde.kate", "fake-9", "Kate - overlay_controller.py"),
    ("org.kde.spectacle", "fake-10", "Spectacle"),
    ("org.kde.dolphin", "fake-11", "Dolphin - Projects/backnav"),
    ("thunderbird", "fake-12", "Thunderbird - Inbox"),
    ("org.kde.okular", "fake-13", "Okular - kwin-scripting.pdf"),
    ("org.kde.konsole", "fake-14", "Konsole - session C"),
    ("firefox", "fake-15", "Firefox - dbus-next docs"),
]


async def main():
    event_bus = EventBus()
    engine = NavigationEngine(event_bus)

    for app, window_id, title in FAKE_WINDOWS:
        event_bus.publish(FocusChanged(app=app, window_id=window_id, title=title))

    bus = await MessageBus().connect()

    overlay = OverlayController(engine)
    await overlay.attach(bus)

    bus.export(OBJECT_PATH, NavigatorService(engine, overlay))
    await bus.request_name(SERVICE_NAME)

    print(
        f"sandbox daemon up: {len(FAKE_WINDOWS)} fake history entries seeded, "
        "overlay attached",
        flush=True,
    )
    await asyncio.Event().wait()


asyncio.run(main())
