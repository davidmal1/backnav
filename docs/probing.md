# Probing an application

Part of [BackNav](../README.md).

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

## Qt applications are the likely candidates

Every app on the supported list is Qt, and that is not a coincidence.
Qt's D-Bus adaptors publish properties and methods, so a Qt app tends to
be able to answer questions about itself. GTK applications expose
`org.gtk.Actions`, which is a *command* interface: it exists so something
can trigger a menu entry remotely. It was never meant to answer
questions, so what you get is a list of everything the menus can do and
nothing about what the application currently is.

That is a structural difference rather than an oversight, so a GTK app
being unsupportable is the expected outcome rather than a disappointment.

## If you want to ask

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
