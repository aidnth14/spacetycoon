import re

with open("client/game.py", "r") as f:
    src = f.read()

# We need to replace from `if t == "hosted":` all the way down to `elif t == "peer_joined":`
pattern = r'            if t == "hosted":.*?elif t == "peer_joined":'

replacement = """            if t == "hosted":
                if getattr(S, "is_host", False) and S.room_code == msg["code"]:
                    # Reconnected
                    if S.state == STATE_WAIT:
                        S.conn.send({"type": "lobby_state", "players": getattr(S, "lobby_players", {})})
                    else:
                        S.conn.send({"type": "lobby_start"})
                else:
                    S.is_host = True
                    S.room_code = msg["code"]
                    S.lobby_name = msg.get("lobby_name", "")
                    S.max_players = msg.get("max_players", 2)
                    S.player_count = msg.get("player_count", 1)
                    S.status_msg = "Room created — waiting for your friend..."
                    S.last_pong_time = now
                    S.lobby_players = {
                        S.client_id: {
                            "name": S.username,
                            "profile": "Pilot",
                            "skin": "Default",
                            "color": list(color_for(S.username)),
                            "ready": False,
                            "restricted": False,
                            "is_host": True,
                            "disconnected": False,
                            "last_seen": now
                        }
                    }
                    S.state = STATE_WAIT
            elif t == "joined":
                if S.room_code == msg.get("code") and not getattr(S, "is_host", True):
                    # Reconnected
                    pass
                else:
                    S.is_host = False
                    S.room_code = msg["code"]
                    S.lobby_name = msg.get("lobby_name", "")
                    S.max_players = msg.get("max_players", 2)
                    S.player_count = msg.get("player_count", 2)
                    S.last_pong_time = now
                    S.status_msg = "Joined — waiting for host..."
                    try:
                        S.conn.send({
                            "type": "lobby_hello", 
                            "id": S.client_id,
                            "name": S.username,
                            "profile": "Pilot",
                            "skin": "Default",
                            "color": list(color_for(S.username))
                        })
                    except Exception:
                        pass
            elif t == "peer_joined":"""

new_src, count = re.subn(pattern, replacement, src, flags=re.DOTALL)
if count != 1:
    print(f"FAILED: Expected 1 match, found {count}")
    exit(1)

with open("client/game.py", "w") as f:
    f.write(new_src)
print("SUCCESS")
