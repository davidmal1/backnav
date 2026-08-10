//
// BackNav Thunderbird Extension
//
// Reports Thunderbird tab activity to the BackNav daemon over the exact
// same WebSocket protocol backnav-engine's websocket_server.py already
// implements for browser extensions (see BrowserTabChanged/BrowserTabClosed
// there) - Thunderbird's tabs API hands back real, stable tab ids just like
// a browser's does, so this reuses that protocol wholesale rather than
// inventing a new one. The engine treats "thunderbird" as just another
// entry in TAB_EXTENSION_APPS (core/navigation_engine.py).
//

// wss:// (not ws://) and its own port (8766, not the browser extensions'
// 8765) deliberately - see websocket_server.py's `run()`. Thunderbird's
// HTTPS-Only Mode silently rewrites a plain ws:// request to wss:// on
// the same port with no user-facing fallback, so this connects secure
// from the start instead of ever tripping that rewrite. Requires
// accepting the daemon's self-signed cert once - see readme.md.
const WS_URL = "wss://127.0.0.1:8766";
const RECONNECT_DELAY_MS = 2000;

let socket = null;

// A UUID generated once and persisted in extension storage, not tied to
// the WebSocket connection itself - the daemon keys its `connections` map
// by this id (see websocket_server.py) specifically so a dropped/reconnected
// socket (or an ephemeral background context getting torn down and
// restarted) still resolves to the same logical Thunderbird instance
// afterward, rather than orphaning whatever history entries were recorded
// under the old connection.
let instanceId = null;

async function getInstanceId() {
    const stored = await browser.storage.local.get("instanceId");

    if (stored.instanceId) {
        return stored.instanceId;
    }

    const id = crypto.randomUUID();
    await browser.storage.local.set({ instanceId: id });
    return id;
}

function send(message) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
        // Nothing to queue this against - the daemon has no notion of
        // replaying stale tab state later, so a dropped event here is the
        // same as one that happened while the daemon simply wasn't running.
        return;
    }

    socket.send(JSON.stringify({ instanceId, ...message }));
}

function reportTab(tab) {
    send({
        event: "tab_changed",
        browser: "thunderbird",
        windowId: tab.windowId,
        id: tab.id,
        title: tab.title || "",
        url: tab.url || "",
    });
}

async function reportActiveTab() {
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });

    if (tab) {
        reportTab(tab);
    }
}

function handleServerMessage(event) {
    let data;

    try {
        data = JSON.parse(event.data);
    } catch (e) {
        return;
    }

    if (data.event !== "activate" || typeof data.tabId !== "number") {
        return;
    }

    // Re-activating a tab that's since been closed is a silent no-op here,
    // same as re-raising a closed window is on the KWin side - nothing
    // sensible to do about it, and the daemon's own dead-tab tracking is
    // what's supposed to keep this from being asked for in the first place.
    browser.tabs.update(data.tabId, { active: true }).catch(() => {});
}

function connect() {
    socket = new WebSocket(WS_URL);

    socket.addEventListener("open", reportActiveTab);
    socket.addEventListener("message", handleServerMessage);
    socket.addEventListener("close", scheduleReconnect);
    socket.addEventListener("error", () => socket.close());
}

function scheduleReconnect() {
    setTimeout(connect, RECONNECT_DELAY_MS);
}

browser.tabs.onActivated.addListener(async ({ tabId }) => {
    try {
        reportTab(await browser.tabs.get(tabId));
    } catch (e) {
        // Tab vanished between the event firing and this lookup.
    }
});

// Catches switching folders/messages within Thunderbird's own 3-pane mail
// tab, which doesn't fire onActivated at all since the tab itself never
// changes - the closest thing here to the KWin script's caption-watching
// hook for Kate/Konsole, except this is a real WebExtension event instead
// of polling a window title. Only the currently-active tab's updates
// matter; a background tab's title changing isn't a navigation.
browser.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    if (tab.active && (changeInfo.title !== undefined || changeInfo.url !== undefined)) {
        reportTab(tab);
    }
});

browser.tabs.onRemoved.addListener((tabId) => {
    send({ event: "tab_closed", id: tabId });
});

getInstanceId().then((id) => {
    instanceId = id;
    connect();
});
