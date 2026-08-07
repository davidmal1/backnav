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

    socket.onclose = () => {
        setTimeout(connect, 1000);
    };

    socket.onmessage = async (message) => {
        const data = JSON.parse(message.data);

        if (data.event === "activate") {
            const tab = await chrome.tabs.update(data.tabId, { active: true });
            await chrome.windows.update(tab.windowId, { focused: true });
        }
    };
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
