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

  **Fixed 2026-08-18**, and no longer a reason to hurry to the store: the
  chromium manifest now carries a `key`, which is the Gecko builds'
  `gecko.id` by another name. The id is derived from that key instead of
  from the directory path, so it is now `fniehifalbhemldjkglbkbdigjpdimhh`
  wherever the folder lives, and `storage.local` - and therefore
  `instanceId` - survives with it. The private half sits in
  `browser/.keys/`, gitignored, outside `browser/chromium/` so it cannot
  be zipped into a submission; only the public half belongs in the
  manifest, and it is not a secret.

  Note for submission day: replace that `key` with the one from the Web
  Store dashboard, so the local unpacked build and the published build
  share an id rather than behaving as two different extensions.

  Unpacked survives a browser restart, which is worth knowing but is not
  a distribution route. Observed 2026-08-18 in Vivaldi and confirmed in
  the journal: `719e4f06` disconnected at 08:52 and returned at 10:00
  with the same `instanceId`. That is ordinary chromium behaviour -
  "Load unpacked" registers the extension in the profile permanently and
  reloads it from the path each start. It still needs Developer Mode
  enabled, still never auto-updates, and until the `key` above was added
  it was fragile to the folder moving. Fine as install-from-source, which
  is what it already is; it does not buy trust, discovery or updates.

  The genuinely shorter path, if a full public listing is not wanted:
  both ecosystems can distribute WITHOUT one. AMO will sign an add-on for
  self-distribution, handing back a signed `.xpi` to host anywhere, which
  installs permanently in release builds - that is the one that would
  stop Thunderbird needing a reload every restart. The Chrome Web Store
  has an unlisted visibility, reachable by direct link and not
  searchable, though it still wants a developer account and review.

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

  Hold being the only route to the panel meant it inherited the system
  keyboard repeat delay (600ms here) and felt sluggish. **Fixed the same
  day:** a press starts a `HoldMs` timer (default 250ms) which the release
  cancels, so a hold is detected by the clock rather than by waiting for
  auto-repeat. Repeats are kept as a backstop, for a machine whose repeat
  delay is shorter than `HoldMs`. `HoldMs` is the second backnavrc
  setting.

- **Done (2026-08-17):** the sandbox lessons are written up, under
  "Things that have actually gone wrong" in `dev/README.md` - the
  `pkill -f` self-kill, `stop` being unable to see `exec`-started
  processes, hot-loaded QML outliving `unloadScript`, and `unloadScript`
  taking a package id where `backnav` is the event producer. They live
  next to the tool now rather than in this file.

  Writing it up turned up one more, which is in there too: the
  `Script1`, `Script2`... nodes under `/Scripting` are NOT a reliable
  count of live scripts. Both packages reported `isScriptLoaded true`
  with the overlay demonstrably running while introspection listed a
  single node, having listed two earlier the same day. Ask about a
  package by name.

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

  **Also done (2026-08-17):** closed Kate documents are now pruned from
  the switcher rather than left as inert rows, via Kate's
  `documentClosed(token)` signal - `core/kate_watcher.py`. Left as a row
  they were not harmless after all: selecting one still raised the Kate
  *window*, landing you in Kate on whatever document happened to be
  current instead of the one you picked.

  One match rule covers every Kate process rather than a subscription per
  pid - the token identifies the document by itself, so the sender does
  not matter, which avoids both per-pid lifecycle and starting async
  subscriptions from the KWin monitor thread. The adapter's token cache
  doubles as `live_targets()`, so the engine's existing skip loop does the
  work with no new engine code. Confirmed end to end against a live Kate.

## Known, diagnosed, not yet fixed

- **A duplicate row for a tabbed app, which vanishes once you select it.**
  Reported 2026-08-17: two Thunderbird rows in the chooser, one selected,
  and on the next hold the other had gone. Nothing is lost - the row that
  vanished pointed at the same window - but it reads alarmingly, and the
  natural reading ("I must have two windows open") is wrong.

  Reproduced, so this is understood rather than suspected. There are two
  entries because there really are two: a `browser_tab` entry, and a plain
  window-level fallback with `restore_type=None` for the same window. The
  fallback is written when the window gains focus BEFORE the extension has
  reported a tab for it - which is the daemon-restart race, and matches the
  incident exactly (daemon up at 14:49:21, Thunderbird connected at
  14:49:22).

  It then vanishes because `_is_noop_window_entry` hides a plain fallback
  only when we hold better information for that window AND it is the
  window that currently has focus. Selecting Thunderbird satisfies the
  second condition, so the duplicate hides itself the moment you act on
  it. Reproduction:

  ```
  focus other -> focus TB (no tab yet) -> tab event for TB -> focus other
      = two TB rows
  focus TB
      = one TB row
  ```

  The obvious fix - dropping the `window_id != _current_window_id` clause
  so the fallback is always hidden when better info exists - is **wrong**,
  and the suite says so: `test_navigation_engine` and `test_lost_tab_close`
  both lose a real, reachable entry ("New Tab", "Brave"). Where no tab
  entry exists for that window the fallback is the only representation of
  it, and swallowing it is worse than showing a duplicate.

  The narrower fix is to supersede at INSERT time rather than filter at
  walk time: when a tab entry arrives for a window, retire any earlier
  plain window-level entry for that same window, since it can only be a
  degraded duplicate of what just arrived. Untried.

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
