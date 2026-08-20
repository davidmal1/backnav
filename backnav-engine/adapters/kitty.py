import json
import os
import subprocess


class KittyAdapter:
    """
    Resolves and restores a specific kitty tab, via kitty's own remote
    control protocol rather than D-Bus.

    kitty exposes nothing on the session bus at all - confirmed live, it
    owns no bus name - so the usual route every other adapter here takes
    is simply absent. What it has instead is `kitty @`, a JSON protocol
    over a Unix socket, and it answers the questions this needs better
    than any D-Bus interface in this project:

        kitty @ ls          every tab as structured JSON, with id, title
                            and is_active
        kitty @ focus-tab   switch to one, matched by numeric id,
                            creating nothing

    That means no caption parsing and no heuristic. qpdfview matches a
    filename stem against its own database with the page number as a
    tie-breaker; Kate mints tokens because it cannot enumerate anything.
    kitty is asked and answers, so this adapter is the smallest here
    despite being the only one not speaking D-Bus.

    REQUIRES a one-time setting. kitty ships `allow_remote_control no`,
    and with it off none of the above exists. Same shape as qpdfview
    needing "Restore tabs" enabled before its database is written at all
    - see that adapter, and the README.

    Detection still comes from the KWin script's caption watching (see
    TABBED_APPS in main.js), same as Konsole and Kate: kitty's title
    follows the active tab, and switching tabs inside an already-focused
    window is invisible to KWin's focus stream.
    """

    # KWin's window.resourceClass for a kitty window - confirmed live via
    # the KWin script's own event log. Plain "kitty", unlike the reverse
    # -DNS names KDE applications use.
    app_name = "kitty"
    restore_type = "kitty_tab"

    def resolve_restore_id(self, pid: int, title: str = ""):
        # title unused - ls reports is_active directly, which is a fresher
        # and unambiguous answer than the caption could give. (qpdfview is
        # the adapter that has to fall back on the caption.)
        state = self._ls(pid)

        if state is None:
            return None

        os_window = self._focused_os_window(state)

        if os_window is None:
            return None

        for tab in os_window.get("tabs", []):
            if tab.get("is_active") and tab.get("id") is not None:
                return f"kitty:{pid}:{tab['id']}"

        return None

    @staticmethod
    def _focused_os_window(state):
        """
        The OS window this pid currently has in front.

        One kitty PROCESS can own several OS windows, and each keeps its
        own active tab - so taking the first `is_active` tab in the whole
        tree answers a different question and gets it wrong whenever more
        than one window is open. KWin hands us a pid, not a window, so the
        disambiguation has to happen here.

        Caught by testing rather than by reading: a restore that had
        genuinely worked was reported as landing somewhere else, because
        resolve kept reporting the first window's tab.

        `last_focused` is the fallback, and it is the usual case rather
        than an edge one: `is_focused` is false whenever kitty is not the
        active application, which includes most of the moments this gets
        asked.
        """
        for key in ("is_focused", "last_focused"):
            for os_window in state:
                if os_window.get(key):
                    return os_window

        return state[0] if state else None

    def restore(self, restore_id: str) -> bool:
        _, pid, tab_id = restore_id.split(":", 2)

        # focus-tab, NOT new-tab or launch: it moves to an existing tab and
        # creates nothing, which is the property that decides whether an
        # app can be supported at all. Matched by id rather than title,
        # since two tabs showing the same directory are common and a title
        # match would pick whichever came first.
        return self._call(pid, "focus-tab", "--match", f"id:{tab_id}") is not None

    def live_targets(self):
        """
        Every tab id kitty currently has open, or None if that cannot be
        established.

        Cheap and exact here, where the other adapters have to work for
        it: ls already returns the whole tree, so the live set falls out
        of the same call resolve uses. Compare qpdfview, which forces a
        database write and reads it back.

        Keyed by (pid, tab_id) because tab ids are only unique within one
        kitty process, and two kitty windows are two processes.

        None rather than an empty set when kitty cannot be reached - an
        empty set reads as "nothing is open" and would strand every kitty
        entry in history.
        """
        pids = self._running_pids()

        if pids is None:
            return None

        live = set()

        for pid in pids:
            state = self._ls(pid)

            # One unreachable kitty must not condemn the others, but it
            # also must not have its own tabs declared dead - so skip it
            # and leave its entries alone by never claiming to know.
            if state is None:
                return None

            for os_window in state:
                for tab in os_window.get("tabs", []):
                    if tab.get("id") is not None:
                        live.add((str(pid), str(tab["id"])))

        return live

    @staticmethod
    def target_of(restore_id: str):
        _, pid, tab_id = restore_id.split(":", 2)
        return (pid, tab_id)

    # ---- talking to kitty ------------------------------------------------

    @staticmethod
    def _socket_for(pid):
        """
        The remote-control socket belonging to this kitty process.

        Read from KITTY_LISTEN_ON in a CHILD process rather than assumed
        from the pid. kitty exports it into everything it spawns, so a
        shell running inside kitty knows the address; kitty's own environ
        does not carry it. The conventional /tmp/kitty-<pid> is only the
        default and moves with the `listen_on` setting, so deriving the
        path would break for anyone who has changed it.
        """
        try:
            children = os.listdir(f"/proc/{pid}/task/{pid}/children")
        except OSError:
            children = []

        # /proc exposes children as a single space-separated line.
        pids = " ".join(children).split() if children else []

        for child in pids:
            try:
                with open(f"/proc/{child}/environ", "rb") as handle:
                    env = handle.read().decode("utf-8", "replace")
            except OSError:
                continue

            for entry in env.split("\0"):
                if entry.startswith("KITTY_LISTEN_ON="):
                    return entry.split("=", 1)[1]

        # Fall back to the documented default, which is right unless the
        # user has set listen_on to something else.
        default = f"/tmp/kitty-{pid}"

        return f"unix:{default}" if os.path.exists(default) else None

    def _ls(self, pid):
        raw = self._call(pid, "ls")

        if raw is None:
            return None

        try:
            return json.loads(raw)
        except ValueError:
            return None

    def _call(self, pid, *args):
        # Instance methods rather than classmethods, deliberately: `self.`
        # lookup is what lets a test replace one of these on an instance,
        # and `cls.` would walk straight past it.
        socket = self._socket_for(pid)

        if socket is None:
            return None

        try:
            result = subprocess.run(
                ["kitty", "@", "--to", socket, *args],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (subprocess.SubprocessError, OSError):
            return None

        if result.returncode != 0:
            return None

        return result.stdout.strip()

    @staticmethod
    def _running_pids():
        try:
            result = subprocess.run(
                ["pgrep", "-x", "kitty"], capture_output=True, text=True, timeout=2,
            )
        except (subprocess.SubprocessError, OSError):
            return None

        # pgrep exits 1 when nothing matches, which is not an error: it
        # means no kitty is running, and therefore no kitty tabs are live.
        if result.returncode not in (0, 1):
            return None

        return [line for line in result.stdout.split() if line.isdigit()]
