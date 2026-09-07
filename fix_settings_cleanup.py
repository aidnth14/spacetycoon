import re
with open("client/game.py", "r") as f:
    src = f.read()

# 1. Strip chunk/vsync/ui_scale clicks
src = re.sub(r'\s*elif S\.chunk_sim_toggle\.clicked\(event\.pos\):\n\s*S\.chunk_sim_toggle\.value = not S\.chunk_sim_toggle\.value', '', src)
src = re.sub(r'\s*elif S\.vsync_toggle\.clicked\(event\.pos\):\n\s*S\.vsync_toggle\.value = not S\.vsync_toggle\.value', '', src)
src = re.sub(r'\s*elif S\.ui_scale_stepper\.handle_click\(event\.pos\):\n\s*pass', '', src) # wait, I don't know the exact string, let's just delete the lines

with open("client/game.py", "w") as f:
    f.write(src)
