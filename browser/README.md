# Distributing the extensions

Three builds, three stores, five browsers. This is the map, and the list
of what is still missing before any of it can be submitted.

## Which build goes where

| build | covers | store | cost |
| --- | --- | --- | --- |
| `chromium/` | Chrome, **Brave**, **Vivaldi** | Chrome Web Store | one-off developer fee |
| `firefox/` | Firefox | addons.mozilla.org (AMO) | free |
| `thunderbird/` | Thunderbird | addons.thunderbird.net (ATN) | free |

The important line is the first one: **Brave and Vivaldi install from the
Chrome Web Store**, so one chromium submission covers all three browsers.
There is no separate Brave store or Vivaldi store to deal with.

That makes it three submissions, not five - and really two-and-a-bit,
since `firefox/` and `thunderbird/` are near-identical Gecko builds.

## The identity problem, and why it is already solved

Each store needs the extension to have a stable id, and each build now
pins one:

| build | pinned by | id |
| --- | --- | --- |
| `chromium/` | `key` in the manifest | `fniehifalbhemldjkglbkbdigjpdimhh` |
| `firefox/` | `browser_specific_settings.gecko.id` | `backnav@davidmal1.github.io` |
| `thunderbird/` | `browser_specific_settings.gecko.id` | `backnav@davidmal1.github.io` |

This used to be the main argument for hurrying to the store: an unpacked
chromium extension took its id from the directory it was loaded from, so
moving the folder minted a new id, a new `storage.local` and a new
`instanceId` - which is what caused the re-bind bug fixed in 660c952.
The manifest `key` removes that, so the store is now wanted for
distribution rather than needed for correctness.

**On submission day**, replace the chromium `key` with the one from the
Web Store dashboard. Otherwise the published extension gets a different
id from the local unpacked one and the two behave as unrelated
extensions - separate storage, separate `instanceId`, both talking to the
daemon at once if both are installed.

### Changing an id installs a SECOND copy - it does not upgrade

The trap behind that paragraph, learned the hard way on 2026-08-18.

Changing `gecko.id` on the Thunderbird build and reloading it did not
replace the old add-on. Thunderbird treated
`backnav@davidmal1.github.io` as a different add-on from
`backnav@localhost` and installed it alongside, so both were loaded and
both connected - visible in the daemon journal as two live ids reporting
the same 4 tabs, and on screen as duplicate Thunderbird rows in the
chooser.

Which is obvious in hindsight: the id IS the add-on's identity, so
changing it cannot be an upgrade of the thing it identifies.

The same applies to the chromium `key`, and that matters precisely when
swapping it for the Web Store's. Remove the unpacked copy at that point
rather than leaving it loaded, or Brave and Vivaldi will run the store
build and the unpacked build at once, both talking to the daemon.

Symptom to recognise, in any browser: duplicate rows for one application
that do not go away, and two connection ids in
`journalctl --user -u backnav` reporting identical tab counts.

## What is not ready yet

These are gaps in this repo, not in the process.

- ~~**No icons anywhere.**~~ **Done 2026-08-18.** All three builds carry
  16/32/48/96/128 in `icons/`, generated from `icon-src/` by
  `icon-src/render.sh`.

  Two SVG sources rather than one, which is worth knowing before editing
  them. The full artwork is a miniature of the switcher itself - the
  overlay's own `#202020` panel, its `#80c0ff` highlight on the back
  arrow, and three rows dimming with depth exactly as the panel dims the
  entries a walk has passed. Below about 48px those three rows merge into
  an illegible smear, so 16 and 32 use `icon-small.svg`: two chunkier
  rows and a bigger arrow. Rendered and compared at 4x before picking the
  crossover, rather than guessed.

