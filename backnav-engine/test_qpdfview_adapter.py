import os
import sqlite3
import tempfile
import unittest.mock as mock

from adapters.qpdfview import QpdfviewAdapter
from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.events.window_caption_changed import WindowCaptionChanged
from core.navigation_engine import NavigationEngine

import adapters.registry as registry


# --- Unit tests against the real QpdfviewAdapter's title parsing and
# --- SQLite lookup, without shelling out to qdbus6 or a real qpdfview
# --- process - _call is mocked, the database is a real temp SQLite file
# --- (same schema qpdfview itself writes) so the lookup query is
# --- exercised for real.
def make_database(tmp_path, rows):
    con = sqlite3.connect(tmp_path)
    con.execute(
        "CREATE TABLE tabs_v5 (filePath TEXT, instanceName TEXT, tabIndex INTEGER, "
        "currentPage INTEGER, PRIMARY KEY (instanceName, tabIndex))"
    )
    con.executemany(
        "INSERT INTO tabs_v5 (filePath, instanceName, tabIndex, currentPage) VALUES (?, '', ?, ?)",
        rows,
    )
    con.commit()
    con.close()


with tempfile.TemporaryDirectory() as tmp_dir:
    db_path = os.path.join(tmp_dir, "database")
    make_database(db_path, [
        ("/home/user/Downloads/report.pdf", 0, 3),
        ("/home/user/Documents/article.pdf", 1, 9),
    ])

    adapter = QpdfviewAdapter()

    with mock.patch.object(QpdfviewAdapter, "_DATABASE_PATH", db_path), \
         mock.patch.object(QpdfviewAdapter, "_call") as fake_call:

        # currentPage() -> "3" (matches the report.pdf row); saveDatabase()
        # is fire-and-forget, its return value is ignored either way.
        fake_call.side_effect = lambda member, *args: {"currentPage": "3"}.get(member)

        restore_id = adapter.resolve_restore_id(pid=999, title="report - qpdfview")
        assert restore_id == "qpdfview:3:/home/user/Downloads/report.pdf", f"got {restore_id!r}"

        # A background/other tab's stem, at a DIFFERENT page than
        # currentPage() reports - proves the filename-stem match is what
        # actually selects the row, with currentPage only a tie-breaker
        # for when several tabs share a stem (not the case here).
        fake_call.side_effect = lambda member, *args: {"currentPage": "3"}.get(member)
        restore_id = adapter.resolve_restore_id(pid=999, title="article - qpdfview")
        assert restore_id == "qpdfview:3:/home/user/Documents/article.pdf", f"got {restore_id!r}"

        # No tab open at all - bare title, nothing to resolve.
        assert adapter.resolve_restore_id(pid=999, title="qpdfview") is None

        # A transient dialog's title slipping through (e.g. "Open in new
        # tab") doesn't match the "<stem> - qpdfview" pattern at all.
        assert adapter.resolve_restore_id(pid=999, title="Open in new tab") is None

        # Filename with no matching database row (e.g. saveDatabase()'s
        # write hasn't landed yet, or restoreTabs is disabled so the
        # table is simply empty) - resolves to nothing rather than a
        # bogus restore_id.
        fake_call.side_effect = lambda member, *args: {"currentPage": "1"}.get(member)
        assert adapter.resolve_restore_id(pid=999, title="unknown-file - qpdfview") is None

        # restore() dispatches to jumpToPageOrOpenInNewTab specifically -
        # not open()/openInNewTab() - see the adapter's docstring for why
        # (open() is destructive to whatever tab is currently focused,
        # openInNewTab() always duplicates).
        fake_call.side_effect = None
        fake_call.return_value = "true"
        assert adapter.restore("qpdfview:5:/home/user/Downloads/report.pdf") is True
        fake_call.assert_called_with("jumpToPageOrOpenInNewTab", "/home/user/Downloads/report.pdf", "5")

        # --- live_targets(): what navigation uses to avoid landing on -
        # --- and thereby REOPENING - a tab that's since been closed.

        # saveDatabase() is a void D-Bus method: a successful call returns
        # an empty string, which is falsy. Testing it for truthiness rather
        # than for None would treat every success as a failure and disable
        # the check entirely.
        fake_call.side_effect = lambda member, *args: "" if member == "saveDatabase" else None
        assert adapter.live_targets() == {
            "/home/user/Downloads/report.pdf",
            "/home/user/Documents/article.pdf",
        }, adapter.live_targets()

        # Liveness is keyed on the file, not the page - the recorded page is
        # stale as soon as the user scrolls, and scrolling doesn't close a tab.
        assert adapter.target_of("qpdfview:99:/home/user/Downloads/report.pdf") \
            == "/home/user/Downloads/report.pdf"

        # saveDatabase() failed, so the table is last session's tabs. That
        # must report None ("can't tell"), never an empty or stale set - a
        # stale set would declare still-open tabs closed and strand them.
        fake_call.side_effect = lambda member, *args: None
        assert adapter.live_targets() is None

    # Database missing entirely (restoreTabs never enabled) - again None
    # rather than an empty set, which would read as "nothing is open" and
    # silently make every qpdfview entry in history unreachable.
    with mock.patch.object(QpdfviewAdapter, "_DATABASE_PATH", os.path.join(tmp_dir, "absent")), \
         mock.patch.object(QpdfviewAdapter, "_call", return_value=""):
        assert adapter.live_targets() is None

