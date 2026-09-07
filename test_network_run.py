import client.network as n
import threading
import time

conn = n.Connection()
conn.connect("ws://localhost:8080", {"test": "first"}, "test_session_id")
time.sleep(1)
print(conn.state)
conn.close()
