import asyncio
import json

from core.events.browser_tab_changed import BrowserTabChanged
from core.events.browser_tab_closed import BrowserTabClosed

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
                connections[instance_id] = websocket

                if data["event"] == "tab_closed":
                    event_bus.publish(BrowserTabClosed(
                        connection_id=instance_id,
                        tab_id=data["id"],
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

    return handler


async def activate_tab(connection_id, tab_id):
    websocket = connections.get(connection_id)

    if websocket is None:
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
