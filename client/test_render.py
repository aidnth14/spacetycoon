import json
from websockets.sync.client import connect
try:
    with connect("wss://spacetycoon-relay.onrender.com") as ws:
        print("Connected!")
        ws.send(json.dumps({"type": "host"}))
        msg = ws.recv()
        print("Received:", msg)
except Exception as e:
    print("Error:", repr(e))