print("Adapter unit tests OK")


# --- Integration test against NavigationEngine, same style as
# --- test_kate_adapter.py/test_konsole_adapter.py - a fake adapter
# --- stands in so this doesn't depend on a real qpdfview process.
class FakeQpdfviewAdapter:
    app_name = "qpdfview.local.qpdfview"
    restore_type = "qpdfview_tab"

    def __init__(self, paths):
        self._paths = list(paths)

    def resolve_restore_id(self, pid, title=""):
        path = self._paths.pop(0)
        return None if path is None else f"qpdfview:1:{path}"

    def restore(self, restore_id):
        return True


fake_adapter = FakeQpdfviewAdapter(paths=["/tmp/a.pdf", "/tmp/a.pdf", "/tmp/b.pdf", None])
registry.ADAPTERS_BY_APP["qpdfview.local.qpdfview"] = fake_adapter
registry.ADAPTERS_BY_RESTORE_TYPE["qpdfview_tab"] = fake_adapter

event_bus = EventBus()
engine = NavigationEngine(event_bus)

# 0: some other window has focus first.
event_bus.publish(FocusChanged(app="org.kde.dolphin", window_id="1", title="Files"))

# 1: qpdfview window gains focus - resolves via the adapter (a.pdf).
event_bus.publish(FocusChanged(app="qpdfview.local.qpdfview", window_id="2", pid=456, title="a - qpdfview"))
assert engine.current.restore_type == "qpdfview_tab"
assert engine.current.restore_id == "qpdfview:1:/tmp/a.pdf"

# Caption changes but the file is still a.pdf (e.g. page-in-title churn) -
# should MERGE into the existing entry, not append a new one.
event_bus.publish(WindowCaptionChanged(app="qpdfview.local.qpdfview", window_id="2", pid=456, title="a (2 / 9) - qpdfview"))
assert engine.current.restore_id == "qpdfview:1:/tmp/a.pdf"

# 2: user switches to a different qpdfview tab (b.pdf) while the window
# stays focused - the caption-change hook should append a new entry.
event_bus.publish(WindowCaptionChanged(app="qpdfview.local.qpdfview", window_id="2", pid=456, title="b - qpdfview"))
assert engine.current.restore_id == "qpdfview:1:/tmp/b.pdf", f"got {engine.current.restore_id!r}"

# Adapter can't resolve this time (e.g. saveDatabase()'s write hasn't
# landed, or restoreTabs is off) - should gracefully fall back to a plain
# window-level entry rather than crashing or recording a bogus restore_id.
event_bus.publish(FocusChanged(app="org.kde.dolphin", window_id="1", title="Files"))
event_bus.publish(FocusChanged(app="qpdfview.local.qpdfview", window_id="2", pid=456, title="c - qpdfview"))
assert engine.current.restore_type is None
assert engine.current.title == "c - qpdfview"

back1 = engine.back()
assert back1.title == "Files", f"got {back1.title!r}"

print("Engine integration OK")
