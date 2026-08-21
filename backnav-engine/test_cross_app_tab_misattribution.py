from core.events.browser_tab_changed import BrowserTabChanged
from core.events.event_bus import EventBus
from core.events.focus_changed import FocusChanged
from core.navigation_engine import NavigationEngine

# --- A tab event may only ever be attributed to the window that actually
# --- sent it.
#
# Reported live (2026-08-12) as a corrupt "thunderbird - SnakeoilOS" row
# sitting directly above the real "brave-browser - SnakeoilOS". Brave's
# extension reports background tabs too - a title refresh, a page
# finishing load - and those arrive whenever they arrive, including while
# some other app has focus. The engine's only test at the time was "is
# the focused app in TAB_EXTENSION_APPS", which Thunderbird is, so a
# background Brave tab got stamped with Thunderbird's app and window id.
#
# Two separate things went wrong and both are pinned below: the bogus
# history entry, and the longer-lived damage of Brave's browser window
# being re-bound to Thunderbird's KWin window - after which refocusing
# Thunderbird would push a BRAVE tab, and navigating to it would raise
# Thunderbird while switching a tab in Brave.


def items(engine):
    return [(i.app, i.title) for i in engine._history.all_items()]


event_bus = EventBus()
engine = NavigationEngine(event_bus)

# Brave is focused and the user switches to a tab. Attributed to Brave.
event_bus.publish(FocusChanged(app="brave-browser", window_id="10", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave-1", window_id=1, tab_id=5,
    title="SnakeoilOS",
))
assert engine.current.app == "brave-browser"
assert engine.current.title == "SnakeoilOS"

# The user moves to Thunderbird, which reports its own tab.
event_bus.publish(FocusChanged(app="thunderbird", window_id="20", title="Inbox"))
event_bus.publish(BrowserTabChanged(
    browser="thunderbird", connection_id="tb-1", window_id=1, tab_id=1,
    title="Inbox - Unified Folders",
))
assert engine.current.app == "thunderbird"

before = items(engine)

# THE BUG: a background Brave tab refreshes while Thunderbird has focus.
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave-1", window_id=1, tab_id=5,
    title="SnakeoilOS",
))

assert ("thunderbird", "SnakeoilOS") not in items(engine), (
    f"a background Brave tab was attributed to Thunderbird: {items(engine)}"
)
assert items(engine) == before, (
    f"a background tab event is not a navigation and must not reorder: "
    f"{items(engine)}"
)

# The window mapping must be undamaged: Brave's browser window still
# belongs to Brave's KWin window, and Thunderbird's window has not had a
# Brave tab cached against it.
assert engine._kwin_window_for_browser_window[("brave-1", 1)] == "10"
assert engine._latest_tab_by_kwin_window["20"].title == "Inbox - Unified Folders"

# Refocusing Thunderbird therefore still restores Thunderbird's own tab,
# rather than the Brave tab that used to leak into its cache.
event_bus.publish(FocusChanged(app="brave-browser", window_id="10", title="Brave"))
event_bus.publish(FocusChanged(app="thunderbird", window_id="20", title="Inbox"))
assert engine.current.app == "thunderbird"
assert engine.current.title == "Inbox - Unified Folders"

# --- The background tab is still TRACKED, just not attributed ---------
#
# Suppressing the push must not throw the event away: the whole point of
# _latest_tab_by_kwin_window is that refocusing a window picks up tab
# activity that happened while it was in the background.
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave-1", window_id=1, tab_id=9,
    title="ChatGPT",
))
assert engine._latest_tab_by_kwin_window["10"].title == "ChatGPT"

event_bus.publish(FocusChanged(app="brave-browser", window_id="10", title="Brave"))
assert engine.current.app == "brave-browser"
assert engine.current.title == "ChatGPT", (
    f"refocusing must pick up background tab activity, got {engine.current.title!r}"
)

# --- Two windows of the SAME browser must not adopt each other's tabs -
#
# _may_own() can't separate these - Vivaldi and Brave both report
# "chromium" - so this is the case the window-identity checks carry
# alone. A second Brave window appears and is focused; a tab event from
# the FIRST Brave window must not bind to or be attributed to it.
event_bus.publish(FocusChanged(app="brave-browser", window_id="11", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave-1", window_id=1, tab_id=5,
    title="SnakeoilOS",
))

assert engine._kwin_window_for_browser_window[("brave-1", 1)] == "10", (
    "window 1 of Brave must stay bound to the KWin window it was seen in"
)
assert engine.current.title != "SnakeoilOS", (
    "a tab from Brave's other window is not a navigation in this one"
)

# ...while that second window's OWN tabs work normally.
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave-1", window_id=2, tab_id=7,
    title="Lyrion Music Server",
))
assert engine._kwin_window_for_browser_window[("brave-1", 2)] == "11"
assert engine.current.title == "Lyrion Music Server"

