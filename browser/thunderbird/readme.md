Load as a temporary add-on in Thunderbird.

about:debugging#/runtime/this-firefox (or the equivalent page in your
Thunderbird version)

Load Temporary Add-on

Select manifest.json in this directory.

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
