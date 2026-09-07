import re
with open("client/game.py", "r") as f:
    src = f.read()

anticheat_old = """                            if speed > 600:
                                # Rubberband them back to old position!
                                S.conn.send({"type": "force_pos", "target": pid, "x": old_pr["p"][0], "y": old_pr["p"][1], "z": old_pr["p"][2]})
                                continue  # Ignore this illegal update"""

anticheat_new = """                            # Check if restricted
                            is_restricted = getattr(S, "lobby_players", {}).get(pid, {}).get("restricted", False)
                            if speed > 600 or is_restricted:
                                # Rubberband them back to old position!
                                S.conn.send({"type": "force_pos", "target": pid, "x": old_pr["p"][0], "y": old_pr["p"][1], "z": old_pr["p"][2]})
                                continue  # Ignore this illegal update"""

src = src.replace(anticheat_old, anticheat_new)

with open("client/game.py", "w") as f:
    f.write(src)
