import subprocess


class KateAdapter:
    """
    Resolves and restores a specific Kate document (tab), via Kate's own
    D-Bus interface (org.kde.kate-<pid>, confirmed live). Kate's
    Application object (/MainApplication) offers no way to ask "what's
    open" or "what's active right now" - so unlike Konsole there's no
    session-id query to piggyback on. Enumerating documents is genuinely
    not possible; the whole interface is activate, activateSession,
    openInput, openUrl, setCursor and the tokenOpenUrl pair.

    It DOES hand back a "token" per document, though, and not only for
    documents we opened ourselves - this said otherwise until 2026-08-14,
    which was wrong and had shaped the design around it. tokenOpenUrl on
    an already-open path returns that document's existing token rather
    than duplicating the tab, so any open document can be tokenised. See
    resolve_restore_id, which relies on exactly that.

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

    def __init__(self):
        # (pid, path) -> Kate's own token for that document.
        #
        # Minted once per document rather than per resolve, for two
        # reasons. It saves a qdbus6 subprocess on every Kate tab switch,
        # and - more importantly - tokenOpenUrl emits a caption change,
        # which is the very thing that TRIGGERS detection. Minting on
        # every resolve would risk feeding itself.
        #
        # Never invalidated. A token for a closed document is harmless
        # because activate() on a dead one does nothing (see restore),
        # and a token from an exited Kate is unreachable anyway - its
        # whole org.kde.kate-<pid> bus name is gone. Entries are bounded
        # by documents-opened-per-Kate-process, so there is nothing here
        # worth reaping.
        self._tokens = {}

    def resolve_restore_id(self, pid: int, title: str = ""):
        # title unused - windowFilePath is a direct, fresher query than
        # anything the caption text could tell us (see qpdfview's adapter
        # for the app that actually needs it).
        path = self._call(pid, self._MAIN_WINDOW_PATH, "org.qtproject.Qt.QWidget.windowFilePath")

        if not path:
            return None

        # Tokenised HERE, while the document is provably open, because
        # there is no way to get a token later without risking the very
        # bug this exists to prevent - the only source of tokens is
        # tokenOpenUrl, and calling that at restore time on a since-closed
        # document reopens it.
        #
        # Safe to call on an already-open path: it returns that document's
        # EXISTING token rather than duplicating the tab, and it does not
        # raise Kate's window. Both confirmed live 2026-08-14 - three calls
        # on one path returned the identical token, and KWin logged a
        # caption event with no focus event. And the document named here is
        # by definition the one already active, since the path came from
        # windowFilePath a moment ago, so the implied "switch to it" is a
        # no-op.
        key = (pid, path)

        if key not in self._tokens:
            token = self._call(
                pid, self._APPLICATION_PATH,
                "org.kde.Kate.Application.tokenOpenUrl", path, "",
            )

            if token:
                self._tokens[key] = token

        return f"kate:{pid}:{path}"

    def live_targets(self):
        """
        The documents believed to be open, for NavigationEngine's skip loop.

        Kate cannot be asked this - there is no enumeration call, which is
        the whole reason resolve mints tokens in the first place. So the
        token cache IS the answer: an entry is in it because the document
        was open when it was resolved, and it leaves when Kate says the
        document closed (see forget_token, driven by core/kate_watcher.py).

        Unlike qpdfview's version this never returns None. There is no "the
        query failed" case to signal, because there is no query.

        An entry with no token reads as dead here, which is right rather
        than incidental: restore() cannot do anything without one, so
        skipping past it beats landing on it.
        """
        return set(self._tokens)

    def target_of(self, restore_id: str):
        _, pid, path = restore_id.split(":", 2)

        return (int(pid), path)

    def forget_token(self, token: str) -> bool:
        """
        Kate has closed the document this token named.

        Searched by value because the signal carries only the token, not
        the path. The cache is small - one entry per document per Kate
        process - so a scan costs nothing worth indexing around.

        Copied before iterating: this runs on the daemon's event loop while
        resolve_restore_id runs on the KWin monitor thread, and iterating a
        dict another thread is inserting into raises.

        Deliberately NOT recording the token as dead. A restore_id names a
        file path, so reopening the file by hand yields the identical id,
        and "once dead, always dead" would skip the reopened document
        forever. Forgetting is enough: the next resolve mints a fresh token
        and the entry is live again.
        """
        for key, cached in list(self._tokens.items()):
            if cached == token:
                self._tokens.pop(key, None)
                return True

        return False

    def restore(self, restore_id: str) -> bool:
        _, pid, path = restore_id.split(":", 2)

        # activate(token), NOT openUrl(path).
        #
        # openUrl means "open this file", and on a document the user has
        # since closed it does exactly that - walking back over a closed
        # Kate tab resurrected every one of them. The old comment here was
        # right that openUrl activates rather than duplicates when the file
        # is still open; it just did not cover the case where it is not.
        #
        # activate() means "switch to this document if it still exists" and
        # creates nothing. Confirmed live 2026-08-14: called with the token
        # of a document that had just been closed, it returned success,
        # changed nothing, and did NOT bring the file back. Called with an
        # entirely made-up token, likewise - no error, no phantom tab.
        #
        # That silent no-op is the same contract the rest of BackNav already
        # assumes for a restore target that has gone away, matching windows
        # and browser tabs rather than being a special case.
        token = self._tokens.get((int(pid), path))

        if token is None:
            # No token means resolve never managed to mint one, which in
            # practice means the tokenOpenUrl call failed. Deliberately NOT
            # falling back to openUrl: that is the reopen bug, and a
            # navigation that quietly does nothing is much easier to live
            # with than one that resurrects a file you closed.
            return False

        return self._call(
            pid, self._APPLICATION_PATH,
            "org.kde.Kate.Application.activate", token,
        ) is not None

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
