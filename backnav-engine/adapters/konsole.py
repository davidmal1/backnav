import subprocess


class KonsoleAdapter:
    """
    Resolves and restores a specific Konsole tab (session), via Konsole's
    own D-Bus interface (org.kde.konsole-<pid>, confirmed live: exposes
    currentSession()/setCurrentSession() on /Windows/1). Konsole doesn't
    emit any signal when the user switches tabs internally, so detection
    piggybacks on the generic KWin caption-changed hook (see main.js) -
    this adapter's job is just turning "app=org.kde.konsole, pid=N" into a
    stable, restorable session id at the moment it's asked, and restoring
    it later.

    Assumes one Konsole window per process - the common case. Opening a
    second window from within an existing Konsole process isn't
    disambiguated here, mirroring the same "one browser = one logical
    window" simplification already made for browser tabs.
    """

    # KWin's window.resourceClass for a real Konsole window - confirmed
    # live via the KWin script's own event log. Not the plain "konsole"
    # one might guess from the binary/package name.
    app_name = "org.kde.konsole"
    restore_type = "konsole_tab"

    def resolve_restore_id(self, pid: int, title: str = ""):
        # title unused - currentSession() is a direct, fresher query than
        # anything the caption text could tell us (see qpdfview's adapter
        # for the app that actually needs it).
        session_id = self._call(pid, "currentSession")

        if session_id is None:
            return None

        return f"konsole:{pid}:{session_id}"

    def restore(self, restore_id: str) -> bool:
        _, pid, session_id = restore_id.split(":", 2)
        return self._call(pid, "setCurrentSession", session_id) is not None

    @staticmethod
    def _call(pid, method, *args):
        try:
            result = subprocess.run(
                ["qdbus6", f"org.kde.konsole-{pid}", "/Windows/1", method, *map(str, args)],
                capture_output=True,
                text=True,
                timeout=1,
            )
        except (subprocess.SubprocessError, OSError):
            return None

        if result.returncode != 0:
            return None

        return result.stdout.strip()
