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

BackNav keeps a most-recently-used trail across windows *and* the tabs
inside them, and gives you a shortcut to walk back along it.

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

## What it can navigate

| | what BackNav restores |
| --- | --- |
| **Chrome, Brave, Vivaldi, Edge, Chromium** | The individual tab |
| **Firefox** | The individual tab |
| **Thunderbird** | The individual mail or message tab |
| **Konsole** | The individual session (tab) |
| **Kate** | The individual document (tab) |
| **qpdfview** | The individual document (tab) |
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

## Why the browsers need an extension

A browser tab is not a window. It has no entry in the compositor, no
title bar, no place in the window stack. From the outside, a browser with
thirty tabs open looks exactly like a browser with one.

So there is nothing for KWin to see, and nothing for it to switch to.
The only thing that knows which tab is active is the browser itself.

The extensions are a small bridge: they tell the daemon which tab is
frontmost, and switch tabs when asked. They connect to a WebSocket on
`127.0.0.1` and that is the whole of it. **They send tab titles and
nothing else**. No URLs, no page content, no history. Every build
requests only the `tabs`, `storage` and `alarms` permissions, with no
host permissions at all.

Konsole, Kate and qpdfview need no extension, because KDE applications
already expose enough over D-Bus to ask them directly.

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

**1. Does it expose D-Bus at all?** With the app running:

```bash
qdbus6 | grep -i yourapp
```

Nothing back means almost certainly not. Most KDE and Qt applications
appear here; GTK ones usually do not.

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

**3. Does the window title change when you switch tabs?** Watch it while
you click between tabs. If the title never changes, there is no signal
that anything happened, and detection has nowhere to start.

Three yeses means it is very likely supportable. A no on the second is
usually fatal, and that is the common case. See Okular above.

### If you want to ask

Open an issue with the output of steps 1 and 2, and say whether the title
changes. That is the whole of what anyone would need to judge it, and it
saves a round trip where the answer is "I cannot tell without a running
copy". That is genuine: every app on the supported list was worked out by
probing a live instance rather than by reading documentation.

Be aware that a *maybe* can still turn into a no. Kate's support took
three attempts: the obvious call reopened closed documents, the
documented way to enumerate them does not exist, and it only works
because a non-creating `activate(token)` happens to be there. qpdfview
needed its own database read plus a caption heuristic. So the honest
expectation is that support is possible when the application cooperates,
and that many do not.

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

```bash
git clone https://github.com/davidmal1/backnav.git
cd backnav

kpackagetool6 --type KWin/Script -i backnav-kwin
kpackagetool6 --type KWin/Script -i backnav-kwin-overlay
```

Enable both in **System Settings → Window Management → KWin Scripts**,
then bind the two shortcuts under **Shortcuts → KWin**: *BackNav:
Navigate Back* and *BackNav: Navigate Forward*.

Then run the daemon. It needs `dbus-next` and `websockets`:

```bash
pip install dbus-next websockets
```

It also needs a self-signed certificate, because one of its two
WebSocket listeners is TLS. Thunderbird's HTTPS-Only Mode rewrites
`ws://` to `wss://` with no fallback, so that connection has to be
secure from the start. The daemon will not start without it, even if you
never use Thunderbird:

```bash
mkdir -p backnav-engine/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout backnav-engine/certs/key.pem \
    -out backnav-engine/certs/cert.pem \
    -subj "/CN=127.0.0.1" -addext "subjectAltName=IP:127.0.0.1"
chmod 600 backnav-engine/certs/key.pem
```

It is never sent anywhere and secures a socket on your own machine only.
Then:

```bash
python3 backnav-engine/backnav.py
```

To have it start with your session, put this in
`~/.config/systemd/user/backnav.service`, adjusting the two paths:

```ini
[Unit]
Description=BackNav navigation daemon
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=/usr/bin/python3 /path/to/backnav/backnav-engine/backnav.py
WorkingDirectory=/path/to/backnav/backnav-engine
Restart=on-failure
RestartSec=2

[Install]
WantedBy=graphical-session.target
```

```bash
systemctl --user enable --now backnav
journalctl --user -u backnav -f     # what it is seeing
```

For tab-level navigation in a browser, install the matching extension
from `browser/`. Each directory has its own readme;
[`browser/README.md`](browser/README.md) explains which build covers
which browser.

## Configuring

Optional. Copy [`backnavrc.example`](backnavrc.example) to
`~/.config/backnavrc` and edit. Changes take effect on the next gesture,
with nothing to restart.

Two settings, both matters of feel: `DwellMs`, how long a pause ends a
gesture, and `HoldMs`, how long a hold takes to summon the panel.

## Status

Working, and in daily use by its author, which is where most of its bug
reports come from. Non-supported applications will behave like traditional
Alt+Tab.

[`TODO.md`](TODO.md) is the honest list of what is outstanding, what is
known-broken, and what has been deliberately left alone.
