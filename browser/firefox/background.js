let socket = null;
let instanceId = null;
let keepaliveTimer = null;

// Comfortably inside Chrome's 30s service-worker idle timeout, so a
// keepalive always lands before the worker can be evicted.
const KEEPALIVE_MS = 20000;

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
    socket.onopen = () => {
        reportLiveTabs();
        reportActiveTab();
        startKeepalive();
    };

    socket.onclose = () => {
        stopKeepalive();
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

// Keeps the service worker alive for as long as the socket is up.
//
// The alarm below can resurrect an evicted worker, but only on its own
// period, which left the extension connected for 30s and dead for the
// next 30s, forever - measured live in the daemon journal as a metronomic
// connect/disconnect every 30s. Chrome resets the worker's 30s idle timer
// on WebSocket ACTIVITY, and an open-but-silent socket is not activity,
// so the worker was still being evicted mid-cycle every time.
//
// Sending something well inside that window is what actually holds the
// worker open. The message carries no state; being traffic is the entire
// point of it, and the daemon skips it explicitly.
// The paragraph above is CHROME's rule, and this file does not run on
// Chrome. Gecko counts extension-API activity rather than socket traffic,
// which makes everything above true and yet insufficient here - so the tick
// makes a chrome.* call as well.
//
// Diagnosed on thunderbird/background.js, whose page died at exactly 30s
// with a 20s socket-only keepalive, then confirmed on this build directly
// (2026-08-14): 298s connected and untouched, against a 30s ceiling, in the
// same window Thunderbird held 307s.
//
// This build is the better half of that evidence. Thunderbird had 3 tabs
// and so almost no event traffic to keep its page alive by accident, while
// this one had 17 - two very different event rates behaving identically,
// which points at the mechanism rather than at circumstance.
//
// Note that getInstanceId() below is NOT a substitute. It hits
// chrome.storage exactly once and returns a cached value forever after, so
// every tick past the first makes no extension-API call whatsoever - which
// is precisely the shape of the bug.
function startKeepalive() {
    stopKeepalive();

    keepaliveTimer = setInterval(async () => {
        if (!socket || socket.readyState !== WebSocket.OPEN)
            return;

        // Cheapest chrome.* call that needs no permission and has no side
        // effects. Being an API call is the entire point of it.
        await chrome.runtime.getPlatformInfo();

        socket.send(JSON.stringify({
            event: "keepalive",
            instanceId: await getInstanceId()
        }));
    }, KEEPALIVE_MS);
}

function stopKeepalive() {
    if (keepaliveTimer !== null) {
        clearInterval(keepaliveTimer);
        keepaliveTimer = null;
    }
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
    }));
}

// Lets the daemon drop this tab from history's back/forward targets -
// re-activating a closed tab is a silent no-op that just makes navigation
// look stuck, so it needs to know to skip past it instead.
//
// Best-effort: if the socket is not up when a tab closes, this is simply
// lost. reportLiveTabs() below is what makes that survivable.
async function publishClosed(tabId) {
    if (!socket || socket.readyState !== WebSocket.OPEN)
        return;

    socket.send(JSON.stringify({
        event: "tab_closed",
        instanceId: await getInstanceId(),
        id: tabId
    }));
}

// Every tab id this browser currently has, sent on connect so the daemon
// can reconcile rather than trust that it received every closure.
//
// reportActiveTab() above covers a dropped tab_changed, because the next
// switch would correct it anyway. A dropped tab_closed has no such
// recovery - nothing ever mentions a closed tab again - so the entry sits
// in the switcher forever, pointing at a tab that cannot be activated.
// Observed live (2026-08-12) on the Chromium side, where an MV3 worker
// respawning on the onRemoved event guarantees the drop; here the window
// is smaller (a persistent background page keeps the socket up) but
// closures during daemon downtime are lost exactly the same way.
async function reportLiveTabs() {
    const tabs = await chrome.tabs.query({});

    if (!socket || socket.readyState !== WebSocket.OPEN)
        return;

    socket.send(JSON.stringify({
        event: "tabs_alive",
        instanceId: await getInstanceId(),
        ids: tabs.map((tab) => tab.id)
    }));
}

connect();

// The backstop for when the worker gets evicted anyway.
//
// startKeepalive() above is what normally prevents eviction; this is the
// recovery path if it ever fails - the daemon being down for a while, for
// instance, since there is no socket to keep alive then and the retry
// setTimeout dies with the worker.
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
    // tab.active is the whole point of this guard, and it was missing.
    //
    // Without it every tab that finishes loading reports itself as a
    // navigation, including ones the user has never looked at. Session
    // restore is where that becomes obvious: a browser reopening thirty
    // tabs fires this thirty times, and because the browser window holds
    // focus throughout, the daemon records every one as somewhere you
    // had been. Reported 2026-08-19 with a switcher full of pages the
    // user had never visited.
    //
    // The listener still earns its place for the ACTIVE tab. Sites that
    // navigate without a tab switch - a single-page app changing its
    // title - produce no onActivated, so this is the only thing that
    // notices the current tab has become a different page.
    //
    // thunderbird/background.js had this right from the start.
    if (tab.active && changeInfo.status === "complete")
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
