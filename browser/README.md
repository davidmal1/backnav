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

- ~~**Versions disagree.**~~ **Done 2026-08-18:** all three are `0.1`.

  Worth knowing before the first submission: a store will not accept the
  same version twice, and versions may only go up. So `0.1` is spent the
  moment anything is uploaded, even a submission that is then rejected -
  the next attempt has to be `0.2` or `0.1.1`. Bump all three together
  regardless of which build changed, so a single number always describes
  the whole set.

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

**ATN** for Thunderbird - I have not confirmed whether it offers an
equivalent self-distribution signing flow, so treat that as a question to
answer rather than a plan. If it does, it is the fix for the thing that
currently annoys most: the Thunderbird build is loaded as a *temporary*
add-on and has to be re-added every single restart. Firefox and the
chromium browsers already survive restarts; Thunderbird is the only one
that does not.

## Suggested order

1. ~~Icons.~~ Done - see above.
2. ~~Narrow the permissions.~~ Done - removed entirely, see above.
3. ~~Align versions, and decide a real Firefox id.~~ Done.
4. Thunderbird first, via whichever ATN route works - it has the most to
   gain, being the only build that does not currently survive a restart.
5. Chromium last. It is the fiddliest (account, fee, review, and the
   `key` swap above) and the one whose pain has already been removed by
   pinning the id.
