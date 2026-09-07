import re
with open("client/game.py", "r") as f:
    src = f.read()

# 1. Handle promote_to_host and force_pos
new_handlers = """            elif t == "promote_to_host":
                S.is_host = True
                my_info = getattr(S, "lobby_players", {}).get(S.client_id)
                if my_info:
                    my_info["is_host"] = True
                S.conn.send({"type": "lobby_state", "players": getattr(S, "lobby_players", {})})
            elif t == "force_pos":
                if msg.get("target") == S.client_id:
                    S.me[0] = msg["x"]
                    S.me[1] = msg["y"]
                    S.me[2] = msg.get("z", 0.0)
"""
src = src.replace('            elif t == "lobby_ping":', new_handlers + '            elif t == "lobby_ping":')

# 2. Handle anti-cheat in pos
pos_old = """            elif t == "pos":
                pid = msg.get("id", msg.get("name", "peer"))
                nm = msg.get("name", "Peer") or "Peer"
                col = tuple(msg["color"]) if msg.get("color") else color_for(nm)
                S.peers[pid] = {"p": [msg["x"], msg["y"], msg.get("z", 0.0)],
                                "name": nm, "color": col, "seen": now}"""

pos_new = """            elif t == "pos":
                pid = msg.get("id", msg.get("name", "peer"))
                nm = msg.get("name", "Peer") or "Peer"
                col = tuple(msg["color"]) if msg.get("color") else color_for(nm)
                
                # --- ANTI-CHEAT (HOST AUTHORITATIVE PHYSICS) ---
                if getattr(S, "is_host", False) and pid != S.client_id:
                    old_pr = getattr(S, "peers", {}).get(pid)
                    if old_pr:
                        dt = now - old_pr["seen"]
                        if dt > 0:
                            dx = msg["x"] - old_pr["p"][0]
                            dy = msg["y"] - old_pr["p"][1]
                            dist = (dx**2 + dy**2)**0.5
                            speed = dist / dt
                            # Allow up to 600 pixels/sec (SPEED is ~180, plus lag tolerance)
                            if speed > 600:
                                # Rubberband them back to old position!
                                S.conn.send({"type": "force_pos", "target": pid, "x": old_pr["p"][0], "y": old_pr["p"][1], "z": old_pr["p"][2]})
                                continue  # Ignore this illegal update

                S.peers[pid] = {"p": [msg["x"], msg["y"], msg.get("z", 0.0)],
                                "name": nm, "color": col, "seen": now}"""
src = src.replace(pos_old, pos_new)

with open("client/game.py", "w") as f:
    f.write(src)
