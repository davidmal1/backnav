"""
Seeding history from KWin's window list at startup.

Without it a daemon that starts mid-session knows nothing at all: the
journal is followed with `-n 0`, so there is no backlog, and the KWin
script emits its initial activeWindow only when the SCRIPT loads, which a
daemon restart does not do. Measured before this existed: back() returned
None and walk_view() returned ([], -1) until the user had switched between
two windows by mouse.

Survivable while BackNav is a second switcher next to Alt+Tab. Not
survivable at all once it IS the Alt+Tab binding, which is the point of
this - a switcher that does nothing after every daemon restart is not a
switcher.

The daemon cannot fetch the list itself, so the overlay panel relays it:
GetPeekState reports seedNeeded, the panel answers with
Workspace.stackingOrder, which it already reads for icons.
"""

import json
import os
from unittest import mock

os.environ["BACKNAV_CONFIG"] = "/nonexistent/backnavrc"

from core.events.browser_tab_changed import BrowserTabChanged  # noqa: E402
from core.events.event_bus import EventBus  # noqa: E402
from core.events.focus_changed import FocusChanged  # noqa: E402
from core.events.window_closed import WindowClosed  # noqa: E402
from core.navigation_engine import NavigationEngine  # noqa: E402
from core.navigator_service import NavigatorService  # noqa: E402
from core.overlay_controller import OverlayController  # noqa: E402

WINDOWS = [
    {"windowId": "w1", "app": "org.kde.dolphin", "title": "Files"},
    {"windowId": "w2", "app": "brave-browser", "title": "Brave"},
    {"windowId": "w3", "app": "org.kde.kate", "title": "notes.md"},
]


def raw(service, name):
    """The undecorated function behind a @method() - see test_navigator_service."""
    return getattr(getattr(type(service), name), "__DBUS_METHOD").fn.__get__(service)


def fresh():
    bus = EventBus()
    return bus, NavigationEngine(bus)


def titles(engine):
    return [item.title for item in engine._history.all_items()]


# ---- an unseeded daemon really is blind ------------------------------

# The condition this exists to fix, pinned so it cannot quietly return.
bus, engine = fresh()

assert engine.back() is None
assert engine.walk_view(8) == ([], -1)

# ---- seeding fills it, newest last -----------------------------------

engine.seed(WINDOWS)

# stackingOrder runs bottom to top, so the caller sends oldest first and
# the topmost window has to end up at the FRONT. Getting this backwards
# would put the window you are already looking at at the far end of the
# list, so the first press would jump somewhere unrelated.
assert titles(engine) == ["notes.md", "Brave", "Files"], titles(engine)

# And back() now works immediately, which is the whole point.
assert engine.back().title == "Brave"

# ---- seeding stops once there is anything to lose --------------------

# A second seed would push stale window-level entries over history the
# user has built since, undoing their actual navigation.
engine.seed([{"windowId": "w9", "app": "other", "title": "Later"}])
assert "Later" not in titles(engine), titles(engine)

# The guard is EMPTY HISTORY, not "have I seeded before". Anything that
# put an entry there closes the door, whether it was a seed or the user.
bus, engine = fresh()
bus.publish(FocusChanged(app="org.kde.kate", window_id="k1", title="notes.md"))
engine.seed(WINDOWS)

assert titles(engine) == ["notes.md"], titles(engine)

# ---- an EMPTY seed does not count as having been seeded --------------

# The failure this exists for, seen live 2026-08-19. At login the daemon
# and KWin start together, so the panel answers before the session has
# opened anything and the list is empty. Under a once-only flag that
# useless seed blocked every later one, and a freshly booted machine knew
# only the windows it had watched the user focus by hand.
bus, engine = fresh()
engine.seed([])

assert engine.seeded is False, "an empty seed counted as seeded"

# So the offer stands, and the next one with something in it lands.
engine.seed(WINDOWS)
assert titles(engine) == ["notes.md", "Brave", "Files"], titles(engine)
assert engine.seeded is True

# ---- a dead entry does not count as being populated ------------------

