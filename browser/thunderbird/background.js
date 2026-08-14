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

// Comfortably inside the ~30s idle timeout an MV3 event page gets, so a
// keepalive always lands before the page can be suspended.
//
// This build went without one until 2026-08-14, having been left out when
// the same fix landed for chromium and firefox. The symptom was a
// connection that reconciled correctly and then simply stopped: measured
// live at 31 seconds between "connected ... reports 3 live tabs" and
// "disconnected" in the daemon journal.
//
// Worth knowing why the existing scheduleReconnect() below could not save
// it, since on paper it should have. Suspension takes the page's timers
// with it, so the very setTimeout meant to reconnect dies alongside the
// thing it was going to revive. That is why the failure reads as silence
// rather than as flapping, and why it appeared to recover "on its own"
// whenever the user happened to touch Thunderbird - a tab event was the
// only thing waking the page back up.
const KEEPALIVE_MS = 20000;

let socket = null;
let keepaliveTimer = null;

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

// Every tab id currently open, sent on connect so the daemon can reconcile
// rather than trust that it received every closure.
//
// reportActiveTab() above covers a dropped tab_changed, because the next
// switch corrects it anyway. A dropped tab_closed has no such recovery -
// nothing ever mentions a closed tab again - so the entry sits in the
// switcher forever, pointing at a tab that cannot be activated. Closures
// while the daemon is down are lost exactly this way.
async function reportLiveTabs() {
    const tabs = await browser.tabs.query({});

    send({ event: "tabs_alive", ids: tabs.map((tab) => tab.id) });
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

    socket.addEventListener("open", reportLiveTabs);
    socket.addEventListener("open", reportActiveTab);
    socket.addEventListener("open", startKeepalive);
    socket.addEventListener("message", handleServerMessage);
    socket.addEventListener("close", stopKeepalive);
    socket.addEventListener("close", scheduleReconnect);
    socket.addEventListener("error", () => socket.close());
}

function scheduleReconnect() {
    setTimeout(connect, RECONNECT_DELAY_MS);
}

// Holds the event page open for as long as the socket is up.
//
// An open-but-silent WebSocket does not count as activity, so the page is
// suspended out from under a perfectly healthy connection. Sending
// something well inside the idle window is what actually keeps it alive.
// The message carries no state - being traffic is the entire point of it,
// and the daemon skips it explicitly (see websocket_server.py).
//
// send() already stamps instanceId onto everything it sends, so unlike the
// chromium and firefox versions this does not need to await getInstanceId()
// on every tick.
function startKeepalive() {
    stopKeepalive();

    keepaliveTimer = setInterval(async () => {
        // The extension-API call is the part that holds the page open. The
        // WebSocket send does a different job and is not redundant with it.
        //
        // Both halves measured 2026-08-14. With the send alone the page died
        // at exactly 30s despite this interval running at 20s, giving a
        // metronomic 30s-alive/30s-dead cycle in the daemon journal. With
        // this call added it held 307s untouched, and firefox/background.js
        // held 298s on the same change in the same window.
        //
        // "Untouched" is load-bearing in that sentence. An event page also
        // stays alive while it is RECEIVING events, so any use of the app
        // during a test keeps it up regardless and proves nothing. An
        // earlier run looked like a pass at 151s and had to be thrown out
        // for exactly that reason.
        //
        // The strategy was ported from chromium/background.js, where the
        // comment is explicit that CHROME resets the service-worker idle
        // timer on WebSocket activity. Gecko does not appear to: its event
        // page counts extension-API activity, and socket.send() is a DOM
        // call, not a browser.* one. getPlatformInfo() is the cheapest
        // browser.* call that needs no permission and has no side effects.
        //
        // The send stays because it is what the DAEMON sees - it is traffic
        // on the socket, which is how a half-open connection gets noticed,
        // and websocket_server.py already skips the event explicitly.
        await browser.runtime.getPlatformInfo();

        send({ event: "keepalive" });
    }, KEEPALIVE_MS);
}

function stopKeepalive() {
    if (keepaliveTimer !== null) {
        clearInterval(keepaliveTimer);
        keepaliveTimer = null;
    }
}

// The backstop for the case the keepalive cannot cover: a page that has
// ALREADY been suspended has no timers left to run, so neither the
// keepalive nor scheduleReconnect() can bring it back. An alarm is the one
// timer that outlives suspension - it wakes the page, which re-runs this
// file top to bottom and reconnects on its own.
//
// periodInMinutes is clamped to a 30s floor, so a minute is the practical
// worst-case reconnect delay.
browser.alarms.create("backnav-reconnect", { periodInMinutes: 1 });

browser.alarms.onAlarm.addListener(() => {
    // If the alarm is what respawned the page, the bottom of this file has
    // already reconnected. This covers the other case: the page is alive
    // but its socket has closed.
    if (!socket || socket.readyState === WebSocket.CLOSED) {
        connect();
    }
});

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
