# BackNav

**An Alt+Tab alternative that understands tabs.**

Most-recently-used switching across your windows *and* the tabs within
them: browser tabs, terminal sessions, open documents.

For KDE Plasma on Wayland.

---

## The problem

Alt+Tab has switched *windows* since Windows 3.x, around 1990. It was
exactly the right design then: one window really was one thing you were
doing.

Tabs did not exist yet. Browsers would not popularise them for another
decade, and it would be years after that before working in a dozen tabs
at once became normal. Alt+Tab is a solution from before the problem, and
it has never been updated to notice.

The problem is that a browser with thirty tabs open is one window. A
Konsole with six sessions is one window.

Consider working on Tab-1, then Tab-2, then wanting to go back to Tab-1.
When you Alt+Tab "back to what I was last doing", you land on an entirely
different application, because Alt+Tab has no concept of tabs.

Ctrl+Tab is not the answer either. It only ever moves within one
application, so it cannot take you back to something in a different one.
It is not universal - each application picks its own key, and plenty
offer nothing. And what it does varies between applications: some cycle
by recency, some step through in order, some pop up a chooser. Even where
the key works, what happens next is not something you can rely on
knowing.

Between them, then, you are asked to work out where you are going before
you can choose how to get there: inside this application or outside it,
one key or the other, and the wrong guess takes you somewhere unrelated.
That is a question you should never have to answer, because you already
know the answer in the only form that matters - you remember the thing,
not which window contains it. Consistency is king.

BackNav keeps a most-recently-used trail across windows *and* the tabs
inside them, and gives you one shortcut to walk back along it, whichever
side of an application boundary the last thing happens to be.

## How it feels

There are two gestures, and they don't overlap:

| gesture | what happens |
| --- | --- |
| **Tap** the shortcut | Step back one place. Repeat to keep going. You just watch windows and tabs come back into focus. |
| **Hold** the shortcut | A switcher panel appears. Nothing moves until you choose. |

Tap to act, hold to look.

Holding shows a list of where you have been, most recent first, with app
icons and titles. Keep tapping to move down it, or let go and use the
arrow keys. Enter or a mouse click confirms; Escape puts you back where you
started.

If that sounds like Alt+Tab, it is meant to. The ordering is
most-recently-used, not a browser's back/forward stack: going somewhere
promotes it to the front rather than appending a second copy of it, and
there is no branch to lose. BackNav did work like browser history early
on, and it was replaced. A linear stack accumulates duplicates of the
places you keep returning to, which is exactly the wrong shape for
switching between a handful of things all day.

**History keeps the 20 most recent places, and that is deliberate.**
BackNav's value is at the shallow end - the last few things you were
doing, where you know what you want and reaching for it beats looking for
it. Something you last touched days and thirty entries ago is quicker to
click on, and no amount of tapping or scrolling past an eight-row panel
changes that. Twenty is already well past the point where the mouse wins.

Holding the shortcut looks like this:

![The BackNav switcher panel showing eight entries - two Kate documents,
three Konsole tabs, two Thunderbird tabs and a Brave tab - each with its
application icon, ordered by how recently it was
used](docs/overlay.png)

Eight rows, and not one of them is a window. Two documents open in Kate,
three Konsole tabs, two Thunderbird tabs and a browser tab, ordered by
when you last touched them rather than grouped by application. Alt+Tab
looking at the same desktop shows four icons.

## What it can navigate

| | what BackNav restores |
| --- | --- |
| **Chrome, Brave, Vivaldi, Edge, Chromium** | The individual tab |
| **Firefox** | The individual tab |
| **Thunderbird** | The individual mail or message tab |
| **Konsole** | The individual tab |
| **Kate** | The individual document (tab) |
| **qpdfview** | The individual document (tab) |
| **kitty** | The individual tab |
| **Any window** | Raised and focused, like Alt+Tab |

Everything else still works at the window level. Nothing needs to be on
this list for BackNav to be useful. The list is about how *deep* it can
go.