- ~~**`<all_urls>` is too broad.**~~ **Gone entirely, 2026-08-18.** No
  build requests any host permission now; all three ask only for `tabs`,
  `storage` and `alarms`.

  It was not narrowed, it was made unnecessary. `<all_urls>` was there to
  read `tab.url` - and nothing ever read the URL back. The extensions
  sent one on every tab switch, the daemon stored it on a
  `BrowserTabChanged` event, and no code anywhere touched it again. So
  every tab you visited crossed a socket for nothing, which is both a
  privacy liability and the first thing a reviewer asks about.

  Removing the field removed the reason for the permission. Done in that
  order deliberately: dropping the permission while still reading
  `tab.url` risked it arriving `undefined`, which would have raised a
  KeyError in the daemon on every tab switch and killed the connection.

  Confirmed live afterwards - all three extensions connect, reconcile and
  report correct titles with no host permission at all, which also
  settles the open question of whether the loopback WebSocket needed one.
  It did not.

  What a user is asked to approve is now just tab access, and the honest
  description of this extension is "reads tab titles, sends them to a
  daemon on localhost".

- ~~**Versions disagree.**~~ **Done 2026-08-18:** all three aligned.
  **Now `0.2`**, bumped together on 2026-08-21 to carry the Firefox
  `update_url` below.

  Worth knowing before the first submission: a store will not accept the
  same version twice, and versions may only go up. So `0.1` is spent the
  moment anything is uploaded, even a submission that is then rejected -
  the next attempt has to be `0.2` or `0.1.1`. Bump all three together
  regardless of which build changed, so a single number always describes
  the whole set. `0.1` is genuinely spent: it was uploaded and signed.

- ~~**`backnav@local` is a placeholder id.**~~ **Settled 2026-08-18:**
  both Gecko builds now use `backnav@davidmal1.github.io`.

  Domain-shaped because that is the format - the id is email-shaped or a
  GUID, so a repository URL cannot be used directly. `davidmal1.github.io`
  is the Pages domain GitHub reserves for that account, so it is provably
  ours and cannot collide in AMO's global id namespace, which is what the
  old `backnav@local` could not promise.

  **Both builds deliberately share one id.** AMO and ATN are separate
  registries and Firefox and Thunderbird are separate applications with
  separate profiles, so there is no collision: one id names "the BackNav
  extension" across both. The alternative - suffixing the Thunderbird
  one - would read as two products, which they are not.

  Changeable only until the first upload to either store. After that the
  id is permanent: a different one is a different add-on, so existing
  users get no update, and reviews and install counts start again.

## The routes, including the short ones

A full public listing is not the only option, and was not obvious:

**Chrome Web Store** offers *unlisted* visibility - installable by direct
link, not searchable, not on your public developer page. Still needs the
developer account and still goes through review, so it saves audience
rather than effort.

**AMO** offers something better: *self-distribution*. Upload the add-on,
AMO signs it and hands back a signed `.xpi` that you host anywhere.
It installs permanently in release Firefox, with no listing and no store
page. This is the genuinely shorter path.

**ATN** for Thunderbird does offer self-distribution - its review policy
says add-ons "intended for internal or private use, or for distribution
testing may not be listed on ATN. Such add-ons may be uploaded for
self-distribution instead."

**But Thunderbird does not need it.** Answered 2026-08-18, and the answer
is that no store is required at all: Thunderbird ships
`xpinstall.signatures.required` defaulting to false and honours it, so an
unsigned `.xpi` installs permanently and survives restarts. Confirmed by
doing it. `build-xpi.sh` produces one; `thunderbird/readme.md` has the
install steps.

That retires what had been the most annoying thing here - the Thunderbird
build being a *temporary* add-on that vanished on every restart. It also
means ATN is now optional for Thunderbird, wanted only for discovery.

Do not assume the same of Firefox. It ships the same pref default and
then ignores it: release builds compile signature enforcement in
(bugzilla 1298806), so an unsigned `.xpi` is refused there. Firefox is
the build that actually needs AMO, whether listed or self-distributed.
Checking the pref file is not enough to tell these two apart - only
installing one is.

## Updates, and what `update_url` costs

Added to the Firefox build on 2026-08-21, pointing at
[`firefox/updates.json`](firefox/updates.json) served from
`raw.githubusercontent.com`.

