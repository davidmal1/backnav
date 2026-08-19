"""
A missing TLS certificate costs one feature, not the whole daemon.

certs/ is gitignored, correctly - it holds a private key - so a fresh
clone has no certificate at all. load_cert_chain used to be
unconditional, which meant a new user got FileNotFoundError and no daemon
whatsoever: no back/forward, no overlay, nothing, on a machine whose
owner may never install the one extension that needs TLS.

The wss:// listener on 8766 exists solely for Thunderbird, whose
HTTPS-Only Mode rewrites ws:// to wss:// on the same port with no
fallback. Everything else speaks plain ws:// on 8765 and does not care.

Exercises _tls_listener directly rather than run(), which would bind real
sockets. What matters is the decision, not the serving.
"""

import io
import os
import ssl
import tempfile
from contextlib import redirect_stdout
from unittest import mock

from core import websocket_server


def listener_with(cert_dir):
    """_tls_listener with certs/ pointed at cert_dir, and its output."""
    buffer = io.StringIO()

    # The module derives certs/ from its own __file__, so the directory is
    # redirected rather than the call rewritten.
    fake_core = os.path.join(cert_dir, "core", "websocket_server.py")

    with mock.patch.object(websocket_server, "__file__", fake_core):
        with redirect_stdout(buffer):
            result = websocket_server._tls_listener(handler=object())

    return result, buffer.getvalue()


# ---- no certificate at all: the fresh-clone case ---------------------

empty = tempfile.mkdtemp(prefix="backnav-nocerts-")
result, noise = listener_with(empty)

assert result is None, "a missing certificate must not produce a listener"

# And it must SAY so. Silently dropping a feature is how someone spends an
# evening wondering why Thunderbird will not connect.
assert "8766" in noise, noise
assert "certificate" in noise.lower(), noise
assert "README" in noise, noise

# The message has to make clear the rest still works, or the reasonable
# reading of any error at startup is "this is broken".
assert "unaffected" in noise.lower(), noise

# ---- a file that exists but is not a certificate ---------------------

# Half-written, truncated, or a key pasted where the cert belongs. This
# raises SSLError rather than OSError, which is why both are caught.
broken = tempfile.mkdtemp(prefix="backnav-badcerts-")
os.makedirs(os.path.join(broken, "certs"), exist_ok=True)

for name in ("cert.pem", "key.pem"):
    with open(os.path.join(broken, "certs", name), "w") as handle:
        handle.write("this is not a certificate\n")

result, noise = listener_with(broken)

assert result is None, "an unusable certificate must not produce a listener"
assert "8766" in noise, noise

# ---- a real certificate still works ----------------------------------

# The guard must not have made TLS unreachable - a daemon that silently
# never serves wss would pass every assertion above.
good = tempfile.mkdtemp(prefix="backnav-goodcerts-")
os.makedirs(os.path.join(good, "certs"), exist_ok=True)

import subprocess

subprocess.run(
    ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
     "-keyout", os.path.join(good, "certs", "key.pem"),
     "-out", os.path.join(good, "certs", "cert.pem"),
     "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
    capture_output=True, check=True,
)

# serve() wants a running event loop, and standing one up here would test
# websockets rather than this decision. Patched so the assertion is about
# what _tls_listener CHOOSES to do, which is the whole subject.
with mock.patch("websockets.server.serve") as fake_serve:
    fake_serve.return_value = "a-listener"
    result, noise = listener_with(good)

assert result == "a-listener", "a valid certificate produced no listener"
assert noise == "", f"a working certificate complained: {noise!r}"

# And it is a TLS listener on the right port, not a second plain one.
args, kwargs = fake_serve.call_args
assert 8766 in args, args
assert isinstance(kwargs.get("ssl"), ssl.SSLContext), kwargs

print("OK")
