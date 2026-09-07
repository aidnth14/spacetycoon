with open("client/game.py", "r") as f:
    src = f.read()

fps_code = """    if getattr(S, "fps_toggle", None) and getattr(S.fps_toggle, "value", False):
        draw_text(screen, f"FPS: {int(1.0/max(0.001, dt))}", S.font, 10, 10, cfg.GREEN)

    return running"""

src = src.replace("    return running", fps_code)

with open("client/game.py", "w") as f:
    f.write(src)
