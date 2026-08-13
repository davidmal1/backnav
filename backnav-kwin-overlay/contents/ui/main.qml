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
import org.kde.kirigami as Kirigami

Window {
    id: root

    // One knob for the whole panel. Every dimension below is derived
    // from it, so resizing is a single edit rather than eight numbers
    // that have to be kept consistent with each other - and the ratios
    // between text, icon and padding hold at any setting, which is what
    // stops a bigger panel from just looking like a stretched one.
    //
    // The base figures are the sizes that were on screen at ui: 1.0.
    readonly property real ui: 1.5

    readonly property int rowHeight: Math.round(36 * ui)

    // Width does NOT keep the proportions the rest of the panel does.
    // Scaling it with everything else gave an 816px window that read as
    // dominating the screen (2026-08-13) - a switcher is glanced at, not
    // worked in. Titles elide rather than wrap, so the cost of a
    // narrower panel is a few truncated tails, and the icon plus the
    // start of the title is what actually identifies a row.
    readonly property int rowWidth: Math.round(390 * ui)
    readonly property int iconSize: Math.round(24 * ui)
    readonly property int fontSize: Math.round(13 * ui)

    // Gap between the panel edge and the rows, and between a row's own
    // contents. Named rather than repeated as bare 12s and 8s, since the
    // window geometry below has to agree with them exactly or the last
    // row is clipped.
    readonly property int panelPadding: Math.round(12 * ui)
    readonly property int rowSpacing: Math.round(8 * ui)
    readonly property int panelRadius: Math.round(8 * ui)
    readonly property int rowRadius: Math.round(4 * ui)

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
    // Whether the daemon has the CHOOSER open (a held shortcut) rather
    // than a tap-driven walk. Only the chooser takes focus.
    property bool chooser: false

    // Qt.Popup is what makes keys possible, and it is applied only in
    // chooser mode.
    //
    // Measured: with Qt.BypassWindowManagerHint the panel is transparent
    // to the keyboard - hover and tap arrive, no key ever does, and
    // window.active is never true. KWin will not focus a window that asks
    // not to be managed, and no focus means no keys. Qt.Popup plus
    // requestActivate() produced window.active=true and a real
    // Qt.Key_Down.
    //
    // It must NOT be applied to a tap-driven walk. That mode raises the
    // target window on every step, the target takes focus, the panel
    // loses it, and a Qt.Popup that loses focus hides itself - observed
    // live as the panel "kept disappearing or was not visible". The
    // chooser can hold focus precisely because it raises nothing until
    // Enter.
    flags: chooser
        ? (Qt.Popup | Qt.FramelessWindowHint)
        : (Qt.BypassWindowManagerHint | Qt.FramelessWindowHint)

    visible: showing

    // Flags make focus possible; they do not ask for it. KWin's own
    // tabbox skips this only because its C++ side grabs the keyboard.
    onChooserChanged: if (chooser && showing) requestActivate()
    onShowingChanged: if (chooser && showing) requestActivate()

    width: rowWidth + 2 * panelPadding
    height: Math.max(Math.min(entries.count, 8), 1) * rowHeight + 2 * panelPadding
    x: Screen.virtualX + (Screen.width - width) / 2
    y: Screen.virtualY + (Screen.height - height) / 2

    ListModel {
        id: entries
    }

    Rectangle {
        anchors.fill: parent
        color: "#e6202020"
        radius: root.panelRadius
        border.color: "#40ffffff"
        border.width: 1
    }

    // There is deliberately no onActiveChanged handler here. It fires on
    // GAINING focus and has never once been observed firing with false,
    // so focus loss is sampled in the poll Timer below instead - see the
    // comment there.

    ListView {
        id: listView
        anchors.fill: parent
        anchors.margins: root.panelPadding
        model: entries
        interactive: false

        focus: true

        // Up/Down/Enter/Escape exist only here. The daemon cannot see
        // them - KGlobalAccel reports just the two BackNav shortcuts - so
        // this window, which has keyboard focus in chooser mode, reads
        // them and calls the daemon.
        //
        // The highlight is still driven entirely by the daemon's reply,
        // not moved locally: ListView's built-in key navigation moves its
        // own currentIndex, which this delegate does not render, so
        // handling these here and letting the next poll bring back the
        // new highlightIndex keeps one source of truth.
        Keys.onPressed: function(event) {
            if (!root.chooser)
                return;

            if (event.key === Qt.Key_Down) {
                root.callChooser(moveCall, "back");
            } else if (event.key === Qt.Key_Up) {
                root.callChooser(moveCall, "forward");
            } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                root.callChooser(confirmCall, null);
            } else if (event.key === Qt.Key_Escape) {
                root.callChooser(cancelCall, null);
            } else {
                return;
            }

            // Only reached for keys actually handled above, so anything
            // else still falls through to whatever would normally get it.
            event.accepted = true;
        }

        delegate: Rectangle {
            id: entryRow

            width: listView.width
            height: root.rowHeight
            radius: root.rowRadius
            color: index === root.highlightIndex ? "#4080c0ff" : "transparent"

            // Pointer events reach these rows in BOTH flag modes, since
            // pointer input routes by position and is unaffected by the
            // panel being unmanaged. They are acted on only in chooser
            // mode all the same: a tap-driven walk is on screen for a few
            // hundred ms and raises a window under the cursor as it goes,
            // so clicking it would be a race against the panel vanishing.
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton

                // Arming on MOVEMENT, not on entry. The panel opens in the
                // centre of the screen, which is often exactly where the
                // pointer already is - and onEntered fires for a row that
                // merely appeared underneath a stationary cursor. Without
                // this the highlight would jump to whatever the pointer
                // happened to be resting on the instant the chooser
                // opened, stealing it from the keyboard before the user
                // had touched the mouse.
                onPositionChanged: {
                    root.mouseArmed = true;
                    root.hoverRow(index);
                }

                onEntered: root.hoverRow(index)

                onClicked: if (root.chooser) root.callChooser(confirmCall, null)
            }

            Row {
                anchors.fill: parent
                anchors.leftMargin: root.rowSpacing
                anchors.rightMargin: root.rowSpacing
                spacing: root.rowSpacing

                // KWin's own icon for the window, not one resolved from
                // the resource class. Kirigami.Icon takes a QIcon
                // directly, which is what Workspace.stackingOrder hands
                // over - verified by probe (2026-08-13): every window
                // exposed one and the assignment came back Ready/valid.
                Kirigami.Icon {
                    width: root.iconSize
                    height: root.iconSize
                    anchors.verticalCenter: parent.verticalCenter
                    source: root.iconFor(model.windowId)
                    opacity: index < root.highlightIndex ? 0.5 : 1.0
                }

                Text {
                    width: entryRow.width - root.iconSize - 3 * root.rowSpacing
                    anchors.verticalCenter: parent.verticalCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                    font.pixelSize: root.fontSize

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

                    // Title only. The app used to be spelled out here as
                    // "app — title", but the app field is a resourceClass and
                    // reads badly: "org.kde.dolphin",
                    // "qpdfview.local.qpdfview", "firefox_firefox". The icon
                    // to the left now carries that, and carries it better.
                    text: model.title
                }
            }
        }
    }

    // Whether the panel has actually held keyboard focus during THIS
    // chooser. Latched, and cleared with the chooser itself in
    // closePanel(), so "never got focus yet" cannot be mistaken for
    // "lost focus" - see the poll Timer.
    property bool hadFocus: false

    // Whether the pointer has actually MOVED during this chooser. Until
    // it has, hover is ignored - see the MouseArea in the delegate.
    // Cleared in closePanel() with everything else, so each chooser
    // starts out keyboard-only again.
    property bool mouseArmed: false

    // Hover moves the highlight, which the daemon owns - so this asks,
    // exactly as the keys do, and lets the next poll bring the new
    // highlightIndex back. Skipping the call when the row is already
    // highlighted stops a pointer resting on one row from generating
    // D-Bus traffic on every jitter event.
    function hoverRow(index) {
        if (!root.chooser || !root.mouseArmed)
            return;

        if (index === root.highlightIndex)
            return;

        root.highlightArg = String(index);
        setHighlightCall.call();
    }

    // The KWin window's own icon, found the same way activateWindow()
    // finds the window itself. Falls back to a generic theme name for a
    // window that has gone away since the daemon built the list -
    // Kirigami.Icon accepts either a QIcon or an icon name, so both
    // forms are valid here.
    function iconFor(windowId) {
        const windows = KWinComponents.Workspace.stackingOrder;

        for (let i = 0; i < windows.length; i++) {
            if (windows[i].internalId.toString() === windowId)
                return windows[i].icon;
        }

        return "application-x-executable";
    }

    Timer {
        interval: 80
        running: true
        repeat: true
        onTriggered: {
            poll.call();

            // root.active is SAMPLED here rather than watched via
            // onActiveChanged, which has never once fired with false -
            // the panel reports gaining focus and never losing it.
            // Measured (2026-08-12): the signal is what is missing, not
            // the state. The property itself goes false perfectly
            // reliably, so polling sees the loss that the signal never
            // announces.
            if (root.chooser && root.active)
                root.hadFocus = true;

            // Losing keyboard focus ends the chooser. KWin's own focus
            // stream cannot see this: the panel is not a managed window,
            // so clicking back onto the window KWin already considers
            // active produces no windowActivated at all and the daemon
            // hears nothing. Measured live (2026-08-12) - the chooser sat
            // open for 90 seconds while the user typed into another
            // window, with not one focus event logged.
            //
            // Dismiss, not cancel: cancel RAISES the window you started
            // from, which would drag you off whatever you just clicked.
            //
            // Gated on having HELD focus first, not merely on not having
            // it. requestActivate() is asynchronous, so for the first
            // poll or two after the chooser opens the panel legitimately
            // has chooser=true and active=false - acting on that would
            // dismiss the chooser roughly 80ms after it appeared, every
            // single time.
            if (root.chooser && root.hadFocus && !root.active)
                root.callChooser(dismissCall, null);
        }
    }

    // ---- Chooser calls -------------------------------------------------
    //
    // Separate DBusCall objects per method rather than one reconfigured
    // in place: `method` is a declared property and rewriting it per call
    // races against the in-flight call's own reply.
    property string chooserArg: ""
    property string highlightArg: "0"

    function callChooser(call, arg) {
        if (arg !== null)
            root.chooserArg = arg;

        call.call();
    }

    KWinComponents.DBusCall {
        id: moveCall
        service: "com.backnav.Navigator"
        path: "/com/backnav/Navigator"
        dbusInterface: "com.backnav.Navigator"
        method: "MoveHighlight"
        arguments: [root.chooserArg]
        onFinished: function(returnValue) {}
    }

    // The mouse's counterpart to moveCall: an absolute row rather than a
    // direction. Sent as a string because every call shape proven to
    // work from DBusCall here passes strings - see SetHighlight in
    // navigator_service.py.
    KWinComponents.DBusCall {
        id: setHighlightCall
        service: "com.backnav.Navigator"
        path: "/com/backnav/Navigator"
        dbusInterface: "com.backnav.Navigator"
        method: "SetHighlight"
        arguments: [root.highlightArg]
        onFinished: function(returnValue) {}
    }

    KWinComponents.DBusCall {
        id: confirmCall
        service: "com.backnav.Navigator"
        path: "/com/backnav/Navigator"
        dbusInterface: "com.backnav.Navigator"
        method: "ConfirmSelection"
        onFinished: function(returnValue) {}
    }

    KWinComponents.DBusCall {
        id: cancelCall
        service: "com.backnav.Navigator"
        path: "/com/backnav/Navigator"
        dbusInterface: "com.backnav.Navigator"
        method: "CancelSelection"
        onFinished: function(returnValue) {}
    }

    // Close the chooser without raising anything - see the poll Timer.
    KWinComponents.DBusCall {
        id: dismissCall
        service: "com.backnav.Navigator"
        path: "/com/backnav/Navigator"
        dbusInterface: "com.backnav.Navigator"
        method: "DismissSelection"
        onFinished: function(returnValue) {}
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
        onTriggered: root.closePanel()
    }

    // Deliberately not named hide(): Window already has one, and it sets
    // visible directly, which would fight the `visible: showing` binding
    // rather than replace it.
    function closePanel() {
        dwell.stop();

        root.showing = false;
        root.chooser = false;
        root.hadFocus = false;
        root.mouseArmed = false;
        root.contentKey = "";
        entries.clear();
        root.highlightIndex = -1;
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
            root.chooser = state.chooser === true;

            // An exhausted history reports active with zero entries; showing
            // an empty panel would be worse than showing nothing.
            root.showing = entries.count > 0;
        } else if (root.chooser) {
            // The chooser never lingers. It ends only on an explicit Enter
            // or Escape, so by the time the daemon reports inactive the
            // decision is already made and acted on - holding a stale list
            // up for another 700ms would just be in the way, and Escape in
            // particular should feel like the panel was never there.
            //
            // It also must not linger: this window has keyboard focus in
            // chooser mode, so a lingering panel is a window still eating
            // the user's keystrokes after they have moved on.
            closePanel();
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
