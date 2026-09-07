from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosed
try:
    with connect("ws://localhost:8081") as ws:
        for raw in ws:
            pass
except ConnectionClosed as e:
    print(f"Caught ConnectionClosed: {e.code} {e.reason}")
else:
    print("Normal exit")
