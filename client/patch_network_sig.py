import re
with open("client/network.py", "r") as f:
    src = f.read()
src = src.replace("def connect(self, addr, first_message, session_id):", "def connect(self, addr, first_message):\n        session_id = first_message.get('id', 'unknown')")
with open("client/network.py", "w") as f:
    f.write(src)
