from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.events.window_caption_changed import WindowCaptionChanged
from core.navigation_engine import NavigationEngine

import adapters.registry as registry

# --- Adapter-tracked tabs that have since been CLOSED must be skipped,
# --- not landed on.
#
# Unlike a closed window (KWin reports WindowClosed) or a closed browser
# tab (the extension reports BrowserTabClosed), closing a qpdfview/Kate
# tab produces no event anywhere the daemon can observe - the window
# stays open. So HistoryManager's dead-tab set can never learn about it.
#
# That would be survivable if restoring a closed tab did nothing. It
# doesn't: qpdfview's jumpToPageOrOpenInNewTab() and Kate's openUrl()
# both REOPEN the file. Reported live - closing qpdfview tabs, switching
# app, then navigating back resurrected every one of them.
#
# The fix is a liveness question asked at navigation time, via the
# adapter's optional live_targets()/target_of() pair.


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


def visit_pdf(stem):
    event_bus.publish(WindowCaptionChanged(
        app="qpdfview.local.qpdfview", window_id="2", pid=456, title=f"{stem} - qpdfview",
    ))


# A plain window, then three qpdfview tabs visited in turn, then away to
# another app - the exact shape of the reported session.
event_bus.publish(FocusChanged(app="org.kde.dolphin", window_id="1", title="Files"))
event_bus.publish(FocusChanged(app="qpdfview.local.qpdfview", window_id="2", pid=456, title="a - qpdfview"))
visit_pdf("b")
visit_pdf("c")
event_bus.publish(FocusChanged(app="org.kde.konsole", window_id="3", title="journalctl"))

# All three tabs are still open: back walks them all, newest first.
adapter.open_paths = {"/tmp/a.pdf", "/tmp/b.pdf", "/tmp/c.pdf"}
assert [engine.back().title for _ in range(4)] == [
    "c - qpdfview", "b - qpdfview", "a - qpdfview", "Files",
]

# Now the user closes b and c, leaving only a. Walking back from the far
# end must land on a and never on the two closed tabs - landing on either
# is what reopened them.
while engine.forward() is not None:
    pass

assert engine.current.title == "journalctl", engine.current.title

adapter.open_paths = {"/tmp/a.pdf"}
adapter.live_target_calls = 0

assert engine.back().title == "a - qpdfview", "walked onto a closed tab"

# That single back() stepped over two closed tabs (c, then b) before
# landing - and asked the adapter ONCE, not once per entry. The check
# costs a qdbus6 subprocess plus a SQLite read, on a keypress.
assert adapter.live_target_calls == 1, f"asked {adapter.live_target_calls}x in one navigation"

assert engine.back().title == "Files"

# Reopening a closed file by hand makes it reachable again. This is why the
# answer must NOT be cached into HistoryManager's dead-tab set: restore_ids
# name a path, so the reopened tab has the very same id the closed one had,
# and "once dead, always dead" would skip it forever.
adapter.open_paths = {"/tmp/a.pdf", "/tmp/b.pdf"}
assert engine.forward().title == "a - qpdfview"
assert engine.forward().title == "b - qpdfview", "a reopened tab stayed unreachable"

# An adapter that can't tell (app gone, D-Bus failed, database unreadable)
# reports None, and navigation carries on as it did before this check
# existed. Refusing to move at all would be a far worse failure than
# landing on a stale entry.
adapter.live_targets = lambda: None

while engine.forward() is not None:
    pass

assert engine.current.title == "journalctl"
assert engine.back().title == "c - qpdfview", "unknown liveness blocked navigation"

print("Closed adapter tab skip OK")
