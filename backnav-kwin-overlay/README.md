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

## When the panel is allowed to appear

Not on every gesture. The common gesture is a single tap to bounce to the
previous window, and for that the panel is a distraction - the switch has
already happened by the time it renders, and it then sits on screen for
`_DWELL_SECONDS` plus the QML `dwell` linger below (~1.5s in total) to
describe a journey of one step.

So the daemon keeps reporting `active: false` until the gesture shows a
sign of being a real walk: **a second press**, or **the key being held**
(the first `globalShortcutRepeated`). Neither fires for tap-and-done.
`activateWindowId` is still reported while inactive, which is what lets a
hidden overlay still raise windows - so nothing about plain tap-to-switch
changes.

A plain elapsed-time delay from the start of the gesture was the first
design and does not work: the gesture stays open for the whole
`_DWELL_SECONDS` after the last tap, so any threshold under 800ms is met
by single taps too (showing the panel late, which is worse than showing
it promptly) and any threshold over 800ms is never met because the walk
has already committed. The dwell sandwiches it; there is no usable value.

The hold trigger deliberately has no threshold of its own on top of the
first repeat. Auto-repeat does not start until the keyboard's repeat
delay has elapsed - 600ms on this machine (`xset q`: "auto repeat delay:
600, repeat rate: 25") - so a repeat existing at all already proves a
deliberate hold. An earlier 250ms gate on top of that was unreachable
code. It also means the peek delay follows System Settings > Keyboard
rather than a BackNav setting, which is the right owner for "how long
before holding a key means something".

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

## The chooser, and why closing it needs two detectors

Holding the shortcut past the keyboard's auto-repeat delay opens the
panel as a **chooser**: it takes keyboard focus, Up/Down move the
highlight, Enter confirms, Escape returns you where you started. There
is no timeout - it stays up until you decide.

Taking focus is what makes it work and also what makes it dangerous. A
chooser that stays open after you have moved on is a window silently
eating your keystrokes, and it wedges the shortcut too, since the daemon
still thinks a gesture is in progress. Closing it reliably turned out to
need three separate mechanisms, because each has a blind spot the others
cover.

**1. Focus moving to a different window** - `OverlayController`
subscribes to KWin's focus stream and dismisses on any normal focus
event. Fast and cheap.

An earlier version compared each event against an "anchor" (the window
focused when the chooser opened) and ignored matches, meaning to tolerate
a late echo from a preceding tap's raise. That was wrong in principle -
the panel had focus, so focus arriving anywhere else is a departure
regardless of destination - and wrong in practice: clicking straight back
onto the window the chooser opened over matched the anchor, was ignored,
and wedged the shortcut until some third window happened to get focus
minutes later. Reported live as *"it fixed itself while typing this
out."*

**2. Focus returning to the window the chooser opened over** - detector
1 cannot see this at all, and the reason is structural: **the panel is
not a KWin-managed window.** KWin's idea of the active window never
changes while the chooser is up, so clicking back onto that same window
produces no `windowActivated` and the daemon hears nothing. Measured
(2026-08-12): the chooser sat open for 90 seconds while the user typed
into another window, with not one focus event logged.

The QML side covers it, via a finding worth stating on its own:

> **`onActiveChanged` never fires with `false` for this window, but the
> `active` property does go false, reliably.** The signal is what is
> missing, not the state.

So the 80ms poll **samples** `root.active` rather than watching the
signal, and calls `DismissSelection()` when it sees focus gone. Absence
of a signal is not absence of the state behind it - worth remembering
before concluding a property is unusable.

Two details this needs:

- It is gated on having **held** focus first (`hadFocus`), not merely on
  lacking it. `requestActivate()` is asynchronous, so `chooser=true,
  active=false` is legitimate for a poll or two after the chooser opens;
  acting on that would dismiss it ~80ms after it appeared, every time.
- It calls `DismissSelection`, **not** `CancelSelection`. Cancel means
  "I did not want any of these, put me back" and raises the origin
  window. Dismiss raises nothing, because focus has already gone
  somewhere the user chose and raising would drag them off it.

**3. The panel ceasing to exist** - if the QML is unloaded or crashes
mid-chooser, neither detector above ever fires and the shortcut stays
wedged forever. The daemon stamps `_last_poll` on every `GetPeekState()`
and treats twelve missed polls (`_PANEL_HEARTBEAT_SECONDS = 1.0`) as a
dead panel, recovering on the next press. This is deliberately **not** a
chooser timeout - it only fires for a panel that has stopped polling.

One thing that would break detector 1 outright is KWin reporting the
panel itself as a normal focus change, which would close the chooser the
instant it opened. It does not, for the same reason detector 2 is needed
at all: an unmanaged window never enters that stream. Confirmed by
logging every focus event across a full round of chooser testing - every
one named a real application, none named the overlay.

## Setup

Needs installing as its own KWin script package:

```
kpackagetool6 --type KWin/Script -i backnav-kwin-overlay
```

(`-u` instead of `-i` to upgrade an already-installed copy - same
manual-copy/reload gap as `backnav-kwin/` itself; see the spun-off dev
sync/reload follow-up task, which should ideally cover this package
too once it exists.)

### Reloading after an edit - `-u` alone is NOT enough

Installing the new file does not put the new file on screen, and this
fails **silently**: the panel keeps running the previous version while
every command reports success.

```
kpackagetool6 --type KWin/Script -u backnav-kwin-overlay   # updates disk
qdbus6 org.kde.KWin /Scripting ...unloadScript backnav-overlay
qdbus6 org.kde.KWin /KWin reconfigure                      # reloads...
```

That sequence looks convincing - `unloadScript` really does unload
(`isScriptLoaded` goes `false`, and the 80ms `GetPeekState` polling
stops dead), `reconfigure` really does reload, and `isScriptLoaded`
goes back to `true`. But Qt's QML engine caches compiled components
**by URL**, and unloading a KWin script does not clear that cache. The
reload therefore re-instantiates the OLD compiled QML from the same
path.

Measured (2026-08-12): with `interval: 400` installed and verified on
disk, the live poll rate stayed at exactly 12.5/sec - the old 80ms
value. Several rounds of overlay "fixes" before this was found had
never once been on screen.

The reliable way to reload in a live session is to load the QML from a
**fresh path** each time, so the cache misses:

```
qdbus6 org.kde.KWin /Scripting ...unloadScript bn-probe
cp contents/ui/main.qml /tmp/bn-probe/probe-$(date +%s).qml
qdbus6 org.kde.KWin /Scripting ...loadDeclarativeScript \
    /tmp/bn-probe/probe-<ts>.qml bn-probe
qdbus6 org.kde.KWin /Scripting ...start
qdbus6 org.kde.KWin /Scripting ...unloadScript backnav-overlay
```

The last line matters: `start()` starts every enabled script, which
brings the installed `backnav-overlay` back up alongside the temporary
copy. Two instances means two overlays and two pollers - visible as a
doubled `GetPeekState` rate (~25/sec rather than ~12.5/sec), which is
the quickest way to check for it:

```
timeout 3 dbus-monitor --session "interface='com.backnav.Navigator'" \
    > /tmp/m.txt; grep -c GetPeekState /tmp/m.txt   # ~37 = one instance
```

Still install the package with `-u` as well - that is what makes the
change survive, since KWin re-reads it from scratch at next login when
the component cache is empty.

### There is no logging from this QML

`console.log` **and** `console.warn` from a declarativescript reach
neither the user nor the system journal - verified while the window was
provably alive and polling 12x/sec. Uncaught exceptions in QML handlers
are therefore invisible too, which is what makes the cache problem
above so hard to spot: broken code and stale code look identical.

The workaround, when something here needs debugging, is to report over
D-Bus instead: add a temporary `Probe(s) -> s` method to
`com.backnav.Navigator` (see `core/navigator_service.py`) that just
`print`s, call it through a `KWinComponents.DBusCall`, and read the
daemon's journal:

```
journalctl --user -u backnav.service -f | grep PROBE
```

Three things that cost time the first time round:

- **Pass the argument as a binding**, `arguments: [root.probeNote]`, not
  by assigning `probeCall.arguments = [...]` imperatively. The
  imperative form silently does nothing, and with QML logging going
  nowhere there is no way to see the throw.
- **Give the method a return value.** A void-returning D-Bus method
  leaves KWin's `DBusCall` with nothing to hand `onFinished`, and the
  call never leaves the overlay. Match `GetPeekState`'s `-> "s"` shape.
- **Messages sharing one `DBusCall` object drop** when they fire in
  quick succession, since each overwrites the previous one's argument.
  Counts from it are a lower bound, not a tally.

The probes are removed once they have answered their question; what
they established is written up in place at the code they explain.

`backnav-kwin/`'s Back/Forward shortcuts have no default keybinding
(never did - "KWin scripts can't safely presume a free key combo"), so
one needs assigning under System Settings > Shortcuts > BackNav before
either the plain tap-to-jump behaviour or this overlay can be triggered
at all.

## Not yet confirmed live (flagging honestly rather than assuming)

- **`_DWELL_SECONDS` has been judged by feel, not measured.** 600ms was
  picked to sit comfortably between a deliberate double-tap and a pause
  between separate gestures, and hand-testing in the sandbox (2026-08-11)
  found it acceptable - single bounces settle without feeling sluggish,
  and a two-tap walk stays one gesture. It was then raised to **800ms**
  to give a two-tap walk more room, which is still a guess by feel rather
  than a measurement. That is one person on one keyboard, so it remains
  the number most likely to need revisiting. Note it compounds with the
  QML `dwell` timer below: the panel stays up for `_DWELL_SECONDS` after
  the last tap and *then* lingers for that timer's interval on top, so
  raising this also lengthens how long the overlay is on screen in total
  (for the gestures that show it at all - a single tap no longer does,
  see "When the panel is allowed to appear" above, which is what removed
  the worst of this).
  The symptom of getting it wrong is subtle rather than
  obvious: too short and a two-tap walk silently degrades into two
  one-tap gestures that just swap the same pair of windows, which reads
  as "it won't go back any further" rather than as a timing problem.
- **`internalId` on QML `Workspace.stackingOrder` window objects.** The
  plain JS scripting API's `workspace.stackingOrder[i].internalId` is
  confirmed live (it's what `backnav-kwin/`'s `activateWindow()` already
  uses successfully); this package's QML `activateWindow()` assumes the
  QML `Workspace` type's window objects expose the same property, since
  both wrap the same underlying KWin window class - reasonable, but
  unconfirmed until tested.
