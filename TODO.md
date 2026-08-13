# Outstanding

Working list for the `mru-navigation` branch. Not merged to `main` yet -
deliberately, until the whole thing is working.

## Overlay tidy-up

Scope still to be set. Candidates noticed while working in
`backnav-kwin-overlay/contents/ui/main.qml`, none of them decided:

- **Mouse selection.** Hover and click on rows do nothing. Pointer
  events were confirmed to arrive during probing, so this is missing
  wiring rather than a platform limitation. There is a comment in
  `main.qml` marking the spot.
- **The poll Timer.** It currently does double duty - heartbeat, and
  sampling `root.active` to detect focus loss, because `onActiveChanged`
  never fires with `false`. That is load-bearing and documented, but the
  two jobs could be separated more clearly.
- Row layout, sizing and the dimming of already-passed rows.

## Then

- `~/.config/backnavrc`, with `DwellMs` reloading live. Offered, never
  started.
- Stale dev sandbox teardown, and writing the sandbox lessons into
  `dev/README.md`. Teardown is `dev/kwin-sandbox.sh stop` - **never**
  `pkill -f 'dev/sandbox_daemon\.py'`, which matches the invoking
  shell's own command line and kills it.
- Kate's `openUrl` reopen bug. Deferred by decision, not forgotten.

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
