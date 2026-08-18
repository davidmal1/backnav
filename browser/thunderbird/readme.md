Install it properly - Thunderbird does not require signed add-ons.

    ../build-xpi.sh thunderbird

Then in Thunderbird: **Add-ons and Themes** -> the gear icon ->
**Install Add-on From File**, and pick the `.xpi` that prints.

It stays installed across restarts. Confirmed live 2026-08-18, including
that it upgrades an existing install rather than sitting alongside it,
because the id in the manifest matches - so `storage.local`, and with it
the `instanceId` the daemon keys on, carry over.

This is worth knowing because it is not true of Firefox: release Firefox
compiles signature enforcement in and ignores
`xpinstall.signatures.required`, so the same unsigned `.xpi` is refused
there and has to be signed by AMO first. Thunderbird ships that pref
defaulting to false and honours it.

### Loading it temporarily instead

For iterating on the extension itself, `about:debugging#/runtime/this-firefox`
-> **Load Temporary Add-on** -> pick `manifest.json` here. Reloads on
demand, which the installed form does not, but it is **gone on every
restart** - which is what made this the daily annoyance it used to be.

## One-time TLS setup

Thunderbird's HTTPS-Only Mode silently rewrites a plain `ws://` request to
`wss://` on the same port with no fallback, so this extension connects to
the daemon over `wss://127.0.0.1:8766` (a separate, TLS-only port -
browser extensions still use plain `ws://127.0.0.1:8765`, unaffected).
The daemon's certificate is self-signed, so Thunderbird needs to be told
to trust it once, per profile:

Settings -> Privacy & Security -> Certificates -> View Certificates ->
Servers tab -> Add Exception

Location: `127.0.0.1:8766`

Get Certificate -> Confirm Security Exception

This only needs doing once per Thunderbird profile. If the daemon's
certificate is ever regenerated (see backnav-engine/certs/), it'll need
to be re-confirmed.
