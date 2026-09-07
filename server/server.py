import asyncio
import json
import logging
import random
import string
import time

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("relay")

import os
HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", 8080))

# --- keepalive ---
PING_INTERVAL = 15
PING_TIMEOUT = 10

# --- abuse limits ---
MAX_TOTAL_CONNECTIONS = 200          # hard cap, protects memory/fd exhaustion
MAX_CONN_PER_IP = 6                  # simultaneous sockets from one address
MAX_NEW_CONN_PER_IP_PER_MIN = 20     # connection-flood throttle
MAX_MSGS_PER_SEC = 60                # per-connection message rate (voice needs headroom)
MAX_MESSAGE_BYTES = 4096             # position/chat are tiny; voice chunks ~1.4 KB
MAX_FAILED_JOINS_PER_IP = 8          # room-code brute-force lockout threshold
FAILED_JOIN_WINDOW_SEC = 60
FAILED_JOIN_LOCKOUT_SEC = 120
ROOM_TTL_UNJOINED_SEC = 600          # abandoned "hosted" rooms auto-expire

ROOM_CODE_LEN = 6                    # 36^6 ≈ 2.2B combinations
MIN_PLAYERS, MAX_PLAYERS = 2, 8      # server-enforced bounds regardless of client request
MAX_LOBBY_NAME_LEN = 32

rooms = {}                # code -> {"peers": set[ws], "created": ts, "joined": bool,
                           #          "max_players": int, "lobby_name": str}
conns_per_ip = {}         # ip -> count of currently open sockets
new_conn_times = {}       # ip -> list[timestamps] (sliding window)
failed_joins = {}         # ip -> list[timestamps]
blocked_until = {}        # ip -> unblock timestamp
total_connections = 0


def gen_code():
    while True:
        c = "".join(random.choices(string.ascii_uppercase + string.digits, k=ROOM_CODE_LEN))
        if c not in rooms:
            return c


def client_ip(ws):
    addr = ws.remote_address
    return addr[0] if addr else "unknown"


def prune_old(timestamps, window):
    cutoff = time.time() - window
    while timestamps and timestamps[0] < cutoff:
        timestamps.pop(0)


def is_blocked(ip):
    until = blocked_until.get(ip)
    if until and time.time() < until:
        return True
    if until:
        del blocked_until[ip]
    return False


def record_failed_join(ip):
    times = failed_joins.setdefault(ip, [])
    times.append(time.time())
    prune_old(times, FAILED_JOIN_WINDOW_SEC)
    if len(times) >= MAX_FAILED_JOINS_PER_IP:
        blocked_until[ip] = time.time() + FAILED_JOIN_LOCKOUT_SEC
        log.warning("ip %s locked out %ss (room-code brute-force pattern)", ip, FAILED_JOIN_LOCKOUT_SEC)


def sweep_stale_rooms():
    now = time.time()
    stale = [c for c, r in rooms.items()
             if not r["joined"] and now - r["created"] > ROOM_TTL_UNJOINED_SEC]
    for c in stale:
        del rooms[c]
    if stale:
        log.info("swept %d stale unjoined room(s)", len(stale))


