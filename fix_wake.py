import re
with open("client/game.py", "r") as f:
    src = f.read()

wake_old = """    def _ping_server():
        import urllib.request, urllib.error
        http_url = cfg.DEFAULT_SERVER.replace("wss://", "https://").replace("ws://", "http://")
        try:
            urllib.request.urlopen(http_url, timeout=45)
        except urllib.error.HTTPError as e:
            pass  # 426 Upgrade Required means it's awake!
        except Exception as e:
            pass  # We will let the network layer handle actual failures
        S.server_woken = True
        
    S.server_woken = False
    import threading
    threading.Thread(target=_ping_server, daemon=True).start()"""
wake_new = """    def _ping_server():
        import urllib.request, urllib.error
        http_url = cfg.DEFAULT_SERVER.replace("wss://", "https://").replace("ws://", "http://")
        try:
            urllib.request.urlopen(http_url, timeout=45)
            S.server_woken = True
        except urllib.error.HTTPError as e:
            if e.code == 426:
                S.server_woken = True
            else:
                S.server_wake_failed = True
        except Exception as e:
            S.server_wake_failed = True
        
    S.server_woken = False
    S.server_wake_failed = False
    import threading
    threading.Thread(target=_ping_server, daemon=True).start()"""
src = src.replace(wake_old, wake_new)

check_old = """    if S.state == STATE_WAKE:
        if S.server_woken:
            go_setup(S, "host")"""
check_new = """    if S.state == STATE_WAKE:
        if S.server_woken:
            go_setup(S, "host")
        elif getattr(S, "server_wake_failed", False):
            reset_to_menu(S, "Could not reach server.")"""
src = src.replace(check_old, check_new)

with open("client/game.py", "w") as f:
    f.write(src)
