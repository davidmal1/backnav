/*
    BackNav's history preview overlay.

    An Alt+Tab-style switcher over most-recently-used ordering: each tap
    of the shortcut walks the highlight one row down a list that itself
    holds still, and the list is only reordered once the gesture goes
    quiet.

    The gesture cannot be driven the way Alt+Tab's is. KGlobalAccel never
    reports a modifier's release - only individual key releases - so
    "the user let go of Alt" is not an observable event here, and the end
    of a gesture is inferred from an idle dwell instead. See
    overlay_controller.py's docstring for the measurements.

    A *separate* KWin script package from backnav-kwin/ (plain
    "javascript"-API script, contents/code/main.js) rather than a QML
    file loaded by it, because KWin's plain JS scripting API has no
    createDialog()/component-loader of any kind - confirmed against the
    KWin 6 scripting API docs, which expose only print/readConfig/
    registerScreenEdge/registerShortcut/callDBus/registerUserActionsMenu
    at the global scope, nothing for putting arbitrary QML on screen.
    "declarativescript" mode (X-Plasma-API in this package's
    metadata.json) is the one KWin script mode that *can* draw a real
    Window - modelled directly on KDE's own official example package
    (kwin.git's examples/quick-script), which does exactly this
    (Window { flags: Qt.BypassWindowManagerHint | Qt.FramelessWindowHint }).

    This script has no shortcuts of its own - backnav-kwin/'s
    registerShortcut("BackNavBack"/"BackNavForward", ...) calls still own
    the action names. Those callbacks are now EMPTY, though: they used to
    navigate too, which double-navigated every tap (see that file, and
    overlay_controller.py, for the full story). The daemon is the only
    thing that navigates now.

    That makes this package load-bearing rather than cosmetic: raising
    the target window is now solely this script's job, via
    activateWindow() below, because on Wayland only KWin can raise a
    window and the daemon cannot push a D-Bus signal into a KWin script.
    With this package disabled, the history cursor still moves and
    browser tabs still switch, but no window is ever raised.

    Instead of shortcuts, this purely polls and renders: see
    backnav-engine/core/overlay_controller.py's docstring
    for the full why (short version: KGlobalAccel itself - not either
    KWin script - is what actually knows about hold/repeat/release, and
    there's no way for the daemon to push a D-Bus signal into this QML
    engine, so it asks instead, on a fast Timer, via
    NavigatorService.GetPeekState()).
*/
import QtQuick
import QtQuick.Window
import org.kde.kwin as KWinComponents

