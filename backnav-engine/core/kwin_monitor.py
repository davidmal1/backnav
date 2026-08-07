import json
import subprocess

from core.events.focus_changed import FocusChanged
from core.events.window_caption_changed import WindowCaptionChanged
from core.events.window_closed import WindowClosed


class KWinMonitor:

    def events(self):
        proc = subprocess.Popen(
            [
                "journalctl",
                "--user",
                "-u",
                "plasma-kwin_wayland.service",
                "-f",
                "-n",
                "0",
                "-o",
                "cat",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

        for line in proc.stdout:
            line = line.strip()

            pos = line.find("{")
            if pos == -1:
                continue

            try:
                data = json.loads(line[pos:])
            except json.JSONDecodeError:
                continue

            # Navigation shortcuts go straight from the KWin script to the
            # daemon over D-Bus (see core/navigator_service.py) since KWin
            # needs the answer synchronously to activate a window - only
            # focus-change, caption-change and window-closed events still
            # flow through this journalctl feed.
            event_type = data.get("type")

            if event_type not in ("focus", "caption", "closed"):
                continue

            window = data["window"]
            # KWin's Date.now() is milliseconds; Event.timestamp is seconds.
            timestamp = data["timestamp"] / 1000

            if event_type == "closed":
                yield WindowClosed(window_id=window["id"], timestamp=timestamp)
                continue

            # True unless the script explicitly says otherwise - keeps
            # older-format lines (or a stale/un-upgraded script instance)
            # behaving as "normal" rather than getting silently dropped.
            normal = data.get("flags", {}).get("normal", True)

            if event_type == "caption":
                yield WindowCaptionChanged(
                    app=window["app"],
                    window_id=window["id"],
                    pid=window["pid"],
                    title=window["title"],
                    normal=normal,
                    timestamp=timestamp,
                )
                continue

            yield FocusChanged(
                app=window["app"],
                window_id=window["id"],
                pid=window["pid"],
                title=window["title"],
                normal=normal,
                timestamp=timestamp,
            )