async def handle(ws):
    global total_connections
    ip = client_ip(ws)
    code = None

    if is_blocked(ip):
        await ws.close(code=1008, reason="temporarily blocked")
        return

    if total_connections >= MAX_TOTAL_CONNECTIONS:
        log.warning("global connection cap hit, rejecting %s", ip)
        await ws.close(code=1013, reason="server busy")
        return

    if conns_per_ip.get(ip, 0) >= MAX_CONN_PER_IP:
        log.warning("per-ip connection cap hit for %s", ip)
        await ws.close(code=1008, reason="too many connections")
        return

    window = new_conn_times.setdefault(ip, [])
    prune_old(window, 60)
    if len(window) >= MAX_NEW_CONN_PER_IP_PER_MIN:
        log.warning("connection-rate limit hit for %s", ip)
        await ws.close(code=1008, reason="rate limited")
        return
    window.append(time.time())

    total_connections += 1
    conns_per_ip[ip] = conns_per_ip.get(ip, 0) + 1
    msg_times = []

    try:
        raw = await ws.recv()
        if len(raw) > MAX_MESSAGE_BYTES:
            return
        msg = json.loads(raw)

        if msg["type"] == "host":
            sweep_stale_rooms()
            session_id = msg.get("session_id")
            code = msg.get("room_code")
            
            # Reclaiming an existing room
            if code and code in rooms and rooms[code].get("host_session") == session_id:
                room = rooms[code]
                room["host_ws"] = ws
                room["peers"].add(ws)
                await ws.send(json.dumps({
                    "type": "hosted", "code": code, "max_players": room["max_players"],
                    "lobby_name": room["lobby_name"], "player_count": len(room["peers"])
                }))
                continue
                
            code = gen_code()

            try:
                max_players = int(msg.get("max_players", MIN_PLAYERS))
            except (TypeError, ValueError):
                max_players = MIN_PLAYERS
            max_players = max(MIN_PLAYERS, min(MAX_PLAYERS, max_players))
            lobby_name = str(msg.get("lobby_name", "")).strip()[:MAX_LOBBY_NAME_LEN]

            rooms[code] = {
                "peers": {ws}, "host_ws": ws, "host_session": session_id, "created": time.time(), "joined": False,
                "max_players": max_players, "lobby_name": lobby_name,
            }
            await ws.send(json.dumps({
                "type": "hosted", "code": code, "max_players": max_players,
                "lobby_name": lobby_name, "player_count": 1,
            }))
            log.info("room %s hosted by %s (max=%d, name=%r)", code, ip, max_players, lobby_name)

        elif msg["type"] == "join":
            code = str(msg.get("code", "")).upper()[:ROOM_CODE_LEN]
            room = rooms.get(code)
            if not room or len(room["peers"]) >= room["max_players"]:
                record_failed_join(ip)
                await ws.send(json.dumps({"type": "error", "msg": "room not found or full"}))
                return
            room["peers"].add(ws)
            room["joined"] = True
            count = len(room["peers"])
            await ws.send(json.dumps({
                "type": "joined", "code": code, "max_players": room["max_players"],
                "lobby_name": room["lobby_name"], "player_count": count,
            }))
            for peer in room["peers"]:
                if peer is not ws:
                    await peer.send(json.dumps({"type": "peer_joined", "player_count": count}))
            log.info("room %s joined (%d/%d) by %s", code, count, room["max_players"], ip)

        else:
            return

        async for raw in ws:
            if len(raw) > MAX_MESSAGE_BYTES:
                continue

            now = time.time()
            msg_times.append(now)
            prune_old(msg_times, 1.0)
            if len(msg_times) > MAX_MSGS_PER_SEC:
                log.warning("message-rate limit hit for %s, dropping", ip)
                await ws.close(code=1008, reason="message rate limited")
                return

            room = rooms.get(code)
            if room:
                for peer in list(room["peers"]):
                    if peer is not ws:
                        try:
                            await peer.send(raw)
                        except websockets.exceptions.ConnectionClosed:
                            pass

    except (websockets.exceptions.ConnectionClosed, json.JSONDecodeError, KeyError) as e:
        log.info("session ended (room %s, ip %s): %s", code, ip, e.__class__.__name__)
    finally:
        total_connections -= 1
        conns_per_ip[ip] = max(0, conns_per_ip.get(ip, 1) - 1)
        if conns_per_ip[ip] == 0:
            del conns_per_ip[ip]
        room = rooms.get(code) if code else None
        if room:
            room["peers"].discard(ws)
            if ws == room.get("host_ws"):
                if room["peers"]:
                    new_host = next(iter(room["peers"]))
                    room["host_ws"] = new_host
                    try:
                        import asyncio
                        asyncio.create_task(new_host.send(json.dumps({"type": "promote_to_host"})))
                    except:
                        pass
                else:
                    room["host_ws"] = None
            if not room["peers"]:
                if code in rooms:
                    del rooms[code]
                log.info("room %s closed", code)
            else:
                count = len(room["peers"])
                for peer in list(room["peers"]):
                    try:
                        await peer.send(json.dumps({"type": "peer_left", "player_count": count}))
                    except:
                        pass

async def main():
    log.info(
        "relay listening on %s:%s | caps: total=%d per_ip=%d new_conn/min=%d msg/s=%d",
        HOST, PORT, MAX_TOTAL_CONNECTIONS, MAX_CONN_PER_IP,
        MAX_NEW_CONN_PER_IP_PER_MIN, MAX_MSGS_PER_SEC,
    )
    async with websockets.serve(
        handle, HOST, PORT,
        ping_interval=PING_INTERVAL,
        ping_timeout=PING_TIMEOUT,
        max_size=MAX_MESSAGE_BYTES,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
