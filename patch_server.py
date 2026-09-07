import re
with open("server/server.py", "r") as f:
    src = f.read()

# Instead of dropping room when host drops, we keep it for 60s
src = src.replace('            if not room["peers"] or ws == room.get("host_ws"):', '            if not room["peers"]:')

# When hosting, allow claiming an existing room if session_id matches
host_logic = """        if msg["type"] == "host":
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
"""
src = re.sub(r'        if msg\["type"\] == "host":\n            sweep_stale_rooms\(\)\n            code = gen_code\(\)', host_logic, src)

# Add host_session to room
src = src.replace('"peers": {ws}, "host_ws": ws,', '"peers": {ws}, "host_ws": ws, "host_session": session_id,')

# When joining, if it's a reconnect, just add them
join_logic = """        elif msg["type"] == "join":
            code = str(msg.get("code", "")).upper()[:ROOM_CODE_LEN]
            room = rooms.get(code)
            if not room or len(room["peers"]) >= room["max_players"]:
                # allow reconnect if they were in the room? Actually we don't track joiner sessions in server, we track peers limit.
                # Just let them join if room not full, or if they are already in the peers (which they won't be if disconnected).
                pass
"""
# I'll just rewrite the finally block instead to be safer
finally_block = """    finally:
        total_connections -= 1
        conns_per_ip[ip] = max(0, conns_per_ip.get(ip, 1) - 1)
        if conns_per_ip[ip] == 0:
            del conns_per_ip[ip]
        room = rooms.get(code) if code else None
        if room:
            room["peers"].discard(ws)
            if ws == room.get("host_ws"):
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
"""
src = re.sub(r'    finally:\n(?:.*?\n)+?async def main\(\):', finally_block + '\nasync def main():', src)

with open("server/server.py", "w") as f:
    f.write(src)
