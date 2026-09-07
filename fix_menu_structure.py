import re
with open("client/game.py", "r") as f:
    src = f.read()

# 1. Rename the button labels in init
src = src.replace('S.menu_local_btn = _mb("LOCAL")', 'S.menu_local_btn = _mb("SOLO")')
src = src.replace('S.menu_online_btn = _mb("ONLINE")', 'S.menu_online_btn = _mb("ONLINE CO-OP")')
# We won't even use host_local_coop_btn and host_online_coop_btn if we flatten.
# Actually, the user wants "ONLINE CO-OP" to be a top level under play.
# Let's check update_menu_layout:
layout_old = """    elif S.menu_page == "play":
        S.MENU_FOCUS = [S.menu_local_btn, S.menu_online_btn, S.menu_back_btn]
    elif S.menu_page == "online":
        S.MENU_FOCUS = [S.menu_join_btn, S.menu_host_btn, S.menu_back_btn]
    elif S.menu_page == "host":
        S.MENU_FOCUS = [S.host_local_coop_btn, S.host_online_coop_btn, S.menu_back_btn]"""
layout_new = """    elif S.menu_page == "play":
        S.MENU_FOCUS = [S.menu_local_btn, S.host_local_coop_btn, S.menu_online_btn, S.menu_back_btn]
    elif S.menu_page == "online":
        S.MENU_FOCUS = [S.menu_join_btn, S.menu_host_btn, S.menu_back_btn]"""
src = src.replace(layout_old, layout_new)

# And in activate_focused:
# S.menu_online_btn currently goes to "online" (which is [Join, Host, Back]). That's perfect for ONLINE CO-OP!
# We just need to make sure S.host_online_coop_btn is no longer used, and instead menu_host_btn triggers start_wake_server.
# Wait, menu_host_btn goes to S.menu_page = "host".
# But "host" page doesn't exist anymore if we remove it from update_menu_layout?
# If "online" -> [JOIN, HOST, BACK], then HOST means "Host an online game".
# So menu_host_btn should directly do `start_wake_server(S)`!

act_old = """    elif widget is getattr(S, "menu_host_btn", None):
        S.menu_page = "host"
        update_menu_layout(S)
    elif widget is getattr(S, "host_local_coop_btn", None):
        go_setup(S, "local")
    elif widget is getattr(S, "host_online_coop_btn", None):
        start_wake_server(S)"""
act_new = """    elif widget is getattr(S, "menu_host_btn", None):
        start_wake_server(S)
    elif widget is getattr(S, "host_local_coop_btn", None):
        go_setup(S, "local")"""
src = src.replace(act_old, act_new)

# In the escape handler and back button handler:
esc_old = """                if S.menu_page == "host":
                    S.menu_page = "online"
                elif S.menu_page == "online":"""
esc_new = """                if S.menu_page == "online":"""
src = src.replace(esc_old, esc_new)

back_old = """        if S.menu_page == "host":
            S.menu_page = "online"
        elif S.menu_page == "online":"""
back_new = """        if S.menu_page == "online":"""
src = src.replace(back_old, back_new)

with open("client/game.py", "w") as f:
    f.write(src)
