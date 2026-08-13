# Outstanding

Working list for the `mru-navigation` branch. Not merged to `main` yet -
deliberately, until the whole thing is working.

## Overlay tidy-up

Done (2026-08-13), tested live: app icons in place of the resourceClass
column, mouse hover and click, and everything scaled up behind a single
`ui` multiplier in `main.qml`.

Dimming of already-passed rows was checked at the larger size and is
fine as it stands.

The poll Timer was split in two and tested live - the chooser still
dismisses on click-away. `pollTimer` runs unconditionally and only asks
the daemon what to draw; `focusWatch` runs `while root.chooser` and only
samples `root.active`. Nothing left open in this section.

## Then

- **Finalise the browser extensions - signed, and in the stores.**
  Chrome Web Store for the chromium build (covers Brave and Vivaldi),
  AMO for Firefox, ATN for Thunderbird. Right now all three are loaded
  unpacked from this worktree, which is not just an install
  inconvenience: an unpacked extension's id depends on the directory it
  was loaded from, so moving or re-adding it mints a new `instanceId`.
  That is exactly what caused the re-bind bug fixed in 660c952. Signed
  and installed from a store, the id is stable and updates arrive on
  their own.

- `~/.config/backnavrc`, with `DwellMs` reloading live. The dwell that
  ends a gesture is a hard-coded guess judged by feel; this makes it
  adjustable without an edit-and-restart cycle.

- Stale dev sandbox teardown, and writing the sandbox lessons into
  `dev/README.md`. Teardown is `dev/kwin-sandbox.sh stop` - **never**
  `pkill -f 'dev/sandbox_daemon\.py'`, which matches the invoking
  shell's own command line and kills it.

  A lesson to write up while it is fresh (2026-08-13): **hot-loaded
  overlay QML can outlive `unloadScript`.** Measured today - with
  `backnav-overlay` reporting `isScriptLoaded false` and only the
  `backnav` event producer left (which makes no D-Bus calls at all),
  GetPeekState was still arriving at a full 80ms cadence from
  `kwin_wayland` itself. An orphaned Window and its Timer, from some
  earlier `loadDeclarativeScript`, with no script node left to unload
  it by.

  Two consequences. The "~37-38 GetPeekState in 3s = exactly one
  instance" rule is only sound in a KWin that has been restarted since
  the last hot-load; otherwise the baseline is 37 per orphan and the
  count proves nothing. And orphans accumulate silently across a
  session, so only a compositor restart clears them.

  Also worth pinning down: `unloadScript` takes the **package id**, so
  the event producer is `backnav` - one character away from the
  project's own name, and unloading it stops focus tracking dead with
  no error and no visible symptom until a navigation is attempted.

- Kate's `openUrl` reopen bug: restoring a Kate tab can reopen a
  document rather than switch to it. Deferred by decision, not
  forgotten.

## While dogfooding

Three tab-tracking fixes landed together in 660c952 and want real use
rather than more tests. What would indicate one of them slipping:

- A tab that is **closed** still offered in the chooser. Reconciliation
  should retire it on the extension's next connect - the journal line
  `backnav: <id> reports N live tabs` is that happening.
- A browser whose **tab switches stop being noticed**, with one stale
  entry pinned near the top. That is the binding wedge returning.
  `journalctl --user -u backnav` will show whether a disconnect was
  announced.
- A row naming the **wrong application** - the "thunderbird -
  SnakeoilOS" shape, where a background tab from one browser is stamped
  with whatever had focus.

Restarting the daemon (`systemctl --user restart backnav`) clears all
three symptoms, so if a restart fixes it, it was state and not logic -
worth saying so when reporting it.

## Unexplained

A stale chooser row ("Chris Scott", 2026-08-12) cleared itself before
the reconciliation code was running, and nothing accounts for that. The
only route to `mark_tab_dead` is a `tab_closed` message and nothing
produces a late one. If an entry vanishes like that again, that is the
moment worth capturing.
