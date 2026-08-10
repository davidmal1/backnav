import asyncio
import threading

from dbus_next.aio import MessageBus

from core.events.event_bus import EventBus
from core.kwin_monitor import KWinMonitor
from core.navigation_engine import NavigationEngine
from core.navigator_service import OBJECT_PATH, SERVICE_NAME, NavigatorService
from core.overlay_controller import OverlayController
from core.websocket_server import run


def _run_kwin_monitor(event_bus):
    for event in KWinMonitor().events():
        event_bus.publish(event)


async def main():
    print("BackNav starting...")

    event_bus = EventBus()
    engine = NavigationEngine(event_bus)

    # The KWin script calls into this over D-Bus when the back/forward
    # shortcut fires, then activates whatever window id comes back -
    # KWin is the only thing that can actually raise a window.
    dbus_bus = await MessageBus().connect()

    # Drives the hold+repeat-taps overlay by watching KGlobalAccel's own
    # press/repeat/release signals for the same shortcuts directly (see
    # OverlayController's docstring for why) - shares this same bus
    # connection since dbus_next lets one MessageBus both export our
    # service and act as a client to another one (kglobalaccel).
    overlay = OverlayController(engine)
    await overlay.attach(dbus_bus)

    dbus_bus.export(OBJECT_PATH, NavigatorService(engine, overlay))
    await dbus_bus.request_name(SERVICE_NAME)

    threading.Thread(
        target=_run_kwin_monitor,
        args=(event_bus,),
        daemon=True,
    ).start()

    await run(event_bus)


if __name__ == "__main__":
    asyncio.run(main())
