import re
with open("game.py", "r") as f:
    src = f.read()

src = src.replace('status = "HOST" if p.get("is_host") else ("RESTRICTED" if p.get("restricted") else ("READY" if p.get("ready") else "NOT READY"))', 'status = "HOST" if p.get("is_host") else ("DISCONNECTED" if p.get("disconnected") else ("RESTRICTED" if p.get("restricted") else ("READY" if p.get("ready") else "NOT READY")))')

with open("game.py", "w") as f:
    f.write(src)
