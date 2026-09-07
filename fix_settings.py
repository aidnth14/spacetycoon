import re
with open("client/game.py", "r") as f:
    src = f.read()

# 1. Remove dead sliders/toggles from creation
src = re.sub(r'    S\.master_vol_slider = .*?\n', '', src)
src = re.sub(r'    S\.sound_slider = .*?\n', '', src)
src = re.sub(r'    S\.particles_slider = .*?\n', '', src)
src = re.sub(r'    S\.ui_scale_stepper = .*?\n', '', src)
src = re.sub(r'    S\.chunk_sim_toggle = .*?\n', '', src)
src = re.sub(r'    S\.vsync_toggle = .*?\n', '', src)

# 2. Fix the layout by moving the surviving ones up
# In init_settings(S, y):
#     S.volume_slider = Slider(col1_x, y + 60, 200, value=cfg.MUSIC_VOLUME, label="MUSIC")
#     S.cam_smooth_slider = Slider(col1_x, y + 240, 200, value=0.5, label="CAMERA SMOOTHING")
src = src.replace('S.volume_slider = Slider(col1_x, y + 60, 200, value=cfg.MUSIC_VOLUME, label="MUSIC")', 'S.volume_slider = Slider(col1_x, y, 200, value=cfg.MUSIC_VOLUME, label="MUSIC")')
src = src.replace('S.cam_smooth_slider = Slider(col1_x, y + 240, 200, value=0.5, label="CAMERA SMOOTHING")', 'S.cam_smooth_slider = Slider(col1_x, y + 80, 200, value=0.5, label="CAMERA SMOOTHING")')
src = src.replace('S.render_dist_stepper = Stepper(col2_x, y, 200, 30, "RENDER DISTANCE", 16, 8, 32)', 'S.render_dist_stepper = Stepper(col2_x, y, 200, 30, "RENDER DISTANCE", 6, 2, 16)')
src = src.replace('S.fps_toggle = Toggle(col2_x, y + 180, 56, 28, "SHOW FPS", value=False)', 'S.fps_toggle = Toggle(col2_x, y + 80, 56, 28, "SHOW FPS", value=False)')
src = src.replace('S.music_toggle = Toggle(col1_x, y + 300, 56, 28, "MUTE", value=False)', 'S.music_toggle = Toggle(col1_x, y + 160, 56, 28, "MUTE", value=False)')

# 3. Fix draw list
src = src.replace('for slider in (S.master_vol_slider, S.volume_slider, S.sound_slider, S.particles_slider, S.cam_smooth_slider):', 'for slider in (S.volume_slider, S.cam_smooth_slider):')
src = src.replace('for toggle in (S.music_toggle, S.chunk_sim_toggle, S.fps_toggle, S.vsync_toggle):', 'for toggle in (S.music_toggle, S.fps_toggle):')
src = src.replace('for stepper in (S.render_dist_stepper, S.ui_scale_stepper):', 'for stepper in (S.render_dist_stepper,):')

# 4. Fix event handling (drag checks)
src = src.replace('if S.volume_slider.dragging or S.sound_slider.dragging:', 'if S.volume_slider.dragging or S.cam_smooth_slider.dragging:')
src = src.replace('if S.master_vol_slider.dragging or S.volume_slider.dragging or S.sound_slider.dragging:', 'if S.volume_slider.dragging or S.cam_smooth_slider.dragging:')

# 5. Fix mouseup/mousedown arrays
src = re.sub(r'\[S\.volume_slider\.rect.*?\]', r'[S.volume_slider.rect, S.cam_smooth_slider.rect, S.render_dist_stepper.rect, S.music_toggle.rect, S.fps_toggle.rect]', src)
src = src.replace('or S.sound_slider.handle_mousedown(event.pos)', 'or S.cam_smooth_slider.handle_mousedown(event.pos)')
src = src.replace('or S.particles_slider.handle_mousedown(event.pos)\n', '')
src = src.replace('or S.master_vol_slider.handle_mousedown(event.pos)\n', '')
src = src.replace('or S.cam_smooth_slider.handle_mousedown(event.pos)\n', '') # It was already listed, let's just make it clean

# 6. Actually implement CAM_SMOOTH and REVEAL_RADIUS
# CAM_SMOOTH goes from 1.0 to 12.0 maybe? 0 to 1 slider -> 1.0 + slider * 11.0
src = src.replace('k = min(1.0, CAM_SMOOTH * dt)', 'k = min(1.0, (1.0 + getattr(S, "cam_smooth_slider", lambda: type("obj", (object,), {"value": 0.5}))().value * 11.0) * dt)')
# Actually, the lambda is messy. S always has cam_smooth_slider once initialized, but just in case:
# k = min(1.0, (1.0 + S.cam_smooth_slider.value * 11.0) * dt)
src = src.replace('k = min(1.0, (1.0 + getattr(S, "cam_smooth_slider", lambda: type("obj", (object,), {"value": 0.5}))().value * 11.0) * dt)', 'k = min(1.0, (1.0 + S.cam_smooth_slider.value * 11.0) * dt)')

# For REVEAL_RADIUS, we just use S.render_dist_stepper.value
src = src.replace('R, R2 = REVEAL_RADIUS, REVEAL_RADIUS * REVEAL_RADIUS', 'R = S.render_dist_stepper.value; R2 = R * R')

# 7. Implement FPS
# In the frame draw loop:
fps_draw = """    if getattr(S, "fps_toggle", None) and S.fps_toggle.value:
        draw_text(screen, f"FPS: {int(1.0/max(0.001, dt))}", S.font, 10, 10, cfg.GREEN)
"""
src = re.sub(r'(    pygame\.display\.flip\(\))', fps_draw + r'\1', src)

with open("client/game.py", "w") as f:
    f.write(src)