**qpdfview is on that list and Okular isn't, which is worth explaining.**
Okular is the PDF viewer Kubuntu ships and the one most people already
have. It cannot be supported, for the reason under "Why some apps can't be
supported" below.
qpdfview was adopted instead, not because it is better, but because it
is the tabbed PDF viewer that *can* be driven correctly. If you want
document-level navigation in a PDF viewer, you will have to install it
deliberately; it will not already be there.

## Can it replace Alt+Tab entirely?

Yes. Binding BackNav to Alt+Tab itself is a reasonable thing to do.

Two things to know. It learns windows as you focus them, so a window you
have never once visited is not in the list. And if the daemon is not
running BackNav does nothing, because the KWin script holds no logic of
its own.

The shortcuts live under **System Settings -> Keyboard -> Shortcuts**,
where BackNav registers them under the **KWin** component. Search for
`BackNav` and you will find *BackNav: Navigate Back* and *BackNav:
Navigate Forward*.

Pick the combination you want for **Navigate Back** and press it into the
field. Something uncontested like **Meta+Tab** just works. **Alt+Tab** is
already KWin's own *Walk Through Windows*, so KDE will warn about the
conflict and offer to reassign - accepting takes Alt+Tab away from the
built-in switcher and gives it to BackNav, which is the point.

If you later want the old behaviour back, *Walk Through Windows* has a
"reset to default" button, so nothing here is one-way.

### Navigate Forward is optional

Bind it only if it suits how you work. It does exactly one thing: undo an
overshoot while a walk is still open. Outside a walk it does nothing at
all, so it is not a browser's forward button despite the name - it is
`Alt+Shift+Tab`.

That is worth having if you tap quickly and sometimes go one too far.
Without it the recovery is clumsy: let the gesture settle, and the entry
you overshot onto is now the most recent, so getting where you meant
takes two taps in the other direction.

If you do bind it, make it the **shifted variant of Navigate Back** -
`Meta+Shift+Tab` alongside `Meta+Tab`, or `Alt+Shift+Tab` alongside
`Alt+Tab`. The entire value is correcting mid-gesture without moving your
hand, which a key somewhere else cannot offer.

And if you never overshoot, leave it unbound. Nothing breaks: the action
is registered either way, and an unbound one is simply inert.

## Why the browsers need an extension

A browser tab is not a window. It has no entry in the compositor, no
title bar, no place in the window stack. From the outside, a browser with
thirty tabs open looks exactly like a browser with one.

So there is nothing for KWin to see, and nothing for it to switch to.
The only thing that knows which tab is active is the browser itself.

The extensions are a small bridge: they tell the daemon which tab is
frontmost, and switch tabs when asked. They connect to a WebSocket on
`127.0.0.1` and that is the whole of it. **They send tab titles and
nothing else** - no URLs, no page content, no history.

They ask for no host permissions, which is the part worth caring about.
Host permissions are what let an extension read page content, inject
scripts or watch network requests, and an extension without them cannot
do those things whatever its code says.

Tab access is not nothing, though, and it would be misleading to present
it as harmless. Chrome describes it to users in terms of browsing
history, because tab titles and URLs reveal where you have been. BackNav
reads titles and does not send URLs - but the permission would allow it,
so you are trusting the code on that point rather than the browser's
sandbox. What the sandbox does guarantee is that it cannot see inside any
page.

Konsole, Kate and qpdfview need no extension, because KDE applications
already expose enough over D-Bus to ask them directly. kitty needs none
either, though it is not a KDE application and speaks no D-Bus at all -
it has its own remote-control protocol, which is richer than most of the
D-Bus interfaces here.

## Why some apps can't be supported

Adding an app takes three things, and most apps have one or two:

1. **A signal that a tab changed.** Usually the window title changing is
   enough.
2. **A way to ask which tab is open now**, that returns something
   restorable.
3. **A way to switch to a specific tab, without creating it.**

