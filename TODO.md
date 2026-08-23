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

- **Chrome Web Store submission**, for the chromium build - one
  submission covers Chrome, Brave and Vivaldi.

  **Decided 2026-08-21: not now.** Three of the four reasons to submit do
  not survive contact with who actually installs this.

  What removed the urgency, earlier: an unpacked extension used to take
  its id from the directory it loaded from, so moving the folder minted a
  new `instanceId` and broke tab binding. The manifest `key` fixed that,
  which left the store buying distribution and nothing else.

  *The Developer Mode barrier* is real for a general audience and not for
  this one. Anyone here has already cloned a repo, apt-installed
  dependencies, hand-written a systemd unit and run openssl. Load
  unpacked is easier than several steps they have already completed.

  *Manual updates* looked like the strong argument and is the weakest.
  The extension ships in the same repository as the daemon, so the
  `git pull` that updates BackNav updates the extension too - the only
  extra cost is clicking reload. And it cuts the other way: there is NO
  protocol version negotiation between daemon and extension, so a
  store-installed copy updating on Google's schedule could drift ahead of
  the daemon with nothing detecting it. Unpacked keeps them in lockstep
  by construction, which is a point FOR staying off the store.

  *Trust* stands - asking someone to enable Developer Mode is a bigger
  ask than a store install, and no amount of readme fixes that.

  *Discovery* is the only reason left with force, and it is the honest
  one: nobody finds an unpacked extension. The repo went public the same
  day this was decided, so the question is now simply whether anyone
  turns up - revisit if they do.

  **Chrome offers no middle path, which is what makes this binary.**
  Firefox had self-distribution: AMO signs it, you host it. Chrome blocks
  off-store `.crx` installs for ordinary users outright, so it is the Web
  Store or unpacked with nothing between - no cheap halfway option to
  reach for later.

  Nothing is lost by waiting. The one genuinely time-sensitive piece was
  the id, and the manifest `key` already pins it. Everything else is
  ready: icons, minimal permissions, aligned versions. See
  `browser/README.md`, including the note about swapping the manifest
  `key` for the Web Store's on submission day, and the trap that follows
  it - the old unpacked copy must be removed at that point or both run at
  once.

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

- **`websockets.server.serve` is deprecated** and warns on every apt
  build. Still present and working in 15.0.1 and 17.0.1 - proven on
  2026-08-21 with a real TLS bind and round trip under apt's 15.0.1, not
  just an import check - but it is the legacy API and will go. The
  replacement is `websockets.asyncio.server`. Nothing forces the move
  yet; the day it does, the daemon stops starting rather than degrading,
  so it is worth doing before a release rather than after a report.

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

- **2026-08-23** - Opera supported, the seventh application and the first
  added by following the diagnostic rather than investigating. It reports
  `Opera`, capitalised where every sibling is lowercase; the set is
  matched exactly, so the case is as load-bearing as the spelling. Both
  spellings are pinned, including that lowercase `opera` must NOT bind,
  so the real one cannot decay into an untested guess.

  Answered while adding it: should the table just say "Chromium-based
  browsers"? No. The extension does work in any of them, but a window is
  identified by the exact name KWin reports, so the general claim would
  be false for every browser nobody had checked. The table stays specific
  and the README now says how to extend it.

- **2026-08-23** - Escape from the chooser raises nothing when nothing
  was focused. Minimise everything, hold, Escape, and a window used to
  come back.

  Cancelling raises the entry the gesture started on deliberately - the
  panel takes keyboard focus and closing it has to hand focus back. That
  assumes the gesture started FROM a focused window. The daemon could not
  tell: KWin fires `windowActivated(null)` when the last window is
  minimised, and the script dropped it, so "nothing is focused" was
  indistinguishable from "unchanged". The script now emits a `blur`
  event and `FocusLost` clears the current window.

  History is deliberately untouched by a blur - those windows still exist
  and Meta+Tab out of an empty desktop is exactly what has to keep
  working.

- **2026-08-23** - The discard diagnostic was made honest, one day after
  shipping. It produced four complaints in a day, every one describing
  correct behaviour as breakage, including `firefox_firefox` - a class
  added the day before.

  Worth keeping because the lesson is not "there was a bug". Discarding
  has three causes and only one is a fault; the first version reported
  all three with the wording of the first. That is exactly the cry-wolf
  failure the design notes argued was worse than no diagnostic at all,
  committed by the person who wrote the argument. All four journal lines
  are now tests.

  Found because a question about Opera sent someone to the journal. Not
  because the daemon was suspected of anything - which is the point: a
  noisy diagnostic is not self-reporting.

