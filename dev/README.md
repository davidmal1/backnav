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

## Things that have actually gone wrong

Each of these cost real time, and each looks like something else while it
is happening. They are written down because none of them announces itself.

### Never `pkill -f` a sandbox process

```
pkill -f 'dev/sandbox_daemon\.py'     # NO
```

The pattern matches the invoking shell's own command line, so the shell
running the `pkill` is itself a match and dies with the target. What you
see is your terminal vanishing, which reads as a crash rather than as the
command working exactly as written.

Use `dev/kwin-sandbox.sh stop`, or explicit pids from `ps`.

### `stop` cannot see anything started with `exec`

`cmd_exec` runs its command with the sandbox bus exported and nothing
else - no pidfile, no bookkeeping. `cmd_stop` checks
`daemon`/`fakenav`/`kwin`/`shell`/`launcher` pidfiles, and if all five are
dead it prints:

```
sandbox is not running
```

...which can be false. An `exec`-launched process carries on with no
script node and no pidfile to reach it by. One survived from 2026-08-11 to
2026-08-14 that way, still holding a since-deleted worktree open through
its cwd:

```
$ readlink /proc/32033/cwd
/home/david/Projects/backnav-mru (deleted)
```

Finding these means looking, not asking:

```
ps -eo pid,lstart,args | grep -E 'sandbox_daemon|kwin-sandbox|fake_navigator' | grep -v grep
```

Then kill by explicit pid. This is the one case where `pkill -f` is most
tempting and still wrong.

### Hot-loaded QML can outlive `unloadScript`

`unloadScript` returning `true`, and `isScriptLoaded` then returning
`false`, does **not** guarantee the QML is gone. A
`loadDeclarativeScript`'d `Window` and its `Timer` can survive as orphans
with no script node left to unload them by.

Measured 2026-08-13 on the live session: with `backnav-overlay` reporting
unloaded and only the `backnav` event producer left - which makes no D-Bus
calls at all - `GetPeekState` was still arriving at a full 80ms cadence
from `kwin_wayland` itself. On screen it showed up as a second, older
switcher panel drawn over the real one, still rendering whatever the
daemon reported.

Two consequences:

- **Counting instances by poll rate only works in a freshly restarted
  KWin.** The rule of thumb is ~37-38 `GetPeekState` calls in 3s per live
  instance, but each orphan adds another 37-38, so in a session that has
  seen hot-loads the count proves nothing.

  ```
  timeout 3 dbus-monitor --session "interface='com.backnav.Navigator'" > /tmp/poll.txt
  grep -c GetPeekState /tmp/poll.txt
  ```

  Via a file on purpose. Piping `timeout ... | grep -c` directly prints
  nothing and exits 143: the `SIGTERM` reaches `grep` as well, so it dies
  before it can report its count. Grouping as
  `{ timeout 3 dbus-monitor ... || true; } | grep -c` also works if you
  want a one-liner.

- **Only a compositor restart clears them**, and orphans accumulate
  silently across a session. On Wayland that means logging out - there is
  no `--replace`, and restarting `plasma-kwin_wayland.service` ends the
  graphical session with every application in it.

### `unloadScript` takes the package id, and `backnav` is a package

The event producer's package id is `backnav` - one character away from the
project's own name, and easy to type while meaning "the whole thing" or
while guessing at a probe's name. Unloading it stops focus tracking dead:

- no error, the call returns `true`;
- nothing on screen changes;
- the daemon keeps running and keeps answering D-Bus;
- history simply stops updating, and you find out at the next navigation.

The two real ids are `backnav` (event producer) and `backnav-overlay`
(the panel), which `kpackagetool6 --type KWin/Script --list` will confirm.
To check what is loaded right now:

```
gdbus call --session --dest org.kde.KWin --object-path /Scripting \
  --method org.kde.kwin.Scripting.isScriptLoaded backnav-overlay
```

Do **not** count the `Script1`, `Script2`... nodes under `/Scripting` and
treat that as the number of live scripts. It does not reliably correspond:
observed 2026-08-17 with both packages reporting `isScriptLoaded true` and
the overlay demonstrably running, while introspection listed a single
node - and the same session had listed two nodes earlier the same day.
Ask about a package by name; the node list will mislead you.

### See also

Two related traps are documented where the code lives, in
`backnav-kwin-overlay/README.md`:

- **"Reloading after an edit - `-u` alone is NOT enough"** - Qt caches
  compiled QML by URL, so `kpackagetool6 -u` can silently leave the old
  code running. This is why the iterate loop above hot-loads from a fresh
  path each time.
- **"There is no logging from this QML"** - `console.log` and
  `console.warn` from a `declarativescript` go nowhere, which is why
  debugging it means adding a temporary D-Bus method and reading the
  daemon's journal.
