import re
with open("client/game.py", "r") as f:
    src = f.read()

better_hello = """            elif t == "lobby_hello" and S.is_host:
                pid = msg["id"]
                existing = getattr(S, "lobby_players", {}).get(pid, {})
                S.lobby_players[pid] = {
                    "name": msg["name"],
                    "profile": msg.get("profile", "Pilot"),
                    "skin": msg.get("skin", "Default"),
                    "color": msg.get("color", [255,255,255]),
                    "ready": existing.get("ready", False),
                    "restricted": existing.get("restricted", False),
                    "is_host": False,
                    "disconnected": False,
                    "last_seen": now
                }
                S.conn.send({"type": "lobby_state", "players": S.lobby_players})
"""
src = re.sub(r'            elif t == "lobby_hello" and S\.is_host:\n(?:.*?\n)+?                S\.conn\.send\(\{"type": "lobby_state", "players": S\.lobby_players\}\)\n', better_hello, src)
with open("client/game.py", "w") as f:
    f.write(src)