A self-distributed `.xpi` has no store behind it, so **without
`update_url` it never updates** - every user reinstalls by hand, forever.
Worse, it cannot be retrofitted: a copy already installed without the
field will not start checking because a later version has it. So it has
to be in the first build anyone installs, which is why it went in before
publishing rather than after.

**It also closes a door.** `update_url` is refused for Mozilla-hosted
add-ons, so as long as it is in the manifest, a public AMO listing is not
available - the linter rejects the upload. Self-distribution is now the
committed route for Firefox, and going listed later means removing the
field and bumping the version again.

**Signed and installed 2026-08-21**, and the upgrade behaved: 0.2 was
installed over a signed 0.1 without removing it first, replaced it rather
than sitting alongside, and kept `storage.local` - so the `instanceId`
the daemon binds tabs to survived, and Firefox tabs still showed as
separate rows immediately afterwards, with no daemon restart.

That is the id doing its job, and it is worth not removing the old
version first: an uninstall takes `storage.local` with it, and the
reinstall then mints a fresh `instanceId` - which is the re-bind bug from
660c952, self-inflicted.

Two things have to stay in step with every release, and nothing checks
them:

- `updates.json` names a version and a download link. Both must match the
  signed `.xpi` actually attached to the release, or Firefox either sees
  no update or 404s fetching it.
- The link points at a GitHub release asset. **It resolves only once the
  repository is public and that release exists** - until then update
  checks fail quietly, which is the correct behaviour for a build nobody
  else has.

## Validating before you upload

AMO runs Mozilla's `addons-linter` on submission. Run it yourself first -
it is the difference between a two-minute upload and a round of
rejections:

```
./build-xpi.sh firefox
npx --yes addons-linter@latest --self-hosted backnav-firefox-0.2.xpi
```

**`--self-hosted` is required for the Firefox build and wrong for the
Thunderbird one.** Without it the linter reports one error,
`MANIFEST_UPDATE_URL`, because `update_url` is forbidden for
Mozilla-hosted add-ons and mandatory for self-distributed ones - the flag
is how you tell it which you are uploading. Thunderbird carries no
`update_url`, so it lints with no flag:

```
./build-xpi.sh thunderbird
npx --yes addons-linter@latest backnav-thunderbird-0.2.xpi
```

Both Gecko builds are currently **0 errors, 0 warnings, 0 notices**. Two
things had to be fixed to get there, on 2026-08-18:

- **`data_collection_permissions` is now required** for all new Firefox
  extensions. Both builds declare `"required": ["none"]`, which is the
  documented value for an extension that transmits nothing off-device.
  That is accurate here: tab titles go to a daemon on `127.0.0.1` and
  never leave the machine. It is also only true because the URL
  collection was removed - had those still been flowing, `none` would
  have been a false declaration rather than a tidy one.

- **`background.service_worker` was being ignored by Firefox.** A Chrome
  key that had been copied into the Gecko build; Firefox runs
  `background.scripts` and flags the other as unsupported. Removing it
  changes no behaviour, since Firefox was already ignoring it.

The linter does not check the things a human reviewer will: that the
extension talks to `ws://127.0.0.1:8765`, and why. Expect to explain that
it is a local companion daemon, and that the repository is public.

## Suggested order

1. ~~Icons.~~ Done - see above.
2. ~~Narrow the permissions.~~ Done - removed entirely, see above.
3. ~~Align versions, and decide a real Firefox id.~~ Done.
4. ~~Thunderbird first, via whichever ATN route works.~~ Done, and it
   needed no store: it installs unsigned and survives restarts. ATN is
   now optional, for discovery only.
5. Firefox next - the one that genuinely needs AMO, since release builds
   refuse unsigned add-ons. Self-distribution signing is the short route.
6. Chromium last. It is the fiddliest (account, fee, review, and the
   `key` swap above) and the one whose pain has already been removed by
   pinning the id.
