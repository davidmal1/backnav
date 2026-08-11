let socket = null;
let instanceId = null;

// A stable id for this browser install, independent of any one WebSocket
// connection. MV3 service workers get unloaded after ~30s idle and respawn
// on the next event, opening a brand new socket each time - if the daemon
// keyed activation/history off the connection itself, every history entry
// recorded before the most recent respawn would silently stop being able
// to activate its tab. Persisting this in storage means it survives
// respawns (and browser restarts), while still being unique per browser
// instance so e.g. Vivaldi and Brave - both reporting browser: "chromium" -
// never collide.
async function getInstanceId() {
    if (instanceId)
        return instanceId;

    const stored = await chrome.storage.local.get("instanceId");

    if (stored.instanceId) {
        instanceId = stored.instanceId;
    } else {
        instanceId = crypto.randomUUID();
        await chrome.storage.local.set({ instanceId });
    }

    return instanceId;
}

function connect() {
    socket = new WebSocket("ws://127.0.0.1:8765");

    // Whatever state the daemon missed while we were away, the only part
    // of it that still matters is which tab is active NOW - so say that
    // as soon as the socket is usable.
    //
    // This is what stops the wake-up event being lost. The service worker
    // respawns on a tab event and runs connect() at top level, so the very
    // event that woke it reaches publish() while the socket is still
    // CONNECTING and gets dropped - silently losing the first tab switch
    // after every respawn. Reporting on open covers that case and any
    // other divergence during the outage, without queueing: the daemon has
    // no notion of replaying stale tab state later, so a backlog of old
    // events would be recorded as if they had all just happened.
    // (Same approach as thunderbird/background.js, which had it first.)
    socket.onopen = reportActiveTab;

    socket.onclose = () => {
        setTimeout(connect, 1000);
    };

    // An error does not always produce a close, and without one the
    // reconnect above is never scheduled and the socket stays wedged.
    socket.onerror = () => {
        socket.close();
    };

    socket.onmessage = async (message) => {
        const data = JSON.parse(message.data);

        if (data.event === "activate") {
            const tab = await chrome.tabs.update(data.tabId, { active: true });
            await chrome.windows.update(tab.windowId, { focused: true });
        }
    };
}

async function reportActiveTab() {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });

    if (tab)
        publish(tab);
}

async function publish(tab) {
    if (!socket || socket.readyState !== WebSocket.OPEN)
        return;

    socket.send(JSON.stringify({
        event: "tab",
        browser: "firefox",
        instanceId: await getInstanceId(),
        id: tab.id,
        windowId: tab.windowId,
        title: tab.title,
        url: tab.url
    }));
}

// Lets the daemon drop this tab from history's back/forward targets -
// re-activating a closed tab is a silent no-op that just makes navigation
// look stuck, so it needs to know to skip past it instead.
async function publishClosed(tabId) {
    if (!socket || socket.readyState !== WebSocket.OPEN)
        return;

    socket.send(JSON.stringify({
        event: "tab_closed",
        instanceId: await getInstanceId(),
        id: tabId
    }));
}

connect();

// The reconnect that survives the worker being evicted.
//
// setTimeout(connect, 1000) above only retries for as long as this
// service worker lives, and a pending timer does NOT keep it alive: MV3
// evicts an idle worker after ~30s, and while the daemon is down there is
// no WebSocket traffic to reset that idle timer. So a daemon restart
// during idle killed the retry loop along with the worker, and nothing
// reconnected until the user happened to switch a tab - observed live as
// BackNav silently failing to activate any browser tab, with no error
// anywhere, because activate_tab() on the daemon side just finds no
// connection and returns.
//
// An alarm is the one timer that outlives eviction: it wakes the worker,
// which re-runs this file top to bottom and so reconnects by itself.
// Chrome clamps periodInMinutes to a 30s floor, so 1 minute is the
// practical worst-case reconnect delay.
chrome.alarms.create("backnav-reconnect", { periodInMinutes: 1 });

chrome.alarms.onAlarm.addListener(() => {
    // Top-level connect() has already run if the worker was respawned by
    // this alarm; this covers the other case, where the worker is alive
    // but its socket has closed.
    if (!socket || socket.readyState === WebSocket.CLOSED)
        connect();
});

chrome.tabs.onActivated.addListener(async (info) => {
    publish(await chrome.tabs.get(info.tabId));
});

chrome.tabs.onRemoved.addListener((tabId) => {
    publishClosed(tabId);
});

chrome.tabs.onUpdated.addListener((id, changeInfo, tab) => {
    if (changeInfo.status === "complete")
        publish(tab);
});

chrome.windows.onFocusChanged.addListener(async (windowId) => {
    if (windowId === chrome.windows.WINDOW_ID_NONE)
        return;

    const tabs = await chrome.tabs.query({
        active: true,
        windowId
    });

    if (tabs.length)
        publish(tabs[0]);
});
