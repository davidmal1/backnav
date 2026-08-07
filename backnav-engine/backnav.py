import asyncio
import threading

from dbus_next.aio import MessageBus

from core.events.event_bus import EventBus
from core.kwin_monitor import KWinMonitor
from core.navigation_engine import NavigationEngine
from core.navigator_service import OBJECT_PATH, SERVICE_NAME, NavigatorService
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
    dbus_bus.export(OBJECT_PATH, NavigatorService(engine))
    await dbus_bus.request_name(SERVICE_NAME)

    threading.Thread(
        target=_run_kwin_monitor,
        args=(event_bus,),
        daemon=True,
    ).start()

    await run(event_bus)


if __name__ == "__main__":
    asyncio.run(main())
