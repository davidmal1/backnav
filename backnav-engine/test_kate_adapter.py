from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.events.window_caption_changed import WindowCaptionChanged
from core.navigation_engine import NavigationEngine

import adapters.registry as registry


# Fake adapter standing in for KateAdapter - avoids shelling out to qdbus6/a
# real Kate process in a unit test. Mimics the same duck-typed shape
# (app_name, restore_type, resolve_restore_id(pid), restore(id)), with a
# scripted sequence of file paths to hand back per call so a caption-change
# can be made to look like a real tab switch. `None` stands in for an
# unsaved "Untitled" buffer - no backing file, so nothing to resolve.
class FakeKateAdapter:
    app_name = "org.kde.kate"
    restore_type = "kate_document"

    def __init__(self, paths):
        self._paths = list(paths)
        self.restored = []

    def resolve_restore_id(self, pid, title=""):
        path = self._paths.pop(0)
        if path is None:
            return None
        return f"kate:{pid}:{path}"

    def restore(self, restore_id):
        self.restored.append(restore_id)
        return True


fake_adapter = FakeKateAdapter(paths=["/tmp/a.txt", "/tmp/a.txt", "/tmp/b.txt", None])
registry.ADAPTERS_BY_APP["org.kde.kate"] = fake_adapter
registry.ADAPTERS_BY_RESTORE_TYPE["kate_document"] = fake_adapter

event_bus = EventBus()
engine = NavigationEngine(event_bus)

# 0: some other window has focus first.
event_bus.publish(FocusChanged(app="org.kde.dolphin", window_id="1", title="Files"))

# 1: Kate window gains focus - resolves via the adapter (a.txt).
event_bus.publish(FocusChanged(app="org.kde.kate", window_id="2", pid=456, title="a.txt"))
assert engine.current.restore_type == "kate_document"
assert engine.current.restore_id == "kate:456:/tmp/a.txt"

# Caption changes but the path is still a.txt (e.g. the "[*]" modified
# marker toggling on an edit) - should MERGE into the existing entry, not
# append a new one. This is the whole reason resolution reads
# windowFilePath rather than the caption/title.
event_bus.publish(WindowCaptionChanged(app="org.kde.kate", window_id="2", pid=456, title="a.txt [*]"))
assert engine.current.restore_id == "kate:456:/tmp/a.txt"

# 2: user switches to a different Kate tab (b.txt) while the window stays
# focused - the caption-change hook should append a new, distinguishable
# entry.
event_bus.publish(WindowCaptionChanged(app="org.kde.kate", window_id="2", pid=456, title="b.txt"))
assert engine.current.restore_id == "kate:456:/tmp/b.txt", f"got {engine.current.restore_id!r}"

# Adapter can't resolve a path this time (e.g. an unsaved Untitled buffer,
# or the qdbus6 call failed) - should gracefully fall back to a plain
# window-level entry rather than crashing or recording a bogus restore_id.
event_bus.publish(FocusChanged(app="org.kde.dolphin", window_id="1", title="Files"))
event_bus.publish(FocusChanged(app="org.kde.kate", window_id="2", pid=456, title="Untitled"))
assert engine.current.restore_type is None
assert engine.current.title == "Untitled"

back1 = engine.back()
assert back1.title == "Files", f"got {back1.title!r}"

print("OK")