# The failure that made a real login look broken, 2026-08-19. KDE focuses
# ksplashqml (and ksmserver-logout-greeter) while the session starts, and
# KWin reports both as NORMAL windows, so they land in history like
# anything else. Moments later they are gone.
#
# Guarding on "history is not empty" counted those corpses and concluded
# the daemon was populated, so the seed never went out - on a machine
# where nothing was reachable at all. back() returned None while the
# daemon insisted it had been seeded.
bus, engine = fresh()
bus.publish(FocusChanged(app="ksplashqml", window_id="splash", title="splash"))

assert engine.seeded is True, "a live window should count"

bus.publish(WindowClosed(window_id="splash"))

assert engine.back() is None, "nothing should be reachable"
assert engine.seeded is False, "a dead entry counted as populated"

# ...so the seed still lands, and the corpse is simply outranked by it.
engine.seed(WINDOWS)
assert titles(engine)[:3] == ["notes.md", "Brave", "Files"], titles(engine)
assert engine.back().title == "Brave"

# ---- junk in the list is skipped, not fatal --------------------------

# Fed from QML, which cannot report an error to anyone, so a malformed
# entry has to cost that entry and nothing else.
bus, engine = fresh()
engine.seed([
    {"windowId": "w1", "app": "org.kde.dolphin", "title": "Files"},
    {"windowId": "", "app": "no-id", "title": "skipped"},
    {"app": "missing-id", "title": "skipped"},
    {"windowId": "w2", "title": "missing app"},
    {"windowId": "w3", "app": "org.kde.kate"},
])

# The last has no title and is kept, falling back to the app name - a
# window with no caption is still somewhere you can go.
assert titles(engine) == ["org.kde.kate", "Files"], titles(engine)

# ---- a seeded entry is superseded, not duplicated --------------------

# The reason the supersede rule had to land first. Seeding writes a
# window-level entry for every browser, so without it every browser would
# show two rows the moment its extension reported a tab.
bus, engine = fresh()
engine.seed(WINDOWS)

bus.publish(FocusChanged(app="brave-browser", window_id="w2", title="Brave"))
bus.publish(BrowserTabChanged(browser="chromium", connection_id="c1",
                              window_id=99, tab_id=1, title="ABC Sport"))

assert titles(engine).count("Brave") == 0, titles(engine)
assert "ABC Sport" in titles(engine), titles(engine)

# ---- the daemon asks, exactly until it is answered -------------------

bus, engine = fresh()
overlay = OverlayController(engine)

assert json.loads(overlay.state_json())["seedNeeded"] is True

overlay.seed_windows(WINDOWS)

assert json.loads(overlay.state_json())["seedNeeded"] is False, "kept asking after seeding"

# ---- the D-Bus surface -----------------------------------------------

engine_mock, overlay_mock = mock.Mock(), mock.Mock()
svc = NavigatorService(engine_mock, overlay_mock)

assert raw(svc, "SeedWindows")(json.dumps(WINDOWS)) == "ok"
overlay_mock.seed_windows.assert_called_once_with(WINDOWS)

# Malformed input is refused rather than raised. An exception here would
# cross a D-Bus boundary into a QML caller that cannot report it, and
# would take the daemon's message loop with it.
overlay_mock.seed_windows.reset_mock()
assert raw(svc, "SeedWindows")("not json at all") == "bad-json"
overlay_mock.seed_windows.assert_not_called()

# Valid JSON that is not a list is refused too - json.loads would happily
# return a dict or an int, and the engine expects to iterate.
for payload in ('{"windowId": "w1"}', '42', '"a string"', 'null'):
    assert raw(svc, "SeedWindows")(payload) == "bad-json", payload

overlay_mock.seed_windows.assert_not_called()

# An empty list is legitimate input, not junk: a session that genuinely
# has no normal windows open yet. It is accepted and passed on - and the
# engine then declines to treat it as a seed, so the panel keeps offering
# (see the empty-seed case above).
assert raw(svc, "SeedWindows")("[]") == "ok"
overlay_mock.seed_windows.assert_called_once_with([])

print("OK")
