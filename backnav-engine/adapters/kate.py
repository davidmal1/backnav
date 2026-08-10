import subprocess


class KateAdapter:
    """
    Resolves and restores a specific Kate document (tab), via Kate's own
    D-Bus interface (org.kde.kate-<pid>, confirmed live). Kate's
    Application object (/MainApplication) only hands back a "token" for
    documents *we* open ourselves (tokenOpenUrl), with no way to ask
    "what's active right now" - so unlike Konsole there's no session-id
    query to piggyback on.

    Instead this reads the main window's windowFilePath - a standard Qt
    property (org.qtproject.Qt.QWidget.windowFilePath, on /kate/MainWindow_1)
    that KDE apps set to the file backing the current view. Confirmed live:
    it tracks the active document across an internal tab switch (no window
    focus change), stays in sync with KWin's caption (which is what
    triggers detection - see main.js's TABBED_APPS), and - critically -
    doesn't carry the caption's "[*]" unsaved-changes marker, so editing a
    file doesn't look like switching to a different one. Empty for buffers
    with no backing file (e.g. an unsaved "Untitled" tab), which resolves
    to no restore id - there's nothing on disk to restore to, so this
    falls back to a plain window-level entry same as any other resolution
    failure.

    Assumes one Kate window per process, mirroring the same simplification
    already made for Konsole.
    """

    # KWin's window.resourceClass for a real Kate window - confirmed live
    # via the KWin script's own event log.
    app_name = "org.kde.kate"
    restore_type = "kate_document"

    _MAIN_WINDOW_PATH = "/kate/MainWindow_1"
    _APPLICATION_PATH = "/MainApplication"

    def resolve_restore_id(self, pid: int, title: str = ""):
        # title unused - windowFilePath is a direct, fresher query than
        # anything the caption text could tell us (see qpdfview's adapter
        # for the app that actually needs it).
        path = self._call(pid, self._MAIN_WINDOW_PATH, "org.qtproject.Qt.QWidget.windowFilePath")

        if not path:
            return None

        return f"kate:{pid}:{path}"

    def restore(self, restore_id: str) -> bool:
        _, pid, path = restore_id.split(":", 2)
        # openUrl activates the existing tab instead of duplicating it if
        # the file's already open in this instance - the same "single
        # instance" behavior `kate <path>` relies on from the CLI.
        return self._call(pid, self._APPLICATION_PATH, "org.kde.Kate.Application.openUrl", path, "") is not None

    @staticmethod
    def _call(pid, object_path, member, *args):
        try:
            result = subprocess.run(
                ["qdbus6", f"org.kde.kate-{pid}", object_path, member, *map(str, args)],
                capture_output=True,
                text=True,
                timeout=1,
            )
        except (subprocess.SubprocessError, OSError):
            return None

        if result.returncode != 0:
            return None

        return result.stdout.strip()
