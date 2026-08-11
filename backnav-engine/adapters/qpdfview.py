import os
import re
import sqlite3
import subprocess


class QpdfviewAdapter:
    """
    Resolves and restores a qpdfview tab, via qpdfview's own D-Bus
    interface (local.qpdfview/MainWindow, confirmed live) plus its
    on-disk SQLite tab database - qpdfview, unlike Kate/Konsole, exposes
    no method or property anywhere that reports which tab/file is
    currently active. Confirmed live: no generic
    org.qtproject.Qt.QWidget interface on /MainWindow (unlike Okular's
    Shell object), and currentPage() returns a bare page number only -
    no path, no tab index.

    Detection works around that gap like this:
    1. The KWin script's caption-watching (see TABBED_APPS in main.js)
       reports the window title on every tab switch. qpdfview's title
       format (confirmed live, and in source -
       MainWindow::setWindowTitleForCurrentTab) is
       "<tab text>[*] - qpdfview", where Qt's own "[*]" placeholder is
       already swapped for "*" or "" by the time this ever sees it - so
       the caption gives us the active tab's filename *stem* (no
       directory, no extension), never a directly usable path.
    2. To turn that stem into a restorable absolute path, this forces a
       fresh write of qpdfview's own tab-persistence database
       (saveDatabase() over D-Bus - confirmed live that its write lands
       before the subprocess call returns, no extra delay needed), then
       reads back the row whose filename stem matches the caption and
       whose currentPage matches currentPage() (a real, live, unambiguous
       query) as a tie-breaker. This is a heuristic (matching by name and
       page rather than a direct id) - the same kind of trade-off already
       accepted for Konsole/Kate's own workarounds - but it's the only
       route qpdfview exposes to an actual path at all.

    This requires the user to enable "Restore tabs" once in qpdfview's
    own Preferences (Behavior tab). Confirmed live: saveTabs() - and
    therefore saveDatabase() - is a complete no-op, writing nothing,
    unless that setting (mainWindow/restoreTabs in qpdfview.conf) is on;
    it's off by default. Same one-time-setup shape as the Thunderbird
    extension's TLS certificate exception.

    Restoring uses jumpToPageOrOpenInNewTab(path, page) - deliberately
    NOT open()/openInNewTab(). Confirmed live (and in source,
    MainWindow::open): plain open() unconditionally replaces whatever
    tab currently happens to be focused, even when the target file is
    already open in a different tab - it never searches other tabs at
    all, so using it here could silently destroy an unrelated tab's
    content. openInNewTab() unconditionally adds a new tab, duplicating
    one that's already open (the same flaw found in Okular).
    jumpToPageOrOpenInNewTab() is the only one of the three that first
    searches every open tab for a path match - confirmed live, including
    the case where the match is a backgrounded (non-current) tab - and
    only falls back to opening a new tab if none is found.

    qpdfview's D-Bus service name is fixed ("local.qpdfview") regardless
    of pid - confirmed live - unlike Kate/Konsole's per-pid service
    names, since the desktop file always launches it with --unique (one
    shared instance for the whole session). pid is accepted here only to
    match the shared adapter interface; it plays no part in addressing
    the D-Bus call.
    """

    # KWin's window.resourceClass for a real qpdfview window - confirmed
    # live via the KWin script's own event log.
    app_name = "qpdfview.local.qpdfview"
    restore_type = "qpdfview_tab"

    _SERVICE = "local.qpdfview"
    _OBJECT_PATH = "/MainWindow"
    _INTERFACE = "local.qpdfview.MainWindow"

    _DATABASE_PATH = os.path.expanduser("~/.local/share/qpdfview/qpdfview/database")

    # Mirrors MainWindow::setWindowTitleForCurrentTab()'s format string:
    # tabText + (" (N / M)" if currentPageInWindowTitle) + "[*] - qpdfview"
    # + (" (instanceName)" if instanceNameInWindowTitle). Both optional
    # settings default to off, but the regex tolerates them either way.
    _TITLE_RE = re.compile(r"^(?P<stem>.*?)(?: \(\d+ / \d+\))?\*? - qpdfview(?: \(.*\))?$")

    def resolve_restore_id(self, pid: int, title: str = ""):
        match = self._TITLE_RE.match(title or "")

        if not match or not match.group("stem"):
            # No tab open at all (bare "qpdfview" title), or a transient
            # dialog's title (e.g. "Open in new tab") slipping through -
            # nothing to resolve, same fallback as Kate's unsaved buffer.
            return None

        page = self._call("currentPage")

        if page is None:
            return None

        self._call("saveDatabase")

        path = self._lookup_path(match.group("stem"), page)

        if path is None:
            return None

        return f"qpdfview:{page}:{path}"

    def restore(self, restore_id: str) -> bool:
        _, page, path = restore_id.split(":", 2)
        return self._call("jumpToPageOrOpenInNewTab", path, page) is not None

    def live_targets(self):
        """
        Absolute paths of every tab qpdfview currently has open, or None
        if that can't be established right now.

        Exists because restore() reopens rather than no-ops: closing a
        tab produces no event anywhere the daemon can see (KWin only
        reports whole windows, and there's no qpdfview equivalent of the
        browsers' BrowserTabClosed), so an entry for a closed tab stays
        forever alive-looking, and jumpToPageOrOpenInNewTab() cheerfully
        opens a brand new tab for it. Navigation has to ask, at the
        moment it's about to land somewhere, rather than being told.

        None - not an empty set - on any failure. An empty set means
        "asked, and nothing is open"; conflating the two would let a
        broken D-Bus call or an unreadable database declare the entire
        qpdfview history dead and silently strand every one of its
        entries.
        """
        # Strict here, unlike resolve_restore_id's fire-and-forget use:
        # without a confirmed fresh write, the table is last session's
        # tabs, and trusting it would mark still-open tabs as closed.
        # ("" is a successful void return - test for None specifically.)
        if self._call("saveDatabase") is None:
            return None

        rows = self._read_tabs()

        if rows is None:
            return None

        return {row_path for row_path, _ in rows}

    @staticmethod
    def target_of(restore_id: str) -> str:
        # Liveness is a property of the FILE, not of the page we happened
        # to be on: the tab is still the same tab after scrolling, and the
        # recorded page is almost always stale by the time we walk back to
        # it.
        _, _page, path = restore_id.split(":", 2)
        return path

    def _read_tabs(self):
        try:
            con = sqlite3.connect(self._DATABASE_PATH)
            try:
                return con.execute(
                    "SELECT filePath, currentPage FROM tabs_v5 WHERE instanceName = ''"
                ).fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            return None

    def _lookup_path(self, stem, page):
        rows = self._read_tabs()

        if rows is None:
            return None

        candidates = [
            row_path for row_path, _ in rows
            if os.path.splitext(os.path.basename(row_path))[0] == stem
        ]

        if not candidates:
            return None

        for row_path, row_page in rows:
            if row_path in candidates and str(row_page) == str(page):
                return row_path

        # No exact page match - e.g. saveDatabase()'s write raced this
        # read, or two tabs share a filename stem and only one page
        # matched. Fall back to the filename match alone rather than
        # giving up entirely; matches the "heuristic, not bulletproof"
        # trade-off already documented above.
        return candidates[0]

    @staticmethod
    def _call(member, *args):
        try:
            result = subprocess.run(
                [
                    "qdbus6",
                    QpdfviewAdapter._SERVICE,
                    QpdfviewAdapter._OBJECT_PATH,
                    f"{QpdfviewAdapter._INTERFACE}.{member}",
                    *map(str, args),
                ],
                capture_output=True,
                text=True,
                timeout=1,
            )
        except (subprocess.SubprocessError, OSError):
            return None

        if result.returncode != 0:
            return None

        return result.stdout.strip()
