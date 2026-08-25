# BackNav

**An Alt+Tab alternative that understands tabs.**

Most-recently-used switching across your windows *and* the tabs within
them: browser tabs, terminal sessions, open documents.

For KDE Plasma on Wayland.

---

## The problem

Alt+Tab has switched *windows* since Windows 3.x, around 1990. Tabs did
not exist yet. Browsers would not popularise them for another decade, and
it would be years after that before working in a dozen tabs at once
became normal. The problem is that a browser with thirty tabs open is one
window. A Konsole with six sessions is one window.

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
Consistency is king.

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
doing.

This video shows BackNav in action.

https://github.com/user-attachments/assets/7021c8de-8847-4253-8a11-5490cbdf76d3

## What it can navigate

| | what BackNav restores |
| --- | --- |
| **Chrome, Brave, Vivaldi, Edge, Opera, Chromium** | The individual tab |
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

**Other Chromium-based browsers are one line away.** The extension works
in any of them, but BackNav identifies a window by the exact name KWin
reports, so an unlisted browser gets window-level navigation until that
name is added - see [Adding a
browser](docs/probing.md#adding-a-browser).

**qpdfview is on that list and Okular isn't, which is worth explaining.**
Okular is the PDF viewer Kubuntu ships and the one most people already
have; it cannot be supported, for the reason in [Why some apps can't be
supported](docs/probing.md#why-some-apps-cant-be-supported). qpdfview was
adopted instead, not because it is better, but because it is the tabbed
PDF viewer that *can* be driven correctly. If you want document-level
navigation in a PDF viewer, you will have to install it deliberately; it
will not already be there.

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
overshoot while a walk is still open.

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

## "Can you support my favourite app?"

Maybe, and you can find out in about five minutes without knowing any of
this codebase. The answer lives in the application, not in BackNav.

The procedure is in [Probing an
application](docs/probing.md), along with what to send if you want to
open an issue.

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
./install.sh
```

That installs the dependencies, both KWin scripts, and the daemon as a
user service, and is safe to re-run. It stops short of three things it
should not decide for you - which shortcut to bind, which browser
extensions you want, and the per-application settings - and prints them
at the end.

The steps it runs are written out in [Installing by
hand](docs/installing-by-hand.md), for anyone who would rather do them
themselves or wants to know what it touched.

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

### Known quirks

**A browser takes up to a minute to come back after the daemon
restarts.** Extensions are not told the socket died; each reconnects on
its own timer, and a minute is the worst case. Until then that browser
reports nothing and shows a single window-level row.

[`TODO.md`](TODO.md) is the honest list of what is outstanding, what is
known-broken, and what has been deliberately left alone.

## License

GPL-3.0 - see [LICENSE](LICENSE). The same licence KWin itself uses,
which is the sensible default for something that runs inside it.
