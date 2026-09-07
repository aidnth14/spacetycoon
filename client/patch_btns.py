import re
with open("game.py", "r") as f:
    src = f.read()

src = src.replace('kick_btn = Button("KICK", kx, ky, 50, 24, bg=cfg.RED)', 'kick_btn = Button(kx, ky, 50, 24, "KICK", palette={"fill": cfg.RED, "border": cfg.RED})')
src = src.replace('r_btn = Button(rlabel, rx, ry, 100, 24, bg=rbg)', 'r_btn = Button(rx, ry, 100, 24, rlabel, palette={"fill": rbg, "border": rbg})')
src = src.replace('S.lobby_ready_btn = Button(ready_label, CENTER_X - 60, cfg.HEIGHT - 120, 120, 40, bg=ready_bg)', 'S.lobby_ready_btn = Button(CENTER_X - 60, cfg.HEIGHT - 120, 120, 40, ready_label, palette={"fill": ready_bg, "border": ready_bg})')
src = src.replace('S.lobby_start_btn = Button("START GAME", CENTER_X - 80, cfg.HEIGHT - 120, 160, 40, bg=start_bg)', 'S.lobby_start_btn = Button(CENTER_X - 80, cfg.HEIGHT - 120, 160, 40, "START GAME", palette={"fill": start_bg, "border": start_bg})')

with open("game.py", "w") as f:
    f.write(src)
