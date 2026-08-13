# dev/ - developer tooling

## `kwin-sandbox.sh`

An isolated, disposable KWin session for developing and testing BackNav's
KWin scripts (`backnav-kwin/`, `backnav-kwin-overlay/`) without touching
your real, live KWin session.

This exists because a live test of `backnav-kwin-overlay` caused a real
incident on the developer's actual desktop (visual corruption plus a
flood of window-closed events - see git history around 2026-08-10). The
sandbox runs a second, throwaway `kwin_wayland` instance in its own
1024x768 window (KWin's own supported windowed mode) under a brand new
private D-Bus session bus, so its `org.kde.KWin` can never collide with,
or be mistaken for, your real session's. Every subcommand talks to the
sandbox bus explicitly - nothing here touches your real `org.kde.KWin` or
`com.backnav.Navigator`, with the one documented exception noted under
`daemon start` below.

Confirmed live via this sandbox: `loadDeclarativeScript(path,
pluginName)` (on `org.kde.KWin`'s `/Scripting` object) is the correct way
to load a `declarativescript`-mode package's QML directly - unlike plain
`loadScript`, which force-parses the file as JavaScript and fails on
QML's `import` line.

### Quick start

```
dev/kwin-sandbox.sh start
dev/kwin-sandbox.sh fake-nav start
dev/kwin-sandbox.sh load backnav-kwin-overlay/contents/ui/main.qml backnav-overlay-dev
dev/kwin-sandbox.sh logs kwin -f      # watch for parse/runtime errors while iterating
# ...edit main.qml...
dev/kwin-sandbox.sh unload backnav-overlay-dev
dev/kwin-sandbox.sh load backnav-kwin-overlay/contents/ui/main.qml backnav-overlay-dev
dev/kwin-sandbox.sh stop
```

`fake-nav` runs `dev/fake_navigator.py`, a stand-in `com.backnav.Navigator`
D-Bus service that serves a fixed, non-empty peek state so the overlay
has something to render without needing the real daemon or real history.
Pass it a JSON file to serve custom state:
`dev/kwin-sandbox.sh fake-nav start /tmp/my-state.json` (must match the
exact shape `OverlayController.state_json()` produces).

### All subcommands

```
start [width] [height]   # default 1024x768
stop
status
env                       # eval "$(dev/kwin-sandbox.sh env)" to point your own shell's qdbus6 at it
qdbus <qdbus6 args...>    # qdbus6 against the sandbox bus, no eval needed
exec <command...>         # run anything with the sandbox bus exported
load <qml-file> [pluginName]      # loadDeclarativeScript
load-js <js-file> [pluginName]    # loadScript, for plain-JS packages
unload <pluginName>
fake-nav start [state.json]
fake-nav stop
daemon start              # runs the REAL backnav-engine daemon.py against the sandbox bus
daemon stop
logs [kwin|fakenav|daemon|dbus-daemon] [-f]
```

### The one caveat: `daemon start`

This runs the actual `backnav-engine/backnav.py`, not a fake. Internally
it follows `journalctl --user -u plasma-kwin_wayland.service` for
focus/caption/window-closed events - your REAL session's systemd unit,
since the sandbox instance isn't a systemd unit and (being empty) has no
windows of its own anyway. That journal read is read-only and harmless,
but it means daemon-sourced history will reflect your real desktop's
windows, not whatever's inside the sandbox. Fine for testing the
D-Bus/shortcut/overlay plumbing; not a way to test adapters against
sandbox-only windows.

### State

Runtime state (PID files, the sandbox's D-Bus address, logs) lives under
`${XDG_RUNTIME_DIR:-/tmp}/backnav-sandbox/` - safe to delete any time the
sandbox is stopped.
