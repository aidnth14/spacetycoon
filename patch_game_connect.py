import re
with open("client/game.py", "r") as f:
    src = f.read()

src = src.replace('S.conn.connect(addr, {', 'S.conn.connect(addr, {') # wait, that's tricky. Let's use regex
src = re.sub(r'S\.conn\.connect\(addr, \{(.*?)\}\)', r'S.conn.connect(addr, {\1}, S.client_id)', src, flags=re.DOTALL)

with open("client/game.py", "w") as f:
    f.write(src)