# --- Each guard on its own -------------------------------------------
#
# The three conditions in _may_bind() overlap heavily in real usage, so
# the cases above are all stopped by more than one of them. These isolate
# each guard against a browser window that is NOT yet bound and a focused
# KWin window that is NOT yet spoken for, which is the only situation
# where a single guard is load-bearing.

# 1. Family. A SECOND Thunderbird window (a composed message, say) that
#    has never reported a tab, plus a brand-new Brave instance reporting
#    in the background. Nothing else can tell these apart - and this is
#    the reported bug in its purest form.
event_bus.publish(FocusChanged(app="thunderbird", window_id="30", title="Compose"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave-2", window_id=1, tab_id=1,
    title="H268A",
))
assert ("brave-2", 1) not in engine._kwin_window_for_browser_window, (
    "a chromium extension must never bind to a Thunderbird window"
)
assert engine.current.app == "thunderbird"
assert engine.current.title != "H268A", f"got {items(engine)}"

# 2. Tab-extension app at all. A plain window has no extension, so a tab
#    event arriving while it is focused belongs to somebody else.
event_bus.publish(FocusChanged(app="org.kde.konsole", window_id="40", title="Konsole"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="brave-3", window_id=1, tab_id=1,
    title="ChatGPT",
))
assert ("brave-3", 1) not in engine._kwin_window_for_browser_window
assert engine.current.app == "org.kde.konsole"
assert engine.current.title == "Konsole", f"got {items(engine)}"

#    Same again from an UNKNOWN family, which is where that check is
#    actually load-bearing: _may_own() deliberately lets an unrecognised
#    family match any tab-extension app, so that adding a browser to
#    browser/ cannot silently break tab tracking before someone updates
#    TAB_EXTENSION_APPS_BY_FAMILY. "Any tab-extension app" must still
#    mean SOME tab-extension app, never a plain window.
event_bus.publish(BrowserTabChanged(
    browser="ladybird", connection_id="new-1", window_id=1, tab_id=1,
    title="Ladybird Home",
))
assert ("new-1", 1) not in engine._kwin_window_for_browser_window, (
    "an unknown extension family must still not bind to a plain window"
)
assert engine.current.title == "Konsole", f"got {items(engine)}"

#    ...but it DOES bind against a real browser window, which is the
#    whole point of the permissive fallback.
event_bus.publish(FocusChanged(app="chromium", window_id="50", title="Ladybird"))
event_bus.publish(BrowserTabChanged(
    browser="ladybird", connection_id="new-1", window_id=1, tab_id=1,
    title="Ladybird Home",
))
assert engine._kwin_window_for_browser_window[("new-1", 1)] == "50"
assert engine.current.title == "Ladybird Home"

# 3. One browser window per KWin window. Vivaldi and Brave both report
#    "chromium", so the family check passes and only the fact that Brave
#    already owns KWin window 10 prevents Vivaldi's connection binding to
#    it.
event_bus.publish(FocusChanged(app="brave-browser", window_id="10", title="Brave"))
event_bus.publish(BrowserTabChanged(
    browser="chromium", connection_id="vivaldi-1", window_id=1, tab_id=1,
    title="Vivaldi Forum",
))
assert ("vivaldi-1", 1) not in engine._kwin_window_for_browser_window, (
    "KWin window 10 is already Brave's - Vivaldi cannot bind to it too"
)
assert engine._kwin_window_for_browser_window[("brave-1", 1)] == "10"
assert engine.current.title != "Vivaldi Forum", f"got {items(engine)}"

# 5. Packaging changes the resource class, and the map has to carry both.
#
#    Found on a clean Kubuntu install 2026-08-21: the snap reports
#    "thunderbird_thunderbird", the deb "thunderbird", and only the
#    latter was listed. The failure is silent and total - the extension
#    connects and reports its tabs, _may_own() then refuses every event
#    for want of a recognised window, and the switcher shows one frozen
#    window-level row instead. Nothing errors.
#
#    Firefox already carried firefox_firefox for the same reason, which
#    is what made the missing entry a gap rather than a discovery.
for spelling in ("thunderbird", "thunderbird_thunderbird"):
    engine = NavigationEngine(event_bus)
    window = f"win-{spelling}"

    event_bus.publish(FocusChanged(app=spelling, window_id=window, title="Inbox"))
    event_bus.publish(BrowserTabChanged(
        browser="thunderbird", connection_id=f"tb-{spelling}", window_id=1,
        tab_id=7, title="Add-ons Manager",
    ))

    assert engine._kwin_window_for_browser_window.get(
        (f"tb-{spelling}", 1)
    ) == window, f"{spelling} did not bind"

    assert engine.current.title == "Add-ons Manager", (
        f"{spelling}: tab event discarded, got {items(engine)}"
    )

print("cross-app tab misattribution OK")