The third is where apps fall down, and **Okular** is the example worth
naming. Its tab-opening call adds a new tab even when the file is already
open in one, so "go back to that document" would silently duplicate it
rather than switch to it. A navigation that quietly changes your
workspace is worse than no navigation, so it is left at the window level.

That is not a fault peculiar to Okular. Kate had exactly the same
problem: `openUrl` reopened documents that had been closed. It is only
supported because Kate happens to *also* expose a non-creating
`activate(token)` call. qpdfview needed a similar hunt. Of its three
open methods, two would have destroyed or duplicated a tab, and only the
third searches existing tabs first.

So the honest rule is: an app is supportable when it offers a way to say
"switch to this, if it still exists" and do nothing otherwise. Plenty of
applications simply do not.

## "Can you support my favourite app?"

Maybe, and you can find out in about five minutes without knowing any of
this codebase. The answer lives in the application, not in BackNav.

The procedure is at the end of this page, under
[Probing an application](#probing-an-application), along with what to
send if you want to open an issue.

## How it fits together

Three pieces, because the information lives in three places:

- **`backnav-kwin/`**, a KWin script. The only thing that can see window
  focus changes, and the only thing that can raise a window on Wayland.
- **`backnav-engine/`**, a Python daemon. Keeps the history, decides
  where "back" goes, talks to applications over D-Bus.
- **`browser/`**, WebExtensions for the browsers and Thunderbird, since
  tabs are invisible from outside.
- **`backnav-kwin-overlay/`**, the switcher panel, as a QML KWin script.

## Installing

Requires KDE Plasma 6 on Wayland, and Python 3.

Start with the tools and the daemon's two dependencies:

```bash
sudo apt install git python3-websockets python3-dbus-next
```

Installing them from apt rather than pip is not a preference. Ubuntu
24.04 and later ship Python as an externally managed environment, so
`pip install` into the system refuses outright and tells you to use the
package manager - which has both, so there is nothing to work around.

```bash
git clone https://github.com/davidmal1/backnav.git
cd backnav
kpackagetool6 --type KWin/Script -i backnav-kwin
kpackagetool6 --type KWin/Script -i backnav-kwin-overlay
```

The `cd` matters, and skipping it fails badly: `kpackagetool6` takes the
two names as relative paths, so from anywhere else you get

```
Error: Installation of  failed: No such file:
```

which names neither what it wanted nor where it looked - and it exits 0
while doing it. If you see that, you are in the wrong directory.

Enable both scripts in **System Settings → Window Management → KWin
Scripts**.

Bind *BackNav: Navigate Back* under **Shortcuts → KWin**. Assign your
desired shortcut key. That one shortcut is the whole interface.

There is a second action, *BackNav: Navigate Forward*, which is entirely
optional - see [Navigate Forward is
optional](#navigate-forward-is-optional) above. Leaving it unbound costs
nothing.

Then set the daemon up to run with your session. Its dependencies came
from the `apt` line above, so there is nothing further to install.

The directory will not exist yet on a machine that has never had a user
service, which is most of them:

```bash
mkdir -p ~/.config/systemd/user
```

Put this in `~/.config/systemd/user/backnav.service`, replacing both
copies of `/home/you/backnav` with where you cloned it. It has to be
written out in full - systemd does not expand `~`, so the `~/backnav`
used elsewhere on this page will not work here:

```ini
[Unit]
Description=BackNav navigation daemon
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=/usr/bin/python3 /home/you/backnav/backnav-engine/backnav.py
WorkingDirectory=/home/you/backnav/backnav-engine
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
```

Save the file, then enter these in a terminal to load and start it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now backnav
```

To watch what it is seeing - this one follows the log and keeps the
terminal until you press Ctrl+C:

```bash
journalctl --user -u backnav -f
```

`daemon-reload` is there because the directory is new: systemd scans for
unit files when it starts, and one appearing in a path that did not exist
then is not noticed on its own. If the unit reports as **masked**, the
file is empty - systemd treats a zero-byte unit the same as a deliberately
masked one, and says so in wording that suggests neither.

`/usr/bin/python3` is correct only if the dependencies came from apt as
above. If you used a virtualenv instead, `ExecStart` has to name that
interpreter - `/path/to/venv/bin/python3` - because systemd runs the unit
without your shell, so an activated venv is not inherited. The failure is
a clean `ModuleNotFoundError` in the journal.

You can also run it directly, which is worth knowing for debugging
because it prints to the terminal instead of the journal - but it holds
that terminal for as long as it runs, and it will not start while the
service has the ports:

```bash
python3 backnav-engine/backnav.py
```

### Installing the browser extensions

For tab-level navigation in a browser, install the matching extension
from `browser/`. Without one, that browser still works at the window
level - you just get one entry for the whole browser rather than one per
tab.

The two browser builds install differently, and only one is ready to use
as it sits in the repository. Thunderbird uses the same mechanism and
needs a little more, so it has its own section below.

**Chrome, Brave and Vivaldi** load the directory directly. In a browser
tab, go to `chrome://extensions`, turn on **Developer Mode**, choose
**Load unpacked** and select `~/backnav/browser/chromium`. Nothing to
build. The
extension id is pinned by the `key` field in its manifest, so it stays
the same wherever you load it from - which is what keeps BackNav's tab
bindings intact if you ever move the folder.

**Firefox** installs from a signed file, which is on the releases page
rather than in the repository:
[**backnav-firefox-0.2.xpi**](https://github.com/davidmal1/backnav/releases/latest).
Download it, then **Add-ons and Themes** -> the gear icon -> **Install
Add-on From File**.

It is signed by Mozilla, so it installs permanently and updates itself
from the releases page - there is nothing to reload by hand and no store
listing involved.

Do not build this one yourself. `build-xpi.sh firefox` works, but release
Firefox compiles signature enforcement in and ignores the preference that
would turn it off, so what it produces is useful for validating a change
and cannot be installed. That is why this build alone is distributed as a
file: [`browser/README.md`](browser/README.md) covers the signing route,
and why Firefox needs it when Thunderbird does not.

Each build directory has its own readme with the detail.
[`browser/README.md`](browser/README.md) explains which build covers
which browser, and why the two Gecko builds differ so sharply given they
are nearly the same code.

### Only if you use kitty

kitty ships with remote control off, and without it BackNav can see the
window but not the tabs inside it. One line in `~/.config/kitty/kitty.conf`,
then restart kitty:

```
allow_remote_control yes
```

Be aware of what that grants: anything able to reach kitty's socket can
run commands in your terminal and read its text, which is more than
BackNav needs. kitty offers narrower modes - `socket-only` and a
password-protected form - and they are worth preferring if you are
comfortable configuring them.

### Only if you use qpdfview

qpdfview needs **"Restore tabs"** enabled, under *Preferences ->
Behavior*. It is off by default.

Without it qpdfview never writes the tab database BackNav reads, so the
window is navigable but the individual documents are not. Nothing warns
you - it simply behaves as though qpdfview had no tabs.

### Only if you use Thunderbird

Not a browser, but it has tabs, and BackNav treats it exactly like one -
an extension reports which tab is active. It needs two things the
browsers do not.

**First, the add-on.** It installs from an `.xpi`, which is a build
artifact and deliberately not committed, so build it:

```bash
cd ~/backnav/browser

./build-xpi.sh thunderbird
```

Then in Thunderbird: **Add-ons and Themes** -> the gear icon ->
**Install Add-on From File**, and pick the `.xpi` the script printed.
Thunderbird accepts unsigned add-ons, so no store is involved, and it
survives restarts.

**Second, a certificate.** Thunderbird's HTTPS-Only Mode rewrites `ws://`
to `wss://` with no fallback, so its extension connects to a second,
TLS-only port. That listener needs a self-signed certificate, and without
one the daemon simply logs a line and carries on with the other port.
Everything except the Thunderbird extension is unaffected.

Run this from the repository root, the `backnav` directory you cloned
into - the daemon looks for the certificate relative to its own location,
so it has to go there rather than anywhere convenient:

```bash
cd ~/backnav

mkdir -p backnav-engine/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout backnav-engine/certs/key.pem \
    -out backnav-engine/certs/cert.pem \
    -subj "/CN=127.0.0.1" -addext "subjectAltName=IP:127.0.0.1"
chmod 600 backnav-engine/certs/key.pem
```

**Third, restart the daemon.** It reads the certificate only at startup,
so one generated while it was running changes nothing until it restarts -
and the next step then fails against a port that was never opened.

```bash
systemctl --user restart backnav
journalctl --user -u backnav | grep 8766 | tail -1
```

That last line tells you whether the certificate was found - it reads
either `:8766 (wss)` or `:8766 disabled, no certificate`. If you are
running the daemon by hand instead, the same line goes to its terminal.

**Fourth, trust it.** Self-signed certificates are refused by default and
Thunderbird will not say so - the extension simply never connects. Once
per profile:

**Settings -> Privacy & Security -> Certificates -> Manage Certificates
-> Servers** tab -> **Add Exception**

Location `127.0.0.1:8766` -> **Get Certificate** -> **Confirm Security
Exception**

Redo this if the certificate is ever regenerated.
[`browser/thunderbird/readme.md`](browser/thunderbird/readme.md) has the
background on why Thunderbird needs TLS when the browsers do not.

## Configuring

Optional. Copy [`backnavrc.example`](backnavrc.example) from the
repository into place and edit it:

```bash
cp ~/backnav/backnavrc.example ~/.config/backnavrc
```

Changes take effect on the next gesture, with nothing to restart - the
file is re-read when it changes rather than watched or reloaded.

Two settings, both matters of feel rather than correctness:

- **`DwellMs`** - how long a pause ends a gesture. Too short and a
  deliberate multi-tap walk gets split into separate ones; too long and
  a quick bounce between two windows feels like it lags before settling.
- **`HoldMs`** - how long you must hold before the panel appears. Lower
  it if summoning it feels sluggish; raise it if an ordinary tap
  sometimes flashes the panel at you.

## Status

Working, and in daily use by its author, which is where most of its bug
reports come from. Non-supported applications will behave like traditional
Alt+Tab.

[`TODO.md`](TODO.md) is the honest list of what is outstanding, what is
known-broken, and what has been deliberately left alone.

## Probing an application

How to tell whether an application can be supported, without knowing
anything about this codebase. Every app on the supported list was worked
out this way, and every step below exists because some app defeated the
previous version of it.

**1. Does it expose D-Bus at all?** With the app running:

```bash
qdbus6 | grep -i yourapp
```

Nothing back means almost certainly not. Most KDE and Qt applications
appear, and so do many GTK ones - appearing here is necessary but says
nothing about whether the app can answer a useful question, which is what
steps 2 and 3 are for.

If you want to be certain the grep did not just miss an oddly named
service, ask which bus names the process actually owns:

```bash
gdbus call --session --dest org.freedesktop.DBus \
    --object-path /org/freedesktop/DBus \
    --method org.freedesktop.DBus.GetConnectionUnixProcessID NAME
```

...for each name from `qdbus6`, and compare against the app's pid. An app
owning none is conclusive.

**How the app was packaged can decide this on its own.** Snap and Flatpak
run under confinement, and owning an arbitrary session-bus name is the
sort of thing confinement blocks - so a packaged build can be silent on
the bus even where the same application, installed natively, would not
be. WPS Office was the case that prompted this note: the snap owns no bus
name at all, and no amount of probing gets past that.

It cuts the other way too. Akonadi, which KMail relies on, refuses D-Bus
introspection from unconfined callers under an AppArmor policy of its
own, so the route there was to read its database instead. If an app
plainly ought to expose something and does not, packaging or policy is
worth suspecting before the application itself.

**D-Bus is not the only way an application can be driven, so silence here
is not the end of the enquiry.** Some expose a remote-control channel of
their own instead, and it can be richer than anything on the bus.

kitty is the example. It owns no bus name at all, so step 1 dismisses it
outright - and yet `kitty @ ls` returns every tab as structured JSON with
`id`, `title` and which one is active, and `kitty @ focus-tab --match
id:N` switches to one without creating anything. That is a better answer
to steps 2 and 3 than most D-Bus interfaces manage, because it needs no
caption parsing and no heuristic at all.

So if an application is silent on the bus but you know it has a CLI or a
scripting interface, check that before giving up. `--help` is usually
enough:

```bash
kitty @ --help          # lists ls, focus-tab, focus-window, ...
```

Two things to weigh if you find one. It may need switching on - kitty
defaults to `allow_remote_control no` - which is a one-time setup step of
the same kind qpdfview already needs. And it may grant far more than
BackNav wants: kitty's remote control lets anything reaching the socket
run commands in the terminal and read its text, so the narrowest mode
that works is the right one to ask for.

**2. What does it offer?** Using the service name from step 1:

```bash
qdbus6 org.kde.yourapp-1234              # objects
qdbus6 org.kde.yourapp-1234 /MainWindow  # methods on one of them
```

You are looking for two things in that list:

- something that reports **which tab or document is active now**, in a
  form you could return to later: a path, an id, a session number;
- something that **switches to one**, whose name suggests activating
  rather than opening. `activate`, `setCurrentSession`, `jumpTo...` are
  promising. `open`, `openUrl`, `openInNewTab` are the warning signs,
  because they tend to create rather than switch.

**3. Check what the promising ones actually take.** A name is not
enough, and this is where most candidates fail. If the app is GTK you
will see `org.gtk.Actions` rather than methods of its own, so ask that
what an action looks like:

```bash
qdbus6 --literal net.giuspen.cherrytree \
    /net/giuspen/cherrytree/window/1 \
    org.gtk.Actions.Describe select_node
```

That returns a triple of *(enabled, parameter type, state)*. For
CherryTree, a note-taking app whose action list includes the very
promising `select_node`, `go_node_next` and `go_node_prev`:

```
[Argument: (bgav) true, [Signature: ], [Argument: av {}]]
                         ^^^^^^^^^^^^   ^^^^^^^^^^^^^^^
                         no parameter   no state
```

**Empty parameter type** means `select_node` takes no arguments, so it
cannot mean "select node X" - it acts on wherever the cursor already is.
`go_node_next` and `go_node_prev` are relative moves with no target.
**Empty state** means nothing reports which node is current.

So CherryTree fails both of the things step 2 was looking for, despite
having 217 actions and three that sound exactly right.

**4. Does the window title change when you switch tabs?** Watch it while
you click between tabs. If the title never changes, there is no signal
that anything happened, and detection has nowhere to start.

Four yeses means it is very likely supportable. A no on the second or
third is usually fatal, and that is the common case. See Okular above.

### Qt applications are the likely candidates

Every app on the supported list is Qt, and that is not a coincidence.
Qt's D-Bus adaptors publish properties and methods, so a Qt app tends to
be able to answer questions about itself. GTK applications expose
`org.gtk.Actions`, which is a *command* interface: it exists so something
can trigger a menu entry remotely. It was never meant to answer
questions, so what you get is a list of everything the menus can do and
nothing about what the application currently is.

That is a structural difference rather than an oversight, so a GTK app
being unsupportable is the expected outcome rather than a disappointment.

### If you want to ask

[Open an issue](https://github.com/davidmal1/backnav/issues) with the
output of steps 1 and 2, and say whether the title changes. That is the
whole of what anyone would need to judge it, and it saves a round trip
where the answer is "I cannot tell without a running copy". That is
genuine: every app on the supported list was worked out by probing a live
instance rather than by reading documentation.

Be aware that a *maybe* can still turn into a no. Kate's support took
three attempts: the obvious call reopened closed documents, the
documented way to enumerate them does not exist, and it only works
because a non-creating `activate(token)` happens to be there. qpdfview
needed its own database read plus a caption heuristic. So the honest
expectation is that support is possible when the application cooperates,
and that many do not.
