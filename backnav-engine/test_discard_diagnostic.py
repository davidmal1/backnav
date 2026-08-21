"""
The daemon says so when it throws tab events away.

This exists because of the thunderbird_thunderbird bug (2026-08-21),
which was invisible for the worst possible reason: every signal anyone
would check said healthy. The extension connected, enumerated its tabs
and reported every switch, and the connection log was clean - while
_on_browser_tab_changed discarded all of it for want of a window with a
recognised resource class. Tab navigation was completely dead and nothing
mentioned it.

The bar here is not "does it print". A diagnostic that also fires during
normal operation is worse than none, because the one line that matters
gets lost among the ones that do not. So the quiet cases are tested at
least as hard as the loud one.
"""

import io
from contextlib import redirect_stdout

from core.events.event_bus import EventBus
from core.events.browser_tab_changed import BrowserTabChanged
from core.events.focus_changed import FocusChanged
from core.navigation_engine import DISCARDS_BEFORE_COMPLAINING, NavigationEngine


def run(steps):
    """Drive a fresh engine through `steps`, returning what it printed."""
    bus = EventBus()
    engine = NavigationEngine(bus)
    buffer = io.StringIO()

    with redirect_stdout(buffer):
        for event in steps:
            bus.publish(event)

    return engine, buffer.getvalue()


def tab(connection="tb-1", browser="thunderbird", tab_id=1, window_id=1):
    return BrowserTabChanged(
        browser=browser, connection_id=connection, window_id=window_id,
        tab_id=tab_id, title=f"Tab {tab_id}",
    )


# ---- the real signature: a class no family claims ---------------------

# Exactly the snap case. Thunderbird is focused and reporting tabs, but
# its resource class is not in the table, so nothing binds and every
# event is dropped.
engine, output = run(
    [FocusChanged(app="thunderbird_snap_typo", window_id="10", title="Inbox")]
    + [tab(tab_id=n) for n in range(1, DISCARDS_BEFORE_COMPLAINING + 1)]
)

assert "discarding" in output, f"said nothing: {output!r}"

# It must name BOTH facts. Either alone leaves you guessing: the class
# without the family does not say what broke, and the family without the
# class does not say why.
assert "thunderbird_snap_typo" in output, output
assert "thunderbird" in output, output

# And say what it costs, since "discarding events" alone does not convey
# that a whole feature is off.
assert "window-level" in output, output

# ---- it says it ONCE, not per event ----------------------------------

# Tab events are continuous. A line each would bury the signal in the
# noise it is meant to cut through.
engine, output = run(
    [FocusChanged(app="thunderbird_snap_typo", window_id="10", title="Inbox")]
    + [tab(tab_id=n) for n in range(1, 40)]
)

assert output.count("discarding") == 1, f"repeated itself: {output!r}"

# ---- quiet case: a browser that has simply not been focused yet ------

# A background tab activating before its browser has ever been focused
# fails to bind too, and that is ordinary. Below the threshold it must
# stay silent - this is the false positive that would have made the
# diagnostic useless.
engine, output = run([
    FocusChanged(app="org.kde.konsole", window_id="20", title="Konsole"),
    tab(connection="brave-1", browser="chromium"),
])

assert output == "", f"complained about ordinary background chatter: {output!r}"

# ---- quiet case: discards before a successful bind do not accumulate --

# The same browser, focused later, binds and works. The earlier discards
# were transient and must not carry over towards a complaint - otherwise
# a busy start-up eventually reports a perfectly healthy browser.
steps = [FocusChanged(app="org.kde.konsole", window_id="20", title="Konsole")]
steps += [tab(connection="brave-1", browser="chromium", tab_id=n)
          for n in range(1, DISCARDS_BEFORE_COMPLAINING)]
steps += [FocusChanged(app="brave-browser", window_id="30", title="Brave")]
steps += [tab(connection="brave-1", browser="chromium", tab_id=99)]

engine, output = run(steps)

assert output == "", f"complained about a browser that then bound: {output!r}"
assert engine._kwin_window_for_browser_window[("brave-1", 1)] == "30"

# Having bound, further background chatter while something else is
# focused is attributed, not discarded, so it stays quiet indefinitely.
steps += [FocusChanged(app="org.kde.konsole", window_id="20", title="Konsole")]
steps += [tab(connection="brave-1", browser="chromium", tab_id=n)
          for n in range(100, 140)]

engine, output = run(steps)

assert output == "", f"complained after a successful bind: {output!r}"

# ---- a recognised app is never reported ------------------------------

# The fixed spelling must produce silence, which is what distinguishes
# "this diagnostic works" from "this diagnostic fires constantly".
engine, output = run(
    [FocusChanged(app="thunderbird_thunderbird", window_id="10", title="Inbox")]
    + [tab(tab_id=n) for n in range(1, 40)]
)

assert output == "", f"complained about a supported class: {output!r}"
assert engine.current.title == "Tab 39", f"got {engine.current}"

print("OK")
