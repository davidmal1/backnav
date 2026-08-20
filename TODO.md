# Outstanding

Where BackNav is up to, and what is left. Everything lives on `main`, and
`main` is pushed.

Reasoning that used to sit in this file has moved to where the code is:
`browser/README.md` for distribution, `dev/README.md` for the sandbox
traps, and comments next to the things they explain. This is a status
list, not an archive.

## Settled, so it does not get re-argued

- **BackNav navigates tabs, not sub-window layout.** Terminal splits,
  Kate's split view, a mail client's folder and preview panes, a
  browser's side panel: none of it is navigated, anywhere, and the
  supported table saying "the individual tab" is the whole statement.

  Decided 2026-08-20 after probing terminal splits in detail. kitty
  treats a split tab as one entry; Konsole gives each pane its own
  session, so it records one entry per pane, and restoring lands on the
  tab. A note describing exactly that was written and then removed,
  because documenting it for terminals invites the same question for
  every other application and the list has no natural end.

  Worth keeping from that investigation, since it nearly went into the
  README backwards: Konsole DETECTS panes it cannot separately restore,
  and kitty ignores them. So Konsole is the finer-grained detector and
  the weaker restorer, which is the opposite of the obvious guess.

  Konsole tab restore itself is fine - verified end to end, picking an
  earlier Konsole tab from the switcher lands on the right one. D-Bus
  probing had made it look broken, because `setCurrentSession` will not
  move focus for a window that is not active, which is invisible from
  outside.

## Still open

- **Going public.** Intended eventually, not scheduled. The audit is
  done, so what is left is a short sequence rather than an investigation.

  History was checked commit by commit on 2026-08-21 and is clean. The
  only key-shaped string in it is the chromium manifest `key`, which is
  the PUBLIC half by design - it pairs with `browser/.keys/chromium.pem`,
  which has never been committed, and publishing it is what pins the
  extension id. `certs/` has never been committed either. No screenshots,
  no journal dumps, no mail account names: worth stating explicitly,
  because this is a tool whose subject matter is window titles and mail
  folders, so the plausible leak here is a debugging artefact rather than
  a credential.

  Author identity was rewritten the same day, all 85 commits, from a real
  name and personal domain to `davidmal1
  <242782351+davidmal1@users.noreply.github.com>`. Trees were verified
  byte-identical before and after. GitHub still links the commits to the
  account, so attribution and the contribution graph are unaffected.

  Reasoning worth keeping, since the first pass got it backwards: a real
  name in commit metadata was argued for as a trust and credit signal,
  but almost nobody reads `git log` to find out whose project it is -
  they read the profile. So the credit is small while the exposure is
  permanent and scraped. The profile name is reversible and commit
  history is not, which is what settled it. If the attribution is ever
  wanted, set it on the profile.

  What is left, in order:

  1. Flip visibility to public.
  2. Optionally ask GitHub Support to garbage-collect the pre-rewrite
     objects. They are unreferenced but addressable by their original
     SHAs. Low risk - the repo has only ever been private with no forks,
     so nobody has ever held those SHAs - and this is the last moment it
     stays that way.
  3. Nothing in the README needs changing. "Open an issue" already links
     to the issues tab and Issues are enabled, so the invitation becomes
     true on the visibility flip.

  One trap outside this repo: the identity fix is `--local`, deliberately,
  since changing the global would have affected every unrelated repo. The
  global is still the personal address. So any FUTURE repo meant to be
  published under `davidmal1` needs the same `git config --local` after
  cloning, and forgetting is invisible until the first push.

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

- **KMail clears all three requirements.** The first application to do so
  since qpdfview. Proven live 2026-08-19 against a real IMAP account, not
  reasoned about.

  1. *A signal that a tab changed* - the caption changes per folder and
     carries a path, e.g. `IMAP Account/Inbox - KMail`.
  2. *A way to ask which is open now* - `windowTitle` on
     `/kmail2/kmail_mainwindow_1` returns `IMAP Account/Inbox`. Plain Qt
     property, the same route Kate uses via `windowFilePath`. **Reads
     EMPTY when no folder is selected**, which is what made the first
     pass conclude there was no query at all.
  3. *A way to switch without creating* - `showFolder(collectionId)`,
     verified by round trip:

     ```
     before             IMAP Account/Inbox
     showFolder(44)  -> IMAP Account/Sent
     showFolder(45)  -> IMAP Account/Drafts
     showFolder(15)  -> IMAP Account/Inbox
     ```

  Use `showFolder`, NOT `selectFolder`. `selectFolder(QString)` takes a
  path, cannot be aimed - it returns `true` for an empty string and for
  `zzzz-nonsense-zzzz` alike, and feeding back the exact path
  `windowTitle` had just reported did not restore it - and it is not
  inert, since wrong paths clear the selection. An id also cannot be
  ambiguous the way a name can, which matters the moment two accounts
  both have an Inbox.

  **What is left is the caption-to-id heuristic, and it is qpdfview's
  problem exactly.** The caption is prettified - `IMAP Account/Inbox` -
  while Akonadi stores `akonadi_imap_resource_0/INBOX`. Different
  resource name, different case. qpdfview needed a filename-stem match
  with the page number as a tie-breaker; this needs the equivalent.

  Collection ids come from Akonadi's own SQLite database at
  `~/.local/share/akonadi/akonadi.db`, `CollectionTable` joined to
  `ResourceTable` - the same read-the-app's-own-database approach
  `adapters/qpdfview.py` already takes, including the care needed to read
  it while the application is writing.

  Note Akonadi's D-Bus interface was NOT reachable: introspecting
  `org.freedesktop.Akonadi` is refused by an AppArmor policy on
  `akonadiserver`. The database route sidesteps that, but anything built
  on the D-Bus API should expect the same refusal.

  Still gated on whether KMail actually gets used. Every supported app
  was verified in daily use rather than only probed, and an adapter
  nobody exercises is the first one that would ship on reasoning alone.
  Worth knowing before committing: the initial Akonadi sync and indexing
  is heavy.

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

- **2026-08-20** - kitty tabs are navigable, the first supported
  application not reached over D-Bus. It owns no bus name; the adapter
  speaks kitty's own JSON protocol over a Unix socket instead, which
  answers "which tab is active" outright and so needs no caption
  heuristic at all. Requires `allow_remote_control` to be enabled, the
  same shape as qpdfview's "Restore tabs".

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
