# qpdfview: one-time setup

BackNav's qpdfview adapter resolves the active tab by reading qpdfview's
own tab-persistence SQLite database (forcing a fresh write via its
`saveDatabase()` D-Bus method on every tab switch). That database is
never written to at all - `saveDatabase()` is a silent no-op - unless
qpdfview's own "Restore tabs" setting is turned on.

This only needs doing once:

Edit -> Settings... -> Behavior tab -> check "Restore tabs"

No restart needed for it to take effect (it's read fresh each time a
tab's state is saved, not just at startup) - untick it and BackNav
simply stops being able to resolve/restore qpdfview tabs again, same
as if qpdfview weren't running.

See `adapters/qpdfview.py`'s docstring for why this - and
`jumpToPageOrOpenInNewTab` rather than `open()`/`openInNewTab()` for
restoring - were the confirmed-live-safe choices.
