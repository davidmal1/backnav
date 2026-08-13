from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.events.window_caption_changed import WindowCaptionChanged
from core.navigation_engine import NavigationEngine

import adapters.registry as registry

# --- Adapter-tracked tabs that have since been CLOSED must be skipped,
# --- both when walking and when rendering the switcher panel.
#
# Unlike a closed window (KWin reports WindowClosed) or a closed browser
# tab (the extension reports BrowserTabClosed), closing a qpdfview/Kate
# tab produces no event anywhere the daemon can observe - the window
# stays open. So HistoryManager's dead-tab set can never learn about it.
#
# That would be survivable if restoring a closed tab did nothing. It
# doesn't: qpdfview's jumpToPageOrOpenInNewTab() reopens the file.
# Reported live on the browser-model branch - closing qpdfview tabs,
# switching app, then navigating back resurrected every one of them.
#
# The fix is a liveness question asked at navigation time, via the
# adapter's optional live_targets()/target_of() pair. This branch adds a
# cost constraint the browser model didn't have: walk_view() renders the
# panel by walking with back(), and the overlay polls it every 80ms, so the
# answer has to be shared across a whole walk rather than fetched per row.
# See NavigationEngine._liveness_scope().


class FakeAdapter:
    app_name = "qpdfview.local.qpdfview"
    restore_type = "qpdfview_tab"

    def __init__(self):
        self.open_paths = set()
        self.live_target_calls = 0

    def resolve_restore_id(self, pid, title=""):
        # "<stem> - qpdfview" -> the path we pretend that tab holds.
        return f"qpdfview:1:/tmp/{title.split(' - ')[0]}.pdf"

    def restore(self, restore_id):
        return True

    def live_targets(self):
        self.live_target_calls += 1
        return set(self.open_paths)

    @staticmethod
    def target_of(restore_id):
        _, _page, path = restore_id.split(":", 2)
        return path


adapter = FakeAdapter()
registry.ADAPTERS_BY_APP["qpdfview.local.qpdfview"] = adapter
registry.ADAPTERS_BY_RESTORE_TYPE["qpdfview_tab"] = adapter

event_bus = EventBus()
engine = NavigationEngine(event_bus)


def settle():
    """Abandon any open walk without reordering, so each phase starts clean."""
    engine._history.restore_walk((0, set()))


def titles(entries):
    return [item.title for item in entries]


# A plain window, then three qpdfview tabs visited in turn, then away to
# another app - the shape of the reported session. MRU order ends up
# journalctl, c, b, a, Files.
event_bus.publish(FocusChanged(app="org.kde.dolphin", window_id="1", title="Files"))
event_bus.publish(FocusChanged(app="qpdfview.local.qpdfview", window_id="2", pid=456, title="a - qpdfview"))
event_bus.publish(WindowCaptionChanged(app="qpdfview.local.qpdfview", window_id="2", pid=456, title="b - qpdfview"))
event_bus.publish(WindowCaptionChanged(app="qpdfview.local.qpdfview", window_id="2", pid=456, title="c - qpdfview"))
event_bus.publish(FocusChanged(app="org.kde.konsole", window_id="3", title="journalctl"))

# All three tabs still open: a walk reaches every one of them.
adapter.open_paths = {"/tmp/a.pdf", "/tmp/b.pdf", "/tmp/c.pdf"}
assert [engine.back().title for _ in range(4)] == [
    "c - qpdfview", "b - qpdfview", "a - qpdfview", "Files",
]

# Now the user closes b and c, leaving only a. Walking must land on a and
# never on the two closed tabs - landing on either is what reopened them.
settle()
adapter.open_paths = {"/tmp/a.pdf"}
adapter.live_target_calls = 0

assert engine.back().title == "a - qpdfview", "walked onto a closed tab"

# That single back() stepped over two closed tabs (c, then b) before
# landing - and asked the adapter ONCE, not once per entry.
assert adapter.live_target_calls == 1, f"asked {adapter.live_target_calls}x in one navigation"

assert engine.back().title == "Files"

# The switcher panel must not offer rows a tap can never land on either.
settle()
entries, highlight = engine.walk_view(4)
assert titles(entries) == ["journalctl", "a - qpdfview", "Files"], titles(entries)
assert highlight == 0, highlight

# Rendering the whole panel is ONE question, not one per row. This is the
# constraint the browser model never had: walk_view() builds the panel with
# a back() per row, and the overlay polls it every 80ms for as long as a
# gesture is held - so a snapshot scoped per back() would mean a qdbus6
# subprocess plus a SQLite read per row, ~12x a second.
#
# Measured with every tab open, so that EVERY back() in the render meets a
# qpdfview entry - with rows already dead only the first one does, and the
# count can't tell a shared snapshot from an unshared one.
settle()
adapter.open_paths = {"/tmp/a.pdf", "/tmp/b.pdf", "/tmp/c.pdf"}
adapter.live_target_calls = 0

entries, _ = engine.walk_view(5)
assert titles(entries) == [
    "journalctl", "c - qpdfview", "b - qpdfview", "a - qpdfview", "Files",
], titles(entries)
assert adapter.live_target_calls == 1, f"panel render asked {adapter.live_target_calls}x"

# The snapshot must not outlive the walk, though - a tab closed between two
# gestures has to be noticed by the next one.
settle()
adapter.open_paths = set()
assert titles(engine.walk_view(4)[0]) == ["journalctl", "Files"], "stale snapshot reused across gestures"

# Reopening a closed file by hand makes it reachable again. This is why the
# answer must NOT be cached into HistoryManager's dead-tab set: restore_ids
# name a path, so the reopened tab has the very same id the closed one had,
# and "once dead, always dead" would skip it forever.
settle()
adapter.open_paths = {"/tmp/b.pdf"}
assert engine.back().title == "b - qpdfview", "a reopened tab stayed unreachable"

# An adapter that can't tell (app gone, D-Bus failed, database unreadable)
# reports None, and navigation carries on as it did before this check
# existed. Refusing to move at all would be a far worse failure than
# landing on a stale entry.
settle()
adapter.live_targets = lambda: None
assert engine.back().title == "c - qpdfview", "unknown liveness blocked navigation"

print("Closed adapter tab skip OK")