- **2026-08-22** - History capped at 20 entries, and the dead-id sets
  stopped leaking. Raised as a memory-safety worry, which it was not:
  entries are a few hundred bytes and Python cannot corrupt memory by
  holding a long list. Measuring it found the real problem next door -
  `_dead_windows` only ever grew, so every window and tab closed since
  the daemon started left a permanent trace. 2000 opened-and-closed tabs
  left 2000 entries and 2000 dead ids; now 20 and 20.

  Dead entries are evicted first, which is what makes a small cap safe:
  they are skipped rather than removed, so a cap counting them would not
  be a cap on places you can reach.

  The cap is 20 because deep history has no use, not because it is
  expensive - the thirtieth entry is quicker to reach with the mouse.

- **2026-08-21** - The daemon says so when it discards tab events. One
  line, once per (resource class, family) pair, naming both facts and
  what it costs:

  ```
  backnav: discarding thunderbird tab events - focused window is
  'thunderbird_thunderbird_x', which no extension family claims. Tab
  navigation is inactive for it; window-level still works.
  ```

  The thunderbird_thunderbird bug would have been a one-line diagnosis
  instead of a long hunt, because every other signal said healthy while
  the feature was entirely dead.

  The work was not in printing it but in staying quiet. Failing to bind
  is ORDINARY - a background tab activating before its browser has ever
  been focused does it - so a naive version fires constantly and is worse
  than nothing. It complains only after `DISCARDS_BEFORE_COMPLAINING`
  events from a connection that has never bound, and a successful bind
  clears the count, which separates "not focused yet" from "will never be
  recognised". The quiet cases carry more of the test file than the loud
  one.

- **2026-08-21** - Public, at https://github.com/davidmal1/backnav, with
  a `v0.2` release carrying the signed Firefox extension.

  The audit that preceded it found nothing to clean up. The only
  key-shaped string in the history is the chromium manifest `key`, which
  is the public half by design and is what pins the extension id; the
  private half, the TLS certificate and the signed `.xpi` have never been
  committed. No screenshots, no journal dumps, no mail account names -
  worth stating for a tool whose subject matter is window titles.

  Author identity was rewritten across all 85 commits beforehand, from a
  real name and personal domain to the account's noreply address, with
  the trees verified byte-identical before and after. GitHub still links
  the commits, so attribution survives and only the domain is gone.

  Verified after the flip rather than assumed: an anonymous clone with no
  credentials succeeds, and the Firefox `update_url` returns 200. The
  release asset was fetched from the exact URL `updates.json` names and
  hashes identical to the signed file, still AMO-signed after the round
  trip - so the update chain is proven, not just wired up.

  Left deliberately undone: the pre-rewrite objects are still on GitHub,
  unreferenced but addressable by their original SHAs. They differ from
  the current ones only in author metadata, and nobody has ever held one
  of those SHAs. Support can still garbage-collect them on request.

- **2026-08-21** - The install works on a machine that is not this one.
  Followed end to end on a clean Kubuntu VM by someone reading the page
  rather than remembering it, which the README had never had.

  It found one code bug and eight documentation ones. The bug is the
  Thunderbird snap's resource class, above. The rest were all the same
  shape: a step that assumes a state this machine was already in - a
  directory that exists, a dependency already installed, a daemon already
  running, a `cd` still in effect from four sections earlier.

  Two are worth remembering beyond their fixes, because both were
  invisible from a working machine:

  - `pip install dbus-next websockets` **cannot succeed** on Ubuntu 24.04
    or later, and the systemd unit named `/usr/bin/python3`, which has
    never had those modules here - the daemon runs from a venv. So the
    documented configuration had never worked anywhere, including on the
    machine it was written on. Both are apt packages; installing them
    that way makes the unit correct as printed.

  - The page was written to be read top to bottom and is used by jumping
    into it. Every "only if you use X" heading is an entry point, and
    each one inherited context from sections above it.

  Structural outcome: the daemon is now set up under systemd inside
  Installing, rather than run by hand there and daemonised a hundred
  lines later. That deleted a whole section, a warning about port
  clashes, and a set of dual by-hand/systemd instructions - the conflict
  had been created by the page's own ordering.

  Also proven on that machine: the signed Firefox 0.2 as a FRESH install,
  where the same file had only ever been tested as an upgrade over 0.1.
  Both paths now hold.

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
