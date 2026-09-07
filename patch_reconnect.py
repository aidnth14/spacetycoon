import re
with open("client/game.py", "r") as f:
    src = f.read()

hosted_logic = """            elif t == "hosted":
                if getattr(S, "is_host", False) and S.room_code == msg["code"]:
                    # Reconnected!
                    if S.state == STATE_WAIT:
                        S.conn.send({"type": "lobby_state", "players": getattr(S, "lobby_players", {})})
                    else:
                        S.conn.send({"type": "lobby_start"}) # remind peers we are in game
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
                            "is_host": True
                        }
                    }
                    S.state = STATE_WAIT
"""
src = re.sub(r'            elif t == "hosted":\n(?:.*?\n)+?                    S\.state = STATE_WAIT\n', hosted_logic, src)

# Same for joined
joined_logic = """            elif t == "joined":
                if S.room_code == msg["code"] and not getattr(S, "is_host", True):
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
                    except:
                        pass
"""
src = re.sub(r'            elif t == "joined":\n(?:.*?\n)+?                        pass\n', joined_logic, src)

with open("client/game.py", "w") as f:
    f.write(src)
