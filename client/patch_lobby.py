import re

with open("game.py", "r") as f:
    src = f.read()

# 1. State initialization
init_vars = """    S.lobby_players = {}
    S.is_host = False
    S.lobby_ready = False
    S.lobby_start_btn = None
    S.lobby_ready_btn = None
    S.lobby_kick_btns = {}
    S.lobby_restrict_btns = {}
    S.lobby_player_list = []
"""
src = re.sub(r'(S\.chat_log = \[\])', r'\1\n' + init_vars, src)

# 2. Host transition (hosted)
host_repl = """            elif t == "hosted":
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
"""
src = re.sub(r'            elif t == "hosted":\n(?:.*?\n){8}', host_repl, src)

# 3. Join transition (joined)
join_repl = """            elif t == "joined":
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
src = re.sub(r'            elif t == "joined":\n(?:.*?\n){9}', join_repl, src)

# 4. Remove automatic STATE_TEST transitions for peer_joined and ping/pong
src = src.replace("""            elif t == "peer_joined":
                S.player_count = msg.get("player_count", S.player_count + 1)
                S.status_msg = "Peer connected!"
                S.state = STATE_TEST
                S.last_pong_time = now""", """            elif t == "peer_joined":
                S.player_count = msg.get("player_count", S.player_count + 1)
                S.status_msg = "Peer connected!"
                S.last_pong_time = now""")

src = src.replace("""                if S.state == STATE_WAIT:
                    S.state = STATE_TEST""", "")

# 5. Add new network message handlers
handlers = """            elif t == "lobby_hello" and S.is_host:
                pid = msg["id"]
                S.lobby_players[pid] = {
                    "name": msg["name"],
                    "profile": msg.get("profile", "Pilot"),
                    "skin": msg.get("skin", "Default"),
                    "color": msg.get("color", [255,255,255]),
                    "ready": False,
                    "restricted": False,
                    "is_host": False
                }
                S.conn.send({"type": "lobby_state", "players": S.lobby_players})
            elif t == "lobby_action":
                if S.is_host:
                    pid = msg.get("id")
                    if pid in S.lobby_players and not S.lobby_players[pid]["restricted"]:
                        if msg.get("action") == "ready":
                            S.lobby_players[pid]["ready"] = bool(msg.get("value"))
                        S.conn.send({"type": "lobby_state", "players": S.lobby_players})
            elif t == "lobby_state":
                S.lobby_players = msg.get("players", {})
                if S.client_id not in S.lobby_players:
                    reset_to_menu(S, "You were kicked by the host.")
            elif t == "lobby_start":
                S.state = STATE_TEST
"""
src = src.replace('            elif t == "chat":', handlers + '            elif t == "chat":')

# 6. Event handling for lobby buttons
click_handling = """        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if S.state == STATE_WAIT:
                pos = event.pos
                if S.lobby_ready_btn and S.lobby_ready_btn.rect.collidepoint(pos):
                    # Toggle ready if not restricted
                    my_info = S.lobby_players.get(S.client_id, {})
                    if not my_info.get("restricted", False):
                        is_ready = my_info.get("ready", False)
                        if S.is_host:
                            S.lobby_players[S.client_id]["ready"] = not is_ready
                            S.conn.send({"type": "lobby_state", "players": S.lobby_players})
                        else:
                            S.conn.send({"type": "lobby_action", "id": S.client_id, "action": "ready", "value": not is_ready})
                if S.is_host and S.lobby_start_btn and S.lobby_start_btn.rect.collidepoint(pos):
                    # Check if all ready
                    if all(p.get("ready") for p in S.lobby_players.values()):
                        S.conn.send({"type": "lobby_start"})
                        S.state = STATE_TEST
                if S.is_host:
                    for pid, btn in S.lobby_kick_btns.items():
                        if btn.rect.collidepoint(pos):
                            if pid in S.lobby_players:
                                del S.lobby_players[pid]
                                S.conn.send({"type": "lobby_state", "players": S.lobby_players})
                    for pid, btn in S.lobby_restrict_btns.items():
                        if btn.rect.collidepoint(pos):
                            if pid in S.lobby_players:
                                S.lobby_players[pid]["restricted"] = not S.lobby_players[pid].get("restricted", False)
                                if S.lobby_players[pid]["restricted"]:
                                    S.lobby_players[pid]["ready"] = False
                                S.conn.send({"type": "lobby_state", "players": S.lobby_players})
"""
src = src.replace('        if event.type == pygame.KEYDOWN and S.state == STATE_MENU:', click_handling + '        if event.type == pygame.KEYDOWN and S.state == STATE_MENU:')

with open("game.py", "w") as f:
    f.write(src)
