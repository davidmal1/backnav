from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.events.window_caption_changed import WindowCaptionChanged
from core.navigation_engine import NavigationEngine

import adapters.registry as registry


# Fake adapter standing in for KonsoleAdapter - avoids shelling out to
# qdbus6/a real Konsole process in a unit test. Mimics the same duck-typed
# shape (app_name, restore_type, resolve_restore_id(pid), restore(id)),
# with a scripted sequence of session ids to hand back per call so a
# caption-change can be made to look like a real tab switch.
class FakeKonsoleAdapter:
    app_name = "org.kde.konsole"
    restore_type = "konsole_tab"

    def __init__(self, sessions):
        self._sessions = list(sessions)
        self.restored = []

    def resolve_restore_id(self, pid, title=""):
        session_id = self._sessions.pop(0)
        if session_id is None:
            return None
        return f"konsole:{pid}:{session_id}"

    def restore(self, restore_id):
        self.restored.append(restore_id)
        return True


fake_adapter = FakeKonsoleAdapter(sessions=[0, 0, 1, None])
registry.ADAPTERS_BY_APP["org.kde.konsole"] = fake_adapter
registry.ADAPTERS_BY_RESTORE_TYPE["konsole_tab"] = fake_adapter

event_bus = EventBus()
engine = NavigationEngine(event_bus)

# 0: some other window has focus first.
event_bus.publish(FocusChanged(app="org.kde.dolphin", window_id="1", title="architecture.md"))

# 1: Konsole window gains focus - resolves via the adapter (session 0).
event_bus.publish(FocusChanged(app="org.kde.konsole", window_id="2", pid=123, title="~/project"))
assert engine.current.restore_type == "konsole_tab"
assert engine.current.restore_id == "konsole:123:0"

# Caption changes but the session is still 0 (e.g. prompt/title churn within
# the same tab) - should MERGE into the existing entry, not append a new one.
event_bus.publish(WindowCaptionChanged(app="org.kde.konsole", window_id="2", pid=123, title="~/project (running)"))
assert engine.current.restore_id == "konsole:123:0"

# 2: user switches to a different Konsole tab (session 1) while the window
# stays focused - the caption-change hook should append a new, distinguishable
# entry.
event_bus.publish(WindowCaptionChanged(app="org.kde.konsole", window_id="2", pid=123, title="~/other-project"))
assert engine.current.restore_id == "konsole:123:1", f"got {engine.current.restore_id!r}"

# Adapter can't resolve a session id this time (e.g. qdbus6 call failed) -
# should gracefully fall back to a plain window-level entry rather than
# crashing or recording a bogus restore_id.
event_bus.publish(FocusChanged(app="org.kde.dolphin", window_id="1", title="architecture.md"))
event_bus.publish(FocusChanged(app="org.kde.konsole", window_id="2", pid=123, title="~/project"))
assert engine.current.restore_type is None
assert engine.current.title == "~/project"

back1 = engine.back()
assert back1.title == "architecture.md", f"got {back1.title!r}"

print("OK")
