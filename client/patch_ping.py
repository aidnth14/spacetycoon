import re
with open("game.py", "r") as f:
    src = f.read()

ping_logic = """            elif t == "lobby_ping":
                S.conn.send({"type": "lobby_pong", "id": S.client_id})
            elif t == "lobby_pong":
                if S.is_host:
                    pid = msg.get("id")
                    if pid in getattr(S, "lobby_players", {}):
                        S.lobby_players[pid]["last_seen"] = now
            elif t == "chat":"""

src = src.replace('            elif t == "chat":', ping_logic)

# In frame(S, events, dt, now), add ping broadcast for host
frame_logic = """    if S.state == STATE_WAIT and S.is_host:
        if now - getattr(S, "last_lobby_ping", 0) > 2.0:
            S.conn.send({"type": "lobby_ping"})
            S.last_lobby_ping = now
            changed = False
            for pid, p in S.lobby_players.items():
                if not p.get("is_host") and now - p.get("last_seen", now) > 6.0:
                    if not p.get("disconnected"):
                        p["disconnected"] = True
                        p["ready"] = False
                        changed = True
            if changed:
                S.conn.send({"type": "lobby_state", "players": S.lobby_players})
"""
src = re.sub(r'(    if S\.state == STATE_TEST:\n        prune_peers\(S, now\))', frame_logic + r'\n\1', src)

# Ensure new players have last_seen initialized
hello_old = '                    "is_host": False\n                }'
hello_new = '                    "is_host": False,\n                    "last_seen": now\n                }'
src = src.replace(hello_old, hello_new)

with open("game.py", "w") as f:
    f.write(src)
