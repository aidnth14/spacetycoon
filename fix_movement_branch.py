import re
with open("client/game.py", "r") as f:
    src = f.read()

# Fix STATE_LOCAL
local_old = """            my_info = getattr(S, "lobby_players", {}).get(S.client_id, {})
            if getattr(S, "paused", False) or S.chat_open or my_info.get("restricted"):"""
local_new = """            if getattr(S, "paused", False) or S.chat_open:"""
src = src.replace(local_old, local_new)

# Fix STATE_TEST
test_old = """        keys = pygame.key.get_pressed()
        if not S.chat_open and not getattr(S, "paused", False):"""
test_new = """        keys = pygame.key.get_pressed()
        my_info = getattr(S, "lobby_players", {}).get(S.client_id, {})
        if not S.chat_open and not getattr(S, "paused", False) and not my_info.get("restricted"):"""
src = src.replace(test_old, test_new)

with open("client/game.py", "w") as f:
    f.write(src)
