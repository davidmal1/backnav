# Outstanding

Where BackNav is up to, and what is left. Everything lives on `main`, and
`main` is pushed.

Reasoning that used to sit in this file has moved to where the code is:
`browser/README.md` for distribution, `dev/README.md` for the sandbox
traps, and comments next to the things they explain. This is a status
list, not an archive.

## Still open

- **Chrome Web Store submission**, for the chromium build - one
  submission covers Chrome, Brave and Vivaldi.

  **Optional now, which it was not a week ago.** The reason to hurry was
  that an unpacked extension took its id from the directory it loaded
  from, so moving the folder minted a new `instanceId` and broke tab
  binding. The manifest `key` fixed that, so the store now buys
  distribution and nothing else: Developer Mode is no longer a nuisance
  you are working around, it is just something you happen to have on.

  So this is worth doing exactly as much as you want BackNav usable by
  people who are not you. For them it removes a real barrier - clone a
  repo, enable Developer Mode, load unpacked, then repeat every update by
  hand. For you it changes nothing.

  Everything needed is ready: icons, minimal permissions, aligned
  versions, pinned id. See `browser/README.md`, including the note about
  swapping the manifest `key` for the Web Store's on submission day.

## Worth watching in use

Things that are fixed but whose fix is thin, or that would be quiet if
they came back.

- **A browser session restore filling the switcher with pages you never
  opened.** Fixed 2026-08-19 by guarding `tabs.onUpdated` on `tab.active`
  in the chromium and firefox extensions, and confirmed against a real
  31-tab Brave restore that produced three entries.

  Flagged here because it has **no automated test** - it is a JavaScript
  fix and there is no JS harness in this project. If a restore ever
  floods the list again, the answer is to drop the `onUpdated` listener
  entirely rather than guard it further; it exists only so a
  single-page app changing its title is noticed without a tab switch.

- The three tab-tracking signatures from 660c952, which wanted real use
  rather than more tests:
  - a **closed** tab still offered in the chooser. Reconciliation should
    retire it on the extension's next connect - the journal line
    `<id> reports N live tabs` is that happening;
  - a browser whose **tab switches stop being noticed**, with one stale
    entry pinned near the top. That is the binding wedge returning;
  - a row naming the **wrong application**, the "thunderbird -
    SnakeoilOS" shape, where a background tab is stamped with whatever
    had focus.

  Restarting the daemon clears all three symptoms, so if a restart fixes
  it, it was state and not logic - worth saying so when reporting it.

## Done

Dates are when it was confirmed working, not when it was written.

- **2026-08-19** - A missing TLS certificate no longer stops the daemon.
  The listener on 8766 exists only for Thunderbird, and `certs/` is
  gitignored, so a fresh clone used to get `FileNotFoundError` and no
  daemon at all. It now logs one line and serves 8765.
- **2026-08-19** - History is seeded from KWin's window list when the
  daemon has nothing reachable, so a mid-session restart no longer leaves
  back/forward doing nothing until you switch windows by hand. Note it
  cannot help at login on this machine: the session restores no windows,
  so there is nothing to seed until you open something.
- **2026-08-19** - A tab entry supersedes the plain window-level fallback
  for the same window, so one window stops producing two rows.
- **2026-08-18** - Extensions readied for distribution: icons in all
  three builds, host permissions removed entirely, versions aligned on
  0.1, ids pinned. Firefox signed by AMO and installed; Thunderbird
  installed as an unsigned `.xpi`, which it accepts, so it needs no store
  at all.
- **2026-08-18** - Tab URLs are no longer collected. They were sent on
  every switch and never read, which is why `<all_urls>` could go.
- **2026-08-17** - `~/.config/backnavrc`, live-reloading, with `DwellMs`
  and `HoldMs`. Copy `backnavrc.example` to start.
- **2026-08-17** - The panel is hold-only: taps never show it, holds
  always do. A hold is detected by the clock rather than by waiting for
  auto-repeat.
- **2026-08-17** - Sandbox lessons written into `dev/README.md`.
- **2026-08-14** - Kate's `openUrl` reopen bug: `restore()` uses
  `activate(token)`, which switches to a document if it still exists and
  creates nothing. Closed Kate documents are also pruned from the
  switcher via `documentClosed`.

## Unexplained

A stale chooser row ("Chris Scott", 2026-08-12) cleared itself before the
reconciliation code was running, and nothing accounts for it. The only
route to `mark_tab_dead` is a `tab_closed` message and nothing produces a
late one.

Probably moot now - reconciliation, the supersede rule and the
`onUpdated` guard have each removed a way for stale rows to exist since.
Left here because the mechanism was never actually identified, so if a
row vanishes unaccountably again, that is the moment worth capturing.
