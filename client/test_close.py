import json
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed

try:
    with connect("wss://spacetycoon-relay.onrender.com") as ws:
        ws.send(json.dumps({"type": "host"}))
        for raw in ws:
            print("Got:", raw)
            ws.close() # Close it ourselves to see what the iterator does
except ConnectionClosed:
    print("Caught ConnectionClosed")
except Exception as e:
    print("Caught Exception:", type(e))
else:
    print("Normal exit (else)")
