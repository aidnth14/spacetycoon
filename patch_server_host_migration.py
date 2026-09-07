import re
with open("server/server.py", "r") as f:
    src = f.read()

old_logic = """            if ws == room.get("host_ws"):
                room["host_ws"] = None"""
new_logic = """            if ws == room.get("host_ws"):
                if room["peers"]:
                    new_host = next(iter(room["peers"]))
                    room["host_ws"] = new_host
                    try:
                        import asyncio
                        asyncio.create_task(new_host.send(json.dumps({"type": "promote_to_host"})))
                    except:
                        pass
                else:
                    room["host_ws"] = None"""

src = src.replace(old_logic, new_logic)
with open("server/server.py", "w") as f:
    f.write(src)