Window {
    id: root

    readonly property int rowHeight: 28
    readonly property int rowWidth: 420

    property int highlightIndex: -1

    // Visibility is driven explicitly rather than bound to entries.count.
    //
    // `visible: entries.count > 0` looks equivalent and is not: applyState()
    // rebuilds the model with clear()+append(), so the count passes through
    // 0 on every single rebuild, which hides and re-shows a real on-screen
    // Window. At the 80ms poll rate that is ~12 hide/show cycles a second -
    // observed live as the panel "refreshing constantly".
    property bool showing: false

    // Signature of the last applied ENTRY list, so an unchanged poll result
    // is skipped instead of pointlessly rebuilding the model. The daemon is
    // polled continuously but the rows only actually change between
    // gestures, not between the taps within one.
    //
    // Deliberately excludes highlightIndex. The rows are stable across a
    // gesture and only the highlight moves, so folding the highlight into
    // this key would rebuild the entire ListView on every tap purely to
    // recolour one row.
    property string contentKey: ""

    color: "transparent"

    // ---- STAGE 2 EXPERIMENT: can this window take keyboard focus? -----
    //
    // Was Qt.BypassWindowManagerHint | Qt.FramelessWindowHint. The probe
    // proved that combination is input-transparent to the KEYBOARD while
    // still receiving the pointer: hover and tap both arrived, no key
    // event ever did, and window.active never once became true. Bypass
    // tells KWin not to manage or focus this window, and no focus means
    // no key delivery; pointer events route by position and so are
    // unaffected.
    //
    // Qt.Popup is what KWin's own switchers use (see
    // /usr/share/kwin/tabbox/compact/) - they pair it with
    // Qt.X11BypassWindowManagerHint, which is a no-op on Wayland, so on
    // this session they are effectively plain popups, and they do get
    // keys.
    // RESULT: Qt.Popup | Qt.FramelessWindowHint plus requestActivate()
    // DOES work - window.active went true and Qt.Key_Down arrived. Keys
    // are therefore possible, and this is the combination to come back
    // to.
    //
    // Reverted for now because it is not usable on its own. Raising the
    // target window is this script's other job (activateWindow() below),
    // and a focused panel fights it: every tap raises the target, the
    // target takes focus, the panel loses it, and a Qt.Popup that loses
    // focus hides itself. Observed live as the panel "kept disappearing
    // or was not visible".
    //
    // The fix is not a flag, it is a model change - a focused panel must
    // defer raising until the selection is CONFIRMED, the way Alt+Tab
    // does. Until that is built, Bypass is the correct behaviour: no
    // focus, no fight, panel stays put.
    flags: Qt.BypassWindowManagerHint | Qt.FramelessWindowHint
    visible: showing

    width: rowWidth + 24
    height: Math.max(Math.min(entries.count, 8), 1) * rowHeight + 24
    x: Screen.virtualX + (Screen.width - width) / 2
    y: Screen.virtualY + (Screen.height - height) / 2

    ListModel {
        id: entries
    }

    Rectangle {
        anchors.fill: parent
        color: "#e6202020"
        radius: 8
        border.color: "#40ffffff"
        border.width: 1
    }

    // ---- TEMPORARY INPUT PROBE (remove once answered) ----------------
    //
    // Establishes whether this window can receive input at all, which
    // decides whether the list can be driven with up/down and the mouse.
    //
    // Unknown because KWin's own switchers are not a precedent: they get
    // key events from KWin's C++ TabBox keyboard GRAB, which we do not
    // have, and they use Qt.X11BypassWindowManagerHint (a no-op on
    // Wayland) where this window uses the cross-platform
    // Qt.BypassWindowManagerHint, which does apply and asks KWin not to
    // manage or focus us.
    //
    // Deliberately logging only - no window flags are touched here, so
    // this cannot change how the panel behaves on screen.
    //
    // Reported over D-Bus rather than console.log/console.warn, because
    // QML logging from a declarativescript goes nowhere at all: this
    // window is provably alive (it polls GetPeekState 12x/sec) and still
    // produced not one line in the user or system journal.
    property string probeNote: ""

    function probe(note) {
        root.probeNote = note;
        probeCall.call();
    }

    KWinComponents.DBusCall {
        id: probeCall
        service: "com.backnav.Navigator"
        path: "/com/backnav/Navigator"
        dbusInterface: "com.backnav.Navigator"
        method: "Probe"
        // A binding rather than an imperative probeCall.arguments = [...]
        // assignment. The imperative form silently did nothing, and with
        // QML logging going nowhere there is no way to see the throw.
        arguments: [root.probeNote]
        onFinished: function(returnValue) {}
    }

    onActiveChanged: probe("window.active=" + active)

    // Fired from a Timer rather than Component.onCompleted so that a
    // failure here distinguishes itself: onCompleted runs before the
    // script is fully wired up, and if THAT was the problem rather than
    // the arguments assignment, this still reports.
    KWinComponents.DBusCall {
        id: probePing
        service: "com.backnav.Navigator"
        path: "/com/backnav/Navigator"
        dbusInterface: "com.backnav.Navigator"
        method: "ProbePing"
        onFinished: function(returnValue) {}
    }

    Timer {
        interval: 1500
        running: true
        repeat: false
        onTriggered: {
            // Ping FIRST and unconditionally. If only this arrives, the
            // problem is passing `arguments`; if neither arrives, the
            // problem is this Timer or the script never re-instantiating.
            probePing.call();
            root.probe("loaded, flags=" + root.flags);
        }
    }

    ListView {
        id: listView
        anchors.fill: parent
        anchors.margins: 12
        model: entries
        interactive: false

        // PROBE: does anything deliver keys here? focus:true only sets
        // focus WITHIN this window - it cannot take focus from the user's
        // actual window, so it is safe even if the answer is no.
        focus: true
        Keys.onPressed: function(event) {
            probe("key=" + event.key + " text=" + event.text);
        }

        delegate: Rectangle {
            width: listView.width
            height: root.rowHeight
            radius: 4
            color: index === root.highlightIndex ? "#4080c0ff" : "transparent"

            // PROBE: hover is the more sensitive of the two - it shows
            // whether pointer events reach this surface at all, even if
            // clicks turn out to be swallowed somewhere above us.
            HoverHandler {
                onHoveredChanged: if (hovered) root.probe("hover row=" + index)
            }

            TapHandler {
                onTapped: root.probe("tap row=" + index)
            }

            Text {
                anchors.fill: parent
                anchors.leftMargin: 8
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight

                // Rows the walk has already gone past are dimmed rather
                // than dropped.
                //
                // They pile up above the highlight as a gesture gets
                // longer and, at full brightness, read as live options -
                // reported live from a two-step walk as the top rows
                // becoming "noise/confusing", the more so because the
                // dwell makes reversing onto them with Forward impractical
                // in the time available.
                //
                // Dimming rather than removing keeps the list still and
                // the highlight moving, which is what Alt+Tab does and
                // what makes the reordering legible. Rendering only from
                // the highlight down was the alternative and was rejected
                // twice now: it pins the highlight to row 0 and scrolls
                // the whole list up on every tap, which was observed live
                // as entries appearing from nowhere. See
                // NavigationEngine.walk_view().
                //
                // (walk_view()'s own reason for keeping these rows - that
                // a bounce needs to see the entry it came from - no longer
                // applies, since a one-tap bounce does not draw the panel
                // at all any more. This is what replaces it.)
                color: index < root.highlightIndex ? "#80ffffff" : "white"

                // Plain "app — title" text list for now - the final
                // product is meant to add an app icon (and possibly the
                // app's display name rather than its resourceClass), per
                // the original design discussion; left as the simplest
                // thing that can show real content first.
                text: model.app + " — " + model.title
            }
        }
    }

    Timer {
        interval: 80
        running: true
        repeat: true
        onTriggered: poll.call()
    }

    KWinComponents.DBusCall {
        id: poll
        service: "com.backnav.Navigator"
        path: "/com/backnav/Navigator"
        dbusInterface: "com.backnav.Navigator"
        method: "GetPeekState"
        onFinished: function(returnValue) {
            applyState(JSON.parse(returnValue[0]));
        }
        // A failed call (daemon not running, D-Bus hiccup, ...) just
        // means the next tick tries again - same as the overlay simply
        // not being available, no different than backnav.service being
        // down for plain back()/forward() already.
    }

    // Keeps the panel up briefly after the gesture ends. Without this it
    // is on screen only while the key is physically down - measured at
    // 160-220ms per tap - which reads as a flicker rather than a preview,
    // and makes rapid taps strobe. Handled here rather than in the daemon
    // deliberately: how long a hint lingers is a presentation concern, and
    // GetPeekState() stays a truthful report of the live gesture state.
    Timer {
        id: dwell
        interval: 700
        onTriggered: {
            root.showing = false;
            root.contentKey = "";
            entries.clear();
            root.highlightIndex = -1;
        }
    }

    function applyState(state) {
        if (state.active) {
            dwell.stop();

            // Rebuild only when the rows actually differ, so a steady
            // stream of identical poll results costs nothing and the
            // ListView is not thrashed 12x/sec.
            const key = JSON.stringify(state.entries);

            if (key !== root.contentKey) {
                root.contentKey = key;
                entries.clear();

                for (let i = 0; i < state.entries.length; i++) {
                    entries.append(state.entries[i]);
                }
            }

            // Always applied, model rebuild or not: within one gesture the
            // rows hold still and this is the only thing that changes.
            root.highlightIndex = state.highlightIndex;

            // An exhausted history reports active with zero entries; showing
            // an empty panel would be worse than showing nothing.
            root.showing = entries.count > 0;
        } else if (root.showing && !dwell.running) {
            // Gesture just ended - leave the last rendered contents on
            // screen until the timer fires so the user can still read
            // where they landed.
            dwell.restart();
        }

        if (state.activateWindowId) {
            activateWindow(state.activateWindowId);
        }
    }

    // Mirrors activateWindow() in backnav-kwin/contents/code/main.js -
    // duplicated rather than shared, since this is a separate script
    // package with no access to the other one's JS state. Not yet
    // confirmed live that QML's Workspace.stackingOrder window objects
    // expose the same internalId property the plain JS scripting API's
    // workspace.stackingOrder does (both wrap the same underlying KWin
    // Window class, so they should, but this specifically needs a real
    // end-to-end test - see the overlay design notes).
    function activateWindow(windowId) {
        const windows = KWinComponents.Workspace.stackingOrder;

        for (let i = 0; i < windows.length; i++) {
            if (windows[i].internalId.toString() === windowId) {
                KWinComponents.Workspace.activeWindow = windows[i];
                return;
            }
        }
    }
}
