# backnav-overlay: the MRU history switcher

A second, separate KWin script package alongside `backnav-kwin/` - it
exists only to draw the on-screen list you get while walking the
Back/Forward shortcut. It has no shortcuts of its own and doesn't touch
window activation logic beyond raising whatever window the daemon says
to raise.

The gesture is Alt+Tab's, reconstructed: each tap walks one entry down
the most-recently-used list and raises it immediately, and the list is
only reordered once you stop tapping. That pause is doing the job
releasing Alt does in the real thing - see "How the end of a gesture is
detected" below for why it has to be inferred rather than observed.

## Why a second package, not a QML file loaded by backnav-kwin/

Confirmed against the actual KWin 6 scripting API docs: a plain
`"javascript"`-API script (what `backnav-kwin/contents/code/main.js`
is) has no way to create an on-screen dialog or load a QML component at
runtime - the only globals it gets are `print`, `readConfig`,
`registerScreenEdge`/`unregisterScreenEdge`, `registerShortcut`,
`callDBus`, and `registerUserActionsMenu`. `"declarativescript"` mode
(what this package uses, entering from `contents/ui/main.qml`) is the
one KWin script mode that *can* draw a real on-screen `Window` - modelled
directly on KDE's own official example
(`kwin.git/examples/quick-script`). The two modes are mutually
exclusive per package (a package enters from either
`contents/code/main.js` or `contents/ui/main.qml`, not both), hence two
packages rather than one.

## How the end of a gesture is detected

Nothing in KWin's scripting API - JS or QML - exposes a shortcut's
press/hold/release state; `registerShortcut()`'s callback and QML's
`ShortcutHandler.activated()` both only fire once per press (they're
wired to the underlying `QAction::triggered()`). Alt+Tab itself gets
around this by being native C++ (KWin's TabBox), not a script.

What actually carries that information is one level down: every global
shortcut, regardless of which API registered it, is owned by
KGlobalAccel, and **KGlobalAccel's own `org.kde.kglobalaccel.Component`
D-Bus interface emits `globalShortcutPressed`, `globalShortcutRepeated`
(fired for as long as the physical key(s) stay down, at the keyboard's
repeat rate) and `globalShortcutReleased` signals per shortcut** -
confirmed live on this machine:

```
$ qdbus6 org.kde.kglobalaccel /component/kwin org.freedesktop.DBus.Introspectable.Introspect
```

already shows `globalShortcutPressed`/`Repeated`/`Released`, and
`BackNavBack`/`BackNavForward` (registered by `backnav-kwin/`'s existing
`registerShortcut()` calls) already appear as known shortcut names under
that component.

So `backnav-engine/core/overlay_controller.py` subscribes to those
signals **directly**, bypassing both KWin scripts entirely for input
detection.

That still isn't enough for an Alt+Tab gesture, though, and this is the
finding that shaped the current design. Measured on real keys
(2026-08-10, nested sandbox, trace tooling in `dev/shortcut_trace.py`):
**`globalShortcutReleased` tracks the KEY, not the combo.** Holding Meta
and tapping F8 twice produced two complete `Pressed`->`Released` cycles,
221ms and 159ms long, and releasing Meta ~2s later emitted nothing at
all. KGlobalAccel never reports a modifier's release, so "the user let go
of Alt" is not an event that exists here.

The gesture's end is therefore inferred from the user going quiet:
each release walks one step and (re)arms a `_DWELL_SECONDS` timer, and
the MRU promotion happens when that timer finally expires. `_on_repeated`
is deliberately inert - repeats arrive at the keyboard auto-repeat rate,
measured 25-28/sec here, which crosses the whole list in a fraction of a
second.

## How this QML learns what to show

The reverse direction has the same shape of problem: this QML has no
way to receive a D-Bus signal push (`KWinComponents.DBusCall` is
call-out-only), and there's no generic "run this in the script's
context" D-Bus method exposed for a running KWin script either. So
`contents/ui/main.qml` polls `com.backnav.Navigator`'s new
`GetPeekState()` method on an 80ms `Timer` and renders whatever comes
back (a JSON string - `{active, direction, entries, highlightIndex,
activateWindowId}`). When a poll shows `activateWindowId` set, this
script raises that window itself (KWin is still the only thing that
can, same as `backnav-kwin/`'s existing `activateWindow()` - this
package has its own copy since it can't reach into the other script's
JS state).

## Setup

Needs installing as its own KWin script package:

```
kpackagetool6 --type KWin/Script -i backnav-kwin-overlay
```

(`-u` instead of `-i` to upgrade an already-installed copy - same
manual-copy/reload gap as `backnav-kwin/` itself; see the spun-off dev
sync/reload follow-up task, which should ideally cover this package
too once it exists.)

`backnav-kwin/`'s Back/Forward shortcuts have no default keybinding
(never did - "KWin scripts can't safely presume a free key combo"), so
one needs assigning under System Settings > Shortcuts > BackNav before
either the plain tap-to-jump behaviour or this overlay can be triggered
at all.

## Not yet confirmed live (flagging honestly rather than assuming)

- **`_DWELL_SECONDS` is a guess, not a measurement.** 600ms was picked to
  be comfortably longer than a deliberate double-tap and shorter than a
  pause between separate gestures, but it has never been tuned against
  actual use. It is the one number in this design most likely to need
  changing, and the symptom of getting it wrong is subtle: too short and
  a two-tap walk silently becomes two one-tap gestures that just swap the
  same pair of windows.
- **`internalId` on QML `Workspace.stackingOrder` window objects.** The
  plain JS scripting API's `workspace.stackingOrder[i].internalId` is
  confirmed live (it's what `backnav-kwin/`'s `activateWindow()` already
  uses successfully); this package's QML `activateWindow()` assumes the
  QML `Workspace` type's window objects expose the same property, since
  both wrap the same underlying KWin window class - reasonable, but
  unconfirmed until tested.
