with open("server/server.py", "r") as f:
    lines = f.readlines()

new_lines = []
for i, line in enumerate(lines):
    if line.strip() == "continue" and i == 145:
        # replace with pass, but we need to indent everything below
        pass
    else:
        new_lines.append(line)

# Wait, rewriting by logic is safer
import re
with open("server/server.py", "r") as f:
    src = f.read()

# Replace the block
bad_block = """            # Reclaiming an existing room
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
            log.info("room %s hosted by %s (max=%d, name=%r)", code, ip, max_players, lobby_name)"""

good_block = """            # Reclaiming an existing room
            if code and code in rooms and rooms[code].get("host_session") == session_id:
                room = rooms[code]
                room["host_ws"] = ws
                room["peers"].add(ws)
                await ws.send(json.dumps({
                    "type": "hosted", "code": code, "max_players": room["max_players"],
                    "lobby_name": room["lobby_name"], "player_count": len(room["peers"])
                }))
            else:
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
                log.info("room %s hosted by %s (max=%d, name=%r)", code, ip, max_players, lobby_name)"""

src = src.replace(bad_block, good_block)
with open("server/server.py", "w") as f:
    f.write(src)
