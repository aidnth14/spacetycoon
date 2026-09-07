import re
with open("client/game.py", "r") as f:
    src = f.read()

# Fix mousedown
bad_md = """                grabbed = (S.master_vol_slider.handle_mousedown(event.pos)
                           or S.volume_slider.handle_mousedown(event.pos)
                                                                                 or S.cam_smooth_slider.handle_mousedown(event.pos))"""
good_md = """                grabbed = (S.volume_slider.handle_mousedown(event.pos) or S.cam_smooth_slider.handle_mousedown(event.pos))"""
src = src.replace(bad_md, good_md)

# Fix mouseup
bad_mu = """                S.master_vol_slider.handle_mouseup()
                S.volume_slider.handle_mouseup()
                S.sound_slider.handle_mouseup()
                S.particles_slider.handle_mouseup()
                S.cam_smooth_slider.handle_mouseup()"""
good_mu = """                S.volume_slider.handle_mouseup()
                S.cam_smooth_slider.handle_mouseup()"""
src = src.replace(bad_mu, good_mu)

# Fix mousemotion
bad_mm = """                S.master_vol_slider.handle_mousemotion(event.pos)
                S.volume_slider.handle_mousemotion(event.pos)
                S.sound_slider.handle_mousemotion(event.pos)
                S.particles_slider.handle_mousemotion(event.pos)
                S.cam_smooth_slider.handle_mousemotion(event.pos)"""
good_mm = """                S.volume_slider.handle_mousemotion(event.pos)
                S.cam_smooth_slider.handle_mousemotion(event.pos)"""
src = src.replace(bad_mm, good_mm)

with open("client/game.py", "w") as f:
    f.write(src)
