DEFAULT_SERVER = "wss://spacetycoon-relay.fly.dev"

WIDTH, HEIGHT = 800, 640

MONO_FONTS = "consolas,menlo,couriernew,dejavusansmono,monospace"

# accent (replaced blue with sand)
GOLD = (240, 214, 158)       # was cyan, now SAND_BRIGHT
GOLD_DIM = (198, 172, 122)   # was dim cyan, now SAND
GOLD_FAINT = (148, 122, 72)  # was faint cyan, now a darker sand
WHITE = (235, 235, 235)
MUTED = (150, 150, 165)
RED = (255, 110, 110)
GREEN = (110, 255, 150)
BG = (5, 5, 10)

# desert-sand lobby text menu
SAND = (198, 172, 122)
SAND_BRIGHT = (240, 214, 158)
SAND_SHADOW = (18, 14, 8)

CARD_BG = (16, 17, 24)
CARD_SHADOW = (0, 0, 0)
CARD_BORDER = (60, 72, 80)
DIVIDER = (48, 58, 66)

INPUT_BG = (24, 25, 34)
INPUT_BORDER = (70, 70, 85)

BTN_BG = (26, 48, 30)
BTN_BG_HOVER = (38, 78, 44)
BTN_BORDER = (80, 90, 80)

CARD_W, CARD_H = 640, 400
CARD_RADIUS = 14

CONNECTION_TIMEOUT = 12.0  # seconds without a pong before we call it dead
PING_INTERVAL = 1.0

MUSIC_TRACKS = ["neon_market.wav", "orbital_drift.wav", "cargo_run.wav", "boardroom.wav",
                "sanctuary_guardians.wav", "alien_wolves.wav", "melancholic_walk.wav"]
MUSIC_VOLUME = 0.22  # dimmed, ambient lobby melody rather than full theme blast
MUSIC_FADE_MS = 1500
