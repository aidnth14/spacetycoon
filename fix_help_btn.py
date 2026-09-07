with open("client/game.py", "r") as f:
    src = f.read()

src = src.replace('widget is getattr(S, "help_btn", None)', 'widget is getattr(S, "help_icon_btn", None)')

with open("client/game.py", "w") as f:
    f.write(src)
