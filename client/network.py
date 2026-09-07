import json
import queue
import random
import socket
import ssl
import struct
import threading

from websockets.sync.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidURI, InvalidHandshake

_DNS_CACHE = {}


def _resolve_via_public_dns(hostname, dns_server="8.8.8.8"):
    if hostname in _DNS_CACHE:
        return _DNS_CACHE[hostname]
    qid = random.randint(0, 65535)
    header = struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0)
    question = b""
    for part in hostname.split("."):
        question += bytes([len(part)]) + part.encode()
    question += b"\x00" + struct.pack(">HH", 1, 1)  # type A, class IN
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(4)
        s.sendto(header + question, (dns_server, 53))
        data, _ = s.recvfrom(512)
    ancount = struct.unpack(">H", data[6:8])[0]
    offset = len(header) + len(question)
    for _ in range(ancount):
        if data[offset] & 0xC0 == 0xC0:
            offset += 2
        rtype, _, _, rdlength = struct.unpack(">HHIH", data[offset:offset + 10])
        offset += 10
        if rtype == 1 and rdlength == 4:
            ip = ".".join(str(b) for b in data[offset:offset + 4])
            _DNS_CACHE[hostname] = ip
            return ip
        offset += rdlength
    raise socket.gaierror(f"no A record for {hostname} via {dns_server}")


def humanize_connect_error(e):
    if isinstance(e, InvalidURI):
        return "Invalid server address — must start with ws:// or wss://"
    if isinstance(e, socket.gaierror):
        return "Server not found — check the address for typos, or your internet connection."
    if isinstance(e, TimeoutError) or isinstance(e, socket.timeout):
        return "Connection timed out — server is unreachable or not responding."
    if isinstance(e, ConnectionRefusedError):
        return "Server refused the connection — it may be offline or the port is wrong."
    if isinstance(e, ssl.SSLCertVerificationError):
        return "TLS certificate error — the server address may be wrong."
    if isinstance(e, InvalidHandshake):
        return "Server didn't respond like a WebSocket relay — check the address."
    if isinstance(e, OSError) and getattr(e, "errno", None) in (61, 111):
        return "Server refused the connection — it may be offline."
    if isinstance(e, OSError) and getattr(e, "errno", None) == 8:
        return "Server not found — check the address for typos, or your internet connection."
    return f"Couldn't reach server ({e.__class__.__name__}: {e})"


def install_dns_fallback():
    real_getaddrinfo = socket.getaddrinfo

    def patched(host, *args, **kwargs):
        try:
            return real_getaddrinfo(host, *args, **kwargs)
        except socket.gaierror:
            ip = _resolve_via_public_dns(host)
            return real_getaddrinfo(ip, *args, **kwargs)

    socket.getaddrinfo = patched


class Connection:
    """Connects and runs a websocket on a background thread, exposes an
    incoming-message queue safe to drain from the pygame main loop. The
    connect handshake (DNS + TLS) is also off the main thread so the UI
    never blocks waiting on the network."""

    def __init__(self):
        self.ws = None
        self.incoming = queue.Queue()
        self._thread = None

    def connect(self, addr, first_message):
        self._thread = threading.Thread(
            target=self._connect_and_read, args=(addr, first_message), daemon=True
        )
        self._thread.start()

    def _connect_and_read(self, addr, first_message):
        try:
            self.ws = ws_connect(addr, open_timeout=6)
            self.send(first_message)
        except Exception as e:
            self.incoming.put({"type": "connect_error", "error": humanize_connect_error(e)})
            return
        try:
            for raw in self.ws:
                self.incoming.put(json.loads(raw))
        except ConnectionClosed as e:
            self.incoming.put({"type": "disconnected", "error": f"closed: {e.code} {e.reason}"})
        except Exception as e:
            self.incoming.put({"type": "disconnected", "error": str(e)})
        else:
            self.incoming.put({"type": "disconnected", "error": "closed"})

    def send(self, d):
        self.ws.send(json.dumps(d))

    def close(self):
        """Never blocks the caller: the actual close handshake (which can
        wait on a server ack) runs on a throwaway daemon thread."""
        ws, self.ws = self.ws, None
        if ws:
            threading.Thread(target=self._close_quietly, args=(ws,), daemon=True).start()

    @staticmethod
    def _close_quietly(ws):
        try:
            ws.close()
        except Exception:
            pass
