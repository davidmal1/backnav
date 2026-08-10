//
// BackNav KWin Event Producer
// Version 0.1
//

function emitEvent(window)
{
    if (!window)
        return;

    const event = {
        version: 1,
        timestamp: Date.now(),
        type: "focus",

        window: {
            id: window.internalId,
            app: window.resourceClass,
            pid: window.pid,
            title: window.caption
        },

        flags: {
            transient: window.transient,
            modal: window.modal,
            normal: window.normalWindow
        }
    };

    console.log(JSON.stringify(event));
}

// Apps whose internal tabs we track by watching for title changes on an
// already-focused window - KWin only tells us when the WHOLE window
// changes focus (see emitEvent/windowActivated below), not when the user
// switches to a different tab inside one that's already focused. Kept to
// a small allowlist rather than watching every window's caption: most
// apps change their title for reasons that have nothing to do with tabs
// (unsaved-file markers, running commands, media titles), and the daemon
// has no way to resolve or restore those anyway.
const TABBED_APPS = new Set(["org.kde.konsole", "org.kde.kate", "qpdfview.local.qpdfview"]);

function emitCaptionChanged(window)
{
    if (!window)
        return;

    console.log(JSON.stringify({
        version: 1,
        timestamp: Date.now(),
        type: "caption",

        window: {
            id: window.internalId,
            app: window.resourceClass,
            pid: window.pid,
            title: window.caption
        },

        flags: {
            transient: window.transient,
            modal: window.modal,
            normal: window.normalWindow
        }
    }));
}

function watchCaption(window)
{
    if (!window || !TABBED_APPS.has(window.resourceClass))
        return;

    window.captionChanged.connect(function() {
        emitCaptionChanged(window);
    });
}

// Raises and focuses the window with the given internalId (a UUID string,
// same format the "focus" events above report as window.id). No-op if the
// window can no longer be found (e.g. it was closed since navigating there).
function activateWindow(windowId)
{
    if (!windowId)
        return;

    const windows = workspace.stackingOrder;

    for (let i = 0; i < windows.length; i++) {
        if (windows[i].internalId.toString() === windowId) {
            workspace.activeWindow = windows[i];
            return;
        }
    }
}

// Reports a window's closure so the daemon can stop offering it as a
// back/forward target - the window may have been the frontmost thing at
// some point in history, and re-raising a closed window is a silent no-op
// that just makes navigation look stuck.
function emitClosed(window)
{
    if (!window)
        return;

    console.log(JSON.stringify({
        version: 1,
        timestamp: Date.now(),
        type: "closed",
        window: {
            id: window.internalId
        }
    }));
}

// Initial state
emitEvent(workspace.activeWindow);

for (const w of workspace.stackingOrder) {
    watchCaption(w);
}

// Future activations
workspace.windowActivated.connect(function(window) {
    emitEvent(window);
});

workspace.windowRemoved.connect(function(window) {
    emitClosed(window);
});

workspace.windowAdded.connect(function(window) {
    watchCaption(window);
});

// Back/forward navigation shortcuts. No default binding is assigned here
// (KWin scripts can't safely presume a free key combo) - assign one under
// System Settings > Shortcuts > BackNav after this script is (re)loaded.
//
// The daemon owns the history; this script just asks it what to activate
// and does the actual raising, since KWin is the only thing that can do
// that. Browser-tab entries additionally make the daemon tell the owning
// browser extension to switch tabs, as a side effect of the same call.
function navigate(direction)
{
    callDBus(
        "com.backnav.Navigator", "/com/backnav/Navigator", "com.backnav.Navigator", "Navigate",
        direction,
        function(windowId) {
            activateWindow(windowId);
        }
    );
}

// This callback only ever fires once per press - registerShortcut is
// wired to the underlying QAction's triggered() signal, with no
// hold/repeat/release equivalent exposed anywhere in the scripting API -
// so it's kept to exactly this simple "single press = jump immediately"
// behaviour. The hold+repeat-taps history preview overlay (see the
// sibling backnav-kwin-overlay/ package) does NOT hook in here: the
// daemon watches these same two shortcuts' hold/repeat/release state
// directly via KGlobalAccel's own D-Bus signals instead (see
// backnav-engine/core/overlay_controller.py), since that's the only
// place that information actually exists. A quick tap-and-release still
// produces exactly one Navigate() call from here, same as always.
registerShortcut("BackNavBack", "BackNav: Navigate Back", "", function() {
    navigate("back");
});

registerShortcut("BackNavForward", "BackNav: Navigate Forward", "", function() {
    navigate("forward");
});
