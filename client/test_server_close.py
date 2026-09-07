import json, time
from websockets.sync.client import connect

with connect("wss://spacetycoon-relay.onrender.com") as ws:
    ws.send(json.dumps({"type": "host"}))
    msg = ws.recv()
    print("Got:", msg)
    # Don't send anything, wait for server to close
    try:
        for raw in ws:
            print("Got:", raw)
    except Exception as e:
        print("Error:", repr(e))
print("Finished!")
