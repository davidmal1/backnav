# backnav-overlay: the hold+repeat-taps history preview

A second, separate KWin script package alongside `backnav-kwin/` - it
exists only to draw the on-screen preview list you get by holding down
the Back/Forward shortcut (Alt+Tab style: hold, tap repeatedly to page
further back/forward, release to jump). It has no shortcuts of its own
and doesn't touch window activation logic beyond raising whatever
window the daemon says to raise on release.

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

## How hold/repeat/release actually gets detected

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
detection. See its docstring for the full state machine (press = peek 1
step, each repeat = peek 1 step further, release = commit whatever's
highlighted).

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

- **Real physical hold+repeat+release behaviour.** The
  `globalShortcutPressed`/`Repeated`/`Released` signals were confirmed to
  exist and fire correctly for a scripted single "press" (via
  `qdbus6 ... invokeShortcut`), but `invokeShortcut()` only ever emits
  `Pressed` - there's no clean way to synthesize a real held key from
  this environment (Wayland session, no `ydotool`/`wtype` installed) to
  see `Repeated`/`Released` fire for real. Needs an actual hands-on test
  once a keybinding is assigned.
- **`internalId` on QML `Workspace.stackingOrder` window objects.** The
  plain JS scripting API's `workspace.stackingOrder[i].internalId` is
  confirmed live (it's what `backnav-kwin/`'s `activateWindow()` already
  uses successfully); this package's QML `activateWindow()` assumes the
  QML `Workspace` type's window objects expose the same property, since
  both wrap the same underlying KWin window class - reasonable, but
  unconfirmed until tested.
