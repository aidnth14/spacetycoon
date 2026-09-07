import re
with open("game.py", "r") as f:
    src = f.read()

# Don't send positions if restricted
src = src.replace('        if now - S.last_pos_sent > 1.0 / POS_SEND_HZ:', '        my_info = getattr(S, "lobby_players", {}).get(S.client_id, {})\n        if not my_info.get("restricted") and now - S.last_pos_sent > 1.0 / POS_SEND_HZ:')

# Don't let WASD move if restricted
src = src.replace('            if getattr(S, "paused", False) or S.chat_open:', '            my_info = getattr(S, "lobby_players", {}).get(S.client_id, {})\n            if getattr(S, "paused", False) or S.chat_open or my_info.get("restricted"):')

with open("game.py", "w") as f:
    f.write(src)
