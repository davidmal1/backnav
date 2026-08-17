# Outstanding

Working list for BackNav. All of it lives on `main` now: the
`mru-navigation` branch was merged in 54903f2 and retired, along with
its worktree, so `/home/david/Projects/backnav` is the only checkout and
the daemon, the KWin packages and the extensions all load from it.

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

  That churn is **chromium-only**, though - corrected 2026-08-14, having
  been written here as if it applied to all three. Both Gecko builds pin
  `browser_specific_settings.gecko.id`, so their extension id survives a
  path change and their stored `instanceId` survives with it. Watched
  live: Thunderbird kept `bb3815d6` across several reloads, while the
  chromium build minted `76385c1e` the moment it was re-added from a new
  directory.

  Decided while fixing the Gecko keepalive (a2cb133): Thunderbird stays
  on MV3 rather than dropping to MV2 with a persistent background page.
  MV2 was the fallback if the event page could not be kept alive, and it
  would have sidestepped Gecko's idle rules entirely - but the keepalive
  works, so the fallback is not needed and MV2 would only have meant
  submitting on a manifest version with no future. Recorded so it is not
  re-argued at submission time.

- **Done (2026-08-17):** `~/.config/backnavrc`, with `DwellMs` reloading
  live. No watcher and no reload signal - each read stats the file and
  re-parses only if it changed, so an edit lands on the next gesture.
  Bad input is reported once to the journal and ignored in favour of the
  default; a typo costs a log line, not a working daemon. Copy
  `backnavrc.example` to get a commented starting point.

  `DwellMs` is the only setting, and the file is deliberately not a home
  for every number that could be one. A setting is a promise to keep a
  behaviour working and a question the user has to answer, so the bar is
  "genuinely a matter of taste".

  Which is what settled the panel question in the same sitting. The
  overlay's "appear after N taps" threshold was briefly made configurable
  here, then removed outright: **taps never show the panel now, holds
  always do.** Tried at 2, judged intrusive, raised to 4, dropped after
  use - no value was right, because any threshold splits a walk into a
  quiet phase and a loud one with the change landing mid-gesture. Making
  it a setting would have preserved a bad idea behind a default.

  Consequence worth watching while dogfooding: hold is now the only route
  to the panel, and it is gated on the system keyboard repeat delay
  (600ms here), so it is not instant. If that grates, the fix is to detect
  a hold from "pressed, and no Released within N ms" rather than waiting
  for the first auto-repeat - KGlobalAccel does deliver Released, so this
  is available, just not needed yet.

- Writing the sandbox lessons into `dev/README.md`. Teardown is
  `dev/kwin-sandbox.sh stop` - **never** `pkill -f
  'dev/sandbox_daemon\.py'`, which matches the invoking shell's own
  command line and kills it.

  The stale sandbox itself is gone (2026-08-14), and clearing it turned
  up a gap worth documenting: **`stop` cannot reach anything started via
  `exec`.** A `kwin-sandbox.sh exec` process gets no pidfile, so
  `cmd_stop` checks daemon/fakenav/kwin/shell/launcher, finds them all
  dead, and reports "sandbox is not running" while an orphan carries on.
  One had been running since Aug 11 with its cwd on a since-deleted
  worktree. Explicit pids are the only way out, which is the one case
  where the `pkill -f` temptation is strongest and still wrong.

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

- Kate's `openUrl` reopen bug is **fixed** (2026-08-14). `restore()` now
  calls `activate(token)` - "switch to this document if it still exists"
  - instead of `openUrl(path)`, which means "open this file" and did.

  It never needed the `live_targets()` machinery the qpdfview fix used,
  and the reason it was deferred turned out not to apply: confirming a
  live open-documents query needed a running Kate, but no such query is
  involved. Probing Kate's D-Bus surface settled three things - there is
  genuinely no way to enumerate open documents; `tokenOpenUrl` on an
  ALREADY-open path returns that document's existing token rather than
  duplicating the tab, and does not raise Kate's window; and `activate()`
  on a dead or invented token is a silent no-op. So the adapter mints a
  token at resolve time, when the document is provably open, and restores
  with it.

  Confirmed end to end against a live Kate: a document was tokenised
  while open, closed by hand, and `restore()` on its entry returned
  success while changing nothing - no reopened tab, `windowFilePath`
  still empty. Not a vacuous pass either, since `restore()` on the same
  token while the document was still open did activate it.

  Optional follow-up, deliberately not done: Kate also emits
  `documentClosed(token)`, which would let closed documents be pruned
  from the chooser the way browser tabs are via `mark_tab_dead`, rather
  than sitting there as dead rows that quietly do nothing. Not needed for
  the bug - a stale entry is now inert rather than harmful - so it is a
  separate improvement. Note it fires once per outstanding token, not
  once per document, so any handler has to be idempotent.

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
