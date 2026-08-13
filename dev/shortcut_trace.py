"""
Live, human-readable trace of KGlobalAccel's hold/repeat/release signals,
plus the daemon's resulting peek state.

Exists because the decisive open question about the overlay gesture -
does globalShortcutReleased fire once per *key tap* or once per *whole
combo release*? - cannot be answered by reading code. It is a property
of KGlobalAccel's own dispatch, and the only way to know is to press
real keys and count what comes back. Raw `dbus-monitor` output does
technically contain the answer, but three interleaved signal types at
the keyboard auto-repeat rate (~25-30/sec) is not something you can
eyeball; this collapses runs of repeats into a single counted line so a
gesture reads as a handful of lines instead of a hundred.

The second column is the daemon's own view (direction + count from
NavigatorService.GetPeekState()), sampled on each signal, so you can see
the controller's accumulator move in lockstep with the physical keys -
and, crucially, see what it finally committed on release.

Usage - point it at whichever bus owns the shortcuts:

    # sandbox
    DBUS_SESSION_BUS_ADDRESS="$(cat "${XDG_RUNTIME_DIR:-/tmp}"/backnav-sandbox/dbus.env)" \
        python3 dev/shortcut_trace.py

    # real session (no env override needed)
    python3 dev/shortcut_trace.py

Ctrl+C prints a summary tally of each signal type.
"""
import asyncio
import os
import sys
import time

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backnav-engine"),
)

from dbus_next.aio import MessageBus

# Only these two are interesting; every other KWin action (Alt+Tab, the
# screenshot keys, ...) shares this same component and would otherwise
# drown the trace.
WATCHED = {"BackNavBack", "BackNavForward"}

START = time.monotonic()
tally = {"PRESSED": 0, "REPEATED": 0, "RELEASED": 0}

# Collapses a run of REPEATED signals for the same action into one line
# that grows a counter, rather than one line per auto-repeat tick.
_run = {"kind": None, "name": None, "count": 0, "first": 0.0}


def _stamp():
    return f"{time.monotonic() - START:7.3f}s"


def _flush_run():
    if _run["kind"] is None:
        return

    if _run["count"] > 1:
        span = time.monotonic() - _run["first"]
        rate = _run["count"] / span if span > 0 else 0
        print(
            f"           ... {_run['kind']} x{_run['count']} over "
            f"{span:.2f}s (~{rate:.0f}/sec)",
            flush=True,
        )

    _run["kind"] = None
    _run["count"] = 0


class Tracer:
    def __init__(self):
        self._navigator = None

    async def attach(self, bus):
        introspection = await bus.introspect("org.kde.kglobalaccel", "/component/kwin")
        proxy = bus.get_proxy_object(
            "org.kde.kglobalaccel", "/component/kwin", introspection
        )
        component = proxy.get_interface("org.kde.kglobalaccel.Component")

        component.on_global_shortcut_pressed(self._make_handler("PRESSED"))
        component.on_global_shortcut_repeated(self._make_handler("REPEATED"))
        component.on_global_shortcut_released(self._make_handler("RELEASED"))

        # Optional: the daemon may not be running, in which case the trace
        # is still perfectly useful, just without the state column.
        try:
            nav_introspection = await bus.introspect(
                "com.backnav.Navigator", "/com/backnav/Navigator"
            )
            nav_proxy = bus.get_proxy_object(
                "com.backnav.Navigator", "/com/backnav/Navigator", nav_introspection
            )
            self._navigator = nav_proxy.get_interface("com.backnav.Navigator")
            print("attached to KGlobalAccel + com.backnav.Navigator", flush=True)
        except Exception as exc:
            print(f"attached to KGlobalAccel (no daemon: {exc})", flush=True)

    def _make_handler(self, kind):
        def handler(component_unique, shortcut_unique, timestamp):
            if shortcut_unique not in WATCHED:
                return

            tally[kind] += 1

            if kind == "REPEATED" and _run["kind"] == "REPEATED" and _run["name"] == shortcut_unique:
                _run["count"] += 1
                return

            _flush_run()
            _run.update(
                {"kind": kind, "name": shortcut_unique, "count": 1, "first": time.monotonic()}
            )

            print(f"{_stamp()}  {kind:<8} {shortcut_unique}", flush=True)
            asyncio.create_task(self._report_state(kind))

        return handler

    async def _report_state(self, kind):
        if self._navigator is None:
            return

        # A tick of slack: the controller handles the same signal we just
        # saw, and there is no ordering guarantee between two independent
        # subscribers to it.
        await asyncio.sleep(0.02)
        state = await self._navigator.call_get_peek_state()
        print(f"           -> state {state}", flush=True)


async def main():
    bus = await MessageBus().connect()
    tracer = Tracer()
    await tracer.attach(bus)

    print(
        "watching BackNavBack / BackNavForward - press the shortcut now "
        "(Ctrl+C to stop)",
        flush=True,
    )
    await asyncio.Event().wait()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    _flush_run()
    print(
        f"\ntally: pressed={tally['PRESSED']} repeated={tally['REPEATED']} "
        f"released={tally['RELEASED']}"
    )
