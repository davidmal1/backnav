import asyncio
import json

from core.events.browser_disconnected import BrowserDisconnected
from core.events.browser_tab_changed import BrowserTabChanged
from core.events.browser_tab_closed import BrowserTabClosed
from core.events.browser_tabs_alive import BrowserTabsAlive

clients = set()

# instanceId (a UUID generated once per browser install and persisted in
# its extension storage - see browser/*/background.js) -> its live
# connection, so an activation request can be routed to the right
# extension. Keyed by that stable id rather than the ephemeral WebSocket
# object or the `browser` field's family name: MV3 service workers get
# unloaded after ~30s idle and reconnect with a brand new socket, and two
# windows of the same family - e.g. Vivaldi and Brave both reporting
# "chromium" - would otherwise collide and each pick up the other's tab.
connections = {}


def _make_handler(event_bus):
    async def handler(websocket):
        clients.add(websocket)
        instance_id = None

        try:
            async for message in websocket:
                data = json.loads(message)
                instance_id = data["instanceId"]

                # Logged on the transition only, not per message. An MV3
                # respawn arrives as a brand new socket under the same
                # instanceId, so this legitimately fires repeatedly over a
                # session - that pattern in the journal is exactly what
                # tells you a worker is being evicted and coming back.
                if connections.get(instance_id) is not websocket:
                    print(f"backnav: browser extension connected ({instance_id})", flush=True)

                connections[instance_id] = websocket

                # Carries no state - its only job is to be traffic, so
                # Chrome's service-worker idle timer keeps getting reset
                # (see the keepalive in chromium/background.js). Skipped
                # before the tab handling below, which would otherwise
                # KeyError on the fields a keepalive does not carry and
                # kill the connection outright.
                if data["event"] == "keepalive":
                    continue

                if data["event"] == "tab_closed":
                    event_bus.publish(BrowserTabClosed(
                        connection_id=instance_id,
                        tab_id=data["id"],
                    ))
                    continue

                # Sent once per connection, immediately on open. Logged
                # because it is low-volume (one line per reconnect) and
                # because a closure lost while the worker was respawning
                # is otherwise completely invisible - this is the line
                # that says how many entries the reconciliation retired.
                if data["event"] == "tabs_alive":
                    print(
                        f"backnav: {instance_id} reports {len(data['ids'])} live tabs",
                        flush=True,
                    )
                    event_bus.publish(BrowserTabsAlive(
                        connection_id=instance_id,
                        tab_ids=frozenset(data["ids"]),
                    ))
                    continue

                event_bus.publish(BrowserTabChanged(
                    browser=data["browser"],
                    connection_id=instance_id,
                    window_id=data["windowId"],
                    tab_id=data["id"],
                    title=data["title"],
                    url=data["url"],
                ))
        finally:
            clients.remove(websocket)

            # Only remove the mapping if it's still ours - a fast
            # reconnect under the same instanceId may already have
            # replaced it by the time this connection's close is handled.
            if instance_id is not None and connections.get(instance_id) is websocket:
                del connections[instance_id]
                print(f"backnav: browser extension disconnected ({instance_id})", flush=True)

                # Release what the engine learned about this connection.
                # Deliberately inside the "still ours" check: a fast
                # reconnect under the same instanceId has already replaced
                # the mapping, and telling the engine to forget a
                # connection that is currently live would unbind a working
                # browser.
                event_bus.publish(BrowserDisconnected(connection_id=instance_id))

    return handler


async def activate_tab(connection_id, tab_id):
    websocket = connections.get(connection_id)

    if websocket is None:
        # Loud, because the user-visible symptom is otherwise nothing at
        # all. Navigating onto a browser-tab entry whose extension has
        # gone away raises the owning window - which, when walking between
        # tabs of the SAME window, is already focused - so the tab simply
        # never switches and no error appears anywhere. Reported live
        # (2026-08-12) as "it doesn't activate the tab", and it took a
        # socket-level check to find that the extension was disconnected
        # rather than anything being wrong with navigation.
        print(
            f"backnav: cannot activate tab {tab_id} - no live connection for "
            f"{connection_id}; the browser extension is not connected "
            f"(known connections: {sorted(connections)})",
            flush=True,
        )
        return

    await websocket.send(json.dumps({
        "event": "activate",
        "tabId": tab_id,
    }))


async def run(event_bus):
    import os
    import ssl

    from websockets.server import serve

    handler = _make_handler(event_bus)

    # Plain WebSocket on 8765, unchanged - the chromium/firefox extensions
    # already connect to this over ws:// and Chrome-family browsers don't
    # have Firefox's per-host TLS-exception mechanism, so forcing TLS here
    # too would trade one connection problem for another with no benefit.
    plain_server = serve(handler, "127.0.0.1", 8765)

    # Separate TLS listener on 8766, for clients that enforce HTTPS-Only
    # Mode (Thunderbird does). Those clients silently rewrite ws:// to
    # wss:// on the SAME port before the request ever leaves the process -
    # there's no user-facing "continue anyway" fallback for a background
    # WebSocket the way there is for a page load, so pointing such a
    # client at 8765 just fails invisibly forever. Rather than trying to
    # defeat that rewrite, backnav's own Thunderbird extension connects to
    # this port directly as wss:// from the start, so nothing ever needs
    # rewriting. Requires accepting the self-signed cert once - see
    # browser/thunderbird/readme.md.
    cert_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "certs")
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_context.load_cert_chain(
        os.path.join(cert_dir, "cert.pem"),
        os.path.join(cert_dir, "key.pem"),
    )
    tls_server = serve(handler, "127.0.0.1", 8766, ssl=ssl_context)

    async with plain_server, tls_server:
        print("WebSocket listening on :8765 (ws) and :8766 (wss)")
        await asyncio.Future()
