from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.events.window_caption_changed import WindowCaptionChanged
from core.navigation_engine import NavigationEngine

import adapters.registry as registry


# Reproduces a real bug found live-testing the Kate adapter: an app's
# transient/modal dialog (Kate's "Open File"/"Close Document" prompts, a
# save-as dialog, etc) reports the exact SAME `app` resourceClass as its
# owning window when it briefly steals focus. Without checking `normal`,
# that focus change would (a) get misattributed to an adapter resolution
# using the *main* window's current file (adapters resolve by pid, which
# the dialog shares), spamming history with duplicate-content entries
# under the dialog's title, and (b) stomp _current_window_id, silently
# breaking caption-change detection on the real window until its next
# genuine focus event.
class FakeKateAdapter:
    app_name = "org.kde.kate"
    restore_type = "kate_document"

    def __init__(self, paths):
        self._paths = list(paths)

    def resolve_restore_id(self, pid, title=""):
        path = self._paths.pop(0)
        return None if path is None else f"kate:{pid}:{path}"

    def restore(self, restore_id):
        return True


# Only two real resolutions should ever happen: the initial focus, and the
# later caption change. The dialog focus event in between must NOT consume
# one - if it did (i.e. if the fix regressed), this list running dry or
# handing back the wrong path is exactly how that would surface.
fake_adapter = FakeKateAdapter(paths=["/tmp/a.txt", "/tmp/b.txt"])
registry.ADAPTERS_BY_APP["org.kde.kate"] = fake_adapter
registry.ADAPTERS_BY_RESTORE_TYPE["kate_document"] = fake_adapter

event_bus = EventBus()
engine = NavigationEngine(event_bus)

# 0: some other window has focus first.
event_bus.publish(FocusChanged(app="org.kde.dolphin", window_id="1", title="Files"))

# 1: Kate's main window gains focus - resolves a.txt.
event_bus.publish(FocusChanged(app="org.kde.kate", window_id="2", pid=456, title="a.txt"))
assert engine.current.restore_id == "kate:456:/tmp/a.txt"

# An "Open File" dialog pops up - same app, same pid, but a DIFFERENT
# window_id and normal=False. Must not create a new entry, must not touch
# current_window_id.
event_bus.publish(FocusChanged(app="org.kde.kate", window_id="3", pid=456, title="Open File — Kate", normal=False))
assert engine.current.restore_id == "kate:456:/tmp/a.txt", "dialog focus must not push a new entry"
assert engine.current.window_id == "2", "dialog focus must not overwrite current entry"

# The dialog closing and the user actually switching tabs afterward must
# still work normally - proves _current_window_id wasn't corrupted by the
# dialog interlude above (this caption change is only honored if it still
# matches the real window as "current").
event_bus.publish(WindowCaptionChanged(app="org.kde.kate", window_id="2", pid=456, title="b.txt"))
assert engine.current.restore_id == "kate:456:/tmp/b.txt", f"got {engine.current.restore_id!r}"

back1 = engine.back()
assert back1.title == "a.txt", f"got {back1.title!r}"

back2 = engine.back()
assert back2.title == "Files", f"got {back2.title!r}"

print("OK")
