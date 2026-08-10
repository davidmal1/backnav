/*
    BackNav's hold+repeat-taps history preview overlay.

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
    those, unchanged, so a quick tap-and-release keeps working exactly
    as before with no overlay flicker. Instead, this purely polls and
    renders: see backnav-engine/core/overlay_controller.py's docstring
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

    color: "transparent"
    flags: Qt.BypassWindowManagerHint | Qt.FramelessWindowHint
    visible: entries.count > 0

    width: rowWidth + 24
    height: Math.min(entries.count, 8) * rowHeight + 24
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

    ListView {
        id: listView
        anchors.fill: parent
        anchors.margins: 12
        model: entries
        interactive: false

        delegate: Rectangle {
            width: listView.width
            height: root.rowHeight
            radius: 4
            color: index === root.highlightIndex ? "#4080c0ff" : "transparent"

            Text {
                anchors.fill: parent
                anchors.leftMargin: 8
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideRight
                color: "white"
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

    function applyState(state) {
        entries.clear();
        root.highlightIndex = -1;

        if (state.active) {
            for (let i = 0; i < state.entries.length; i++) {
                entries.append(state.entries[i]);
            }
            root.highlightIndex = state.highlightIndex;
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
