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
| `firefox/` | `browser_specific_settings.gecko.id` | `backnav@local` |
| `thunderbird/` | `browser_specific_settings.gecko.id` | `backnav@localhost` |

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

- **No icons anywhere.** No `icons` key in any of the three manifests.
  The Chrome Web Store requires a 128x128, and both Gecko stores want a
  set. This is the one hard blocker - nothing can be submitted without
  it.

- **`<all_urls>` is almost certainly too broad**, in both `chromium/` and
  `firefox/`. Nothing here uses a content script, `fetch`, or
  `executeScript`; the only two things needing permission are reading
  `tab.url` - already covered by the `tabs` permission - and opening the
  WebSocket to `ws://127.0.0.1:8765`.

  Worth narrowing before submitting, for two reasons that both bite:
  reviewers treat `<all_urls>` as a request to justify, and users see
  "Read and change all your data on all websites" at install time, which
  is an alarming prompt for something that watches tab titles.

  Try removing `host_permissions` entirely first, then reload and confirm
  the daemon still logs tab switches. If the socket turns out to need it,
  narrow to the loopback origin rather than restoring `<all_urls>`.
  Untested either way - the extension has always had it.

- **Versions disagree.** `chromium/` and `firefox/` say `0.1`,
  `thunderbird/` says `0.1.0`. Pick one scheme and bump all three to a
  real release number.

- **`backnav@local` is a placeholder id** for the Firefox build. It works,
  but a domain you control reads better on a public listing, and the id
  cannot be changed later without it counting as a different add-on.

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

1. Icons. Hard blocker, and needed identically by all three.
2. Narrow the permissions, and re-test. Cheapest thing that improves both
   review odds and the install prompt.
3. Align versions, and decide on a real Firefox id.
4. Thunderbird first, via whichever ATN route works - it has the most to
   gain, being the only build that does not currently survive a restart.
5. Chromium last. It is the fiddliest (account, fee, review, and the
   `key` swap above) and the one whose pain has already been removed by
   pinning the id.
