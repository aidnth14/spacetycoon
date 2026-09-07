with open("game.py", "r") as f:
    src = f.read()

old_all_ready = """                if not p.get("ready") and not p.get("is_host"):
                    all_ready = False"""
new_all_ready = """                if not p.get("ready") and not p.get("is_host") and not p.get("restricted"):
                    all_ready = False"""

src = src.replace(old_all_ready, new_all_ready)

with open("game.py", "w") as f:
    f.write(src)
