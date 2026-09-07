import re
with open("client/game.py", "r") as f:
    src = f.read()

network_state_logic = """            elif t == "network_state":
                ns = msg["state"]
                if ns == "reconnecting":
                    S.status_msg = "Reconnecting..."
                elif ns == "disconnected":
                    reset_to_menu(S, "Disconnected from server.")
            elif t == "connect_error":"""

src = src.replace('            elif t == "connect_error":', network_state_logic)

with open("client/game.py", "w") as f:
    f.write(src)
