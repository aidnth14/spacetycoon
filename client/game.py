"""All per-frame logic lives here so main.py can hot-reload it live.

Persistent state (network conn, music, positions, typed text, counters) is
stored on the shared `S` namespace which main.py owns and never rebuilds, so
reloading this module never drops the connection or resets a session.
"""
import math
import os
import queue
import time

import pygame

import config as cfg
import ui
import iso
import voice as voicelib
from ui import (
    Starfield, TextInput, Button, IconButton, Slider, Toggle, Stepper,
    draw_glow_text, draw_text, draw_wrapped_text, draw_card, draw_divider, pulse_alpha,
    draw_focus_ring,
)

STATE_MENU, STATE_SETUP, STATE_WAIT, STATE_TEST, STATE_LOCAL = \
    "menu", "setup", "wait", "test", "local"

JOYSTICK_A, JOYSTICK_B = 0, 1  # standard Xbox/PlayStation layout button indices
SPEED_CELLS = 5.5  # avatar walk speed in grid cells / sec (zoom-independent)
PLAYER_R = 12
LOCAL_MAX = 4  # same-screen coop supports up to 4 keyboard controllers
POS_SEND_HZ = 6  # online position updates/sec (stays under the relay rate cap)
CAM_SMOOTH = 6.0  # camera easing — lower = smoother/laggier follow

# jump / gravity — z is height in screen px; airborne avatars clear props
GRAVITY = 1500.0
JUMP_V = 470.0
JUMP_CLEAR = 8.0  # z above which you're airborne and can pass over rocks

# auto-assigned avatar colours (online): stable per-name so everyone agrees
PALETTE = [
    (90, 200, 220), (110, 255, 150), (110, 180, 255), (255, 150, 220),
    (255, 190, 90), (180, 140, 255), (255, 120, 120), (120, 255, 205),
]


def color_for(name):
    h = sum(ord(c) for c in name) if name else 0
    return PALETTE[h % len(PALETTE)]


PEER_TIMEOUT = 4.0     # drop a remote avatar after this many seconds of silence
CHAT_FADE = 9.0        # seconds a message stays before fading when chat is closed
VOICE_KEY = pygame.K_v  # hold to talk (online)

# per-player local control schemes: (label, up, down, left, right, color, jump)
# up/down/left/right map to isometric NE/SW/NW/SE, not screen axes.
SCHEMES = [
    ("WASD", pygame.K_w, pygame.K_s, pygame.K_a, pygame.K_d, (90, 200, 220), pygame.K_SPACE),
    ("ARROWS", pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT, (110, 255, 150), pygame.K_RSHIFT),
    ("IJKL", pygame.K_i, pygame.K_k, pygame.K_j, pygame.K_l, (110, 180, 255), pygame.K_o),
    ("TFGH", pygame.K_t, pygame.K_g, pygame.K_f, pygame.K_h, (255, 150, 220), pygame.K_y),
]

# --- layout (recomputed from cfg on every reload, so cfg edits apply live) ---
CENTER_X = cfg.WIDTH // 2
CARD_X = (cfg.WIDTH - cfg.CARD_W) // 2
CARD_Y = 150
CARD = pygame.Rect(CARD_X, CARD_Y, cfg.CARD_W, cfg.CARD_H)
PAD = 40
LOCAL_PLAY = pygame.Rect(CARD_X + PAD, CARD_Y + 130, cfg.CARD_W - PAD * 2, cfg.CARD_H - 160)

COL_GAP = 24
COL_W = (cfg.CARD_W - PAD * 2 - COL_GAP) // 2
LEFT_X = CARD_X + PAD
RIGHT_X = LEFT_X + COL_W + COL_GAP
COL_HEADER_Y = CARD_Y + 108

BTN_H = 52
btn_y = CARD_Y + 280
GEAR_SIZE, GEAR_GAP = 40, 12

SETTINGS_W, SETTINGS_H = 460, 440
SETTINGS_RECT = pygame.Rect(CENTER_X - SETTINGS_W // 2, cfg.HEIGHT // 2 - SETTINGS_H // 2,
                            SETTINGS_W, SETTINGS_H)


# --- music (all state on S) ---
def track_display_name(index):
    if not cfg.MUSIC_TRACKS:
        return "No tracks loaded"
    stem = os.path.splitext(cfg.MUSIC_TRACKS[index % len(cfg.MUSIC_TRACKS)])[0]
    return stem.replace("_", " ").title()


def play_track_at(S, index):
    if not cfg.MUSIC_TRACKS:
        return
    S.music_track_index = index % len(cfg.MUSIC_TRACKS)
    path = os.path.join(S.ASSETS_DIR, cfg.MUSIC_TRACKS[S.music_track_index])
    try:
        pygame.mixer.music.load(path)
        pygame.mixer.music.set_volume(0.0 if S.music_muted else S.music_volume)
        pygame.mixer.music.play(fade_ms=cfg.MUSIC_FADE_MS)
        S.music_paused = False
    except pygame.error as e:
        print(f"[audio] couldn't load {path}: {e}")


def play_next_track(S):
    play_track_at(S, S.music_track_index + 1)


def play_prev_track(S):
    play_track_at(S, S.music_track_index - 1)


def toggle_play_pause(S):
    if not cfg.MUSIC_TRACKS:
        return
    if S.music_paused:
        pygame.mixer.music.unpause()
    else:
        pygame.mixer.music.pause()
    S.music_paused = not S.music_paused


def apply_volume(S):
    S.music_volume = S.volume_slider.value
    S.sound_volume = S.sound_slider.value
    S.music_muted = S.music_toggle.value  # toggle reads "MUTE": True = muted
    pygame.mixer.music.set_volume(0.0 if S.music_muted else S.music_volume)


def _load_icon(path, size):
    try:
        return pygame.transform.smoothscale(pygame.image.load(path).convert_alpha(), (size, size))
    except pygame.error:
        return None


# --- fonts + widgets (rebuilt on reload; values carried over) ---
def _brand_font(S, size):
    """Bold display font for titles / the wordmark."""
    return pygame.font.SysFont(cfg.MONO_FONTS, size, bold=True)


def _build_fonts(S):
    S.small_font = pygame.font.SysFont(cfg.MONO_FONTS, 14)
    S.font = pygame.font.SysFont(cfg.MONO_FONTS, 19)
    S.body_font = pygame.font.SysFont(cfg.MONO_FONTS, 22)
    S.big_font = pygame.font.SysFont(cfg.MONO_FONTS, 26, bold=True)
    # headline/branding uses the bold display font; code/RTT stays mono for digits
    S.title_font = _brand_font(S, 34)
    S.brand_font = _brand_font(S, 52)  # the big "SPACE TYCOON" wordmark
    S.code_font = pygame.font.SysFont(cfg.MONO_FONTS, 52, bold=True)


def _build_ui(S):
    # server address lives on the JOIN / HOST setup panels
    S.addr_input = TextInput(LEFT_X, CARD_Y + 56, cfg.CARD_W - PAD * 2, 36,
                             "SERVER ADDRESS", cfg.DEFAULT_SERVER)
    S.code_input = TextInput(LEFT_X, CARD_Y + 132, cfg.CARD_W - PAD * 2, 40, "ROOM CODE")

    # lobby settings + username live on the SETUP screen (single / local / join / host)
    S.lobby_name_input = TextInput(LEFT_X, CARD_Y + 116, cfg.CARD_W - PAD * 2, 36,
                                   "LOBBY NAME (OPTIONAL)")
    S.max_players_stepper = Stepper(LEFT_X, CARD_Y + 176, 200, 34, "PLAYERS", 2, 2, 4)
    S.name_inputs = [
        TextInput(LEFT_X,  CARD_Y + 240, COL_W, 34, "P1 NAME"),
        TextInput(RIGHT_X, CARD_Y + 240, COL_W, 34, "P2 NAME"),
        TextInput(LEFT_X,  CARD_Y + 296, COL_W, 34, "P3 NAME"),
        TextInput(RIGHT_X, CARD_Y + 296, COL_W, 34, "P4 NAME"),
    ]
    S.setup_confirm_btn = Button(CENTER_X - 130, CARD_Y + 340, 260, 46, "CONFIRM")

    # single flat main menu — one screen, one choice
    MW = 320
    MX = CENTER_X - MW // 2
    y0, bh, gap = CARD_Y + 36, 42, 10
    def _mb(i, label):
        return Button(MX, y0 + i * (bh + gap), MW, bh, label)
    S.single_btn = _mb(0, "SINGLE PLAYER")
    S.local_btn = _mb(1, "LOCAL CO-OP")
    S.join_btn = _mb(2, "JOIN GAME")
    S.host_btn = _mb(3, "HOST GAME")
    S.settings_btn = _mb(4, "SETTINGS")
    S.quit_btn = _mb(5, "QUIT")

    S.close_btn = IconButton(cfg.WIDTH - 42, 14, 30, kind="close")  # quits the app
    S.panel_x = IconButton(CARD.right - 42, CARD_Y + 12, 28, kind="close")  # closes current panel

    sx = SETTINGS_RECT.x + 74  # sliders start right of their icons
    S.volume_slider = Slider(sx, SETTINGS_RECT.y + 108, 210,
                             value=cfg.MUSIC_VOLUME, label="MUSIC")
    S.sound_slider = Slider(sx, SETTINGS_RECT.y + 162, 210, value=0.6, label="SOUND")
    S.music_icon = _load_icon(os.path.join(S.ASSETS_DIR, "music.png"), 26)
    S.sound_icon = _load_icon(os.path.join(S.ASSETS_DIR, "sound.png"), 26)
    S.music_toggle = Toggle(SETTINGS_RECT.x + 40, SETTINGS_RECT.y + 214, 56, 28, "MUTE", value=False)

    transport_y = SETTINGS_RECT.y + 306
    tw, th, tgap, mid_w = 100, 40, 16, 140
    total = tw * 2 + mid_w + tgap * 2
    tx = SETTINGS_RECT.centerx - total // 2
    S.prev_btn = Button(tx, transport_y, tw, th, "PREV")
    S.play_pause_btn = Button(S.prev_btn.rect.right + tgap, transport_y, mid_w, th, "PAUSE")
    S.next_btn = Button(S.play_pause_btn.rect.right + tgap, transport_y, tw, th, "NEXT")
    S.settings_close_btn = Button(SETTINGS_RECT.centerx - 80, SETTINGS_RECT.bottom - 52, 160, 40, "CLOSE")
    S.settings_x = IconButton(SETTINGS_RECT.right - 40, SETTINGS_RECT.y + 12, 26, kind="close")

    S.MENU_FOCUS = [S.single_btn, S.local_btn, S.join_btn, S.host_btn,
                    S.settings_btn, S.quit_btn]


def init(S):
    """First-time setup. Creates everything, including persistent state."""
    _build_fonts(S)
    _build_ui(S)
    S.starfield = Starfield(cfg.WIDTH, cfg.HEIGHT)

    S.state = STATE_MENU
    S.room_code = ""
    S.lobby_name = ""
    S.max_players = 2
    S.player_count = 1
    S.status_msg = ""
    S.last_rtt = None
    S.ping_count = 0
    S.pong_count = 0
    S.last_ping_time = 0.0
    S.last_pong_time = 0.0
    S.setup_mode = "single"    # "single", "join" or "host"
    S.local_players = []       # list of [wx, wy] world-pixel positions on the map
    S.local_names = []         # per-player usernames, parallel to local_players
    S.username = ""            # this client's name (host / join)

    # the endless isometric dirt world every mode is played on
    S.iso = iso.Iso(seed=1337, scale=2, view=(cfg.WIDTH, cfg.HEIGHT))
    S.me = [0.0, 0.0, 0.0, 0.0]   # this client's avatar (online), grid cell fx,fy,z,vz
    S.peers = {}                  # id -> {"p":[fx,fy,z], "name":str, "color":rgb, "seen":t}
    S.client_id = ""              # unique per session (name#rand)
    S.last_pos_sent = 0.0

    # chat (Minecraft-style) + push-to-talk voice
    S.chat_open = False
    S.chat_input = ""
    S.chat_log = []               # list of {"t":ts, "name":str, "color":rgb, "text":str}
    S.voice = voicelib.Voice()
    S.show_keys = False           # keybinds panel
    load_game_icons(S)

    S.focus_index = 0  # PLAY focused by default
    S.using_controller = False
    S.show_settings = False

    S.music_track_index = -1
    S.music_volume = cfg.MUSIC_VOLUME
    S.sound_volume = S.sound_slider.value
    S.music_muted = False
    S.music_paused = False
    play_next_track(S)


def rebuild(S):
    """Called after a hot reload. Rebuilds fonts/widgets/visuals from the new
    code, but preserves the live session: connection, music, game state, and
    the values the user has typed/adjusted."""
    vals = {
        "addr": S.addr_input.value, "code": S.code_input.value,
        "names": [n.value for n in S.name_inputs],
        "lobby": S.lobby_name_input.value, "maxp": S.max_players_stepper.value,
        "vol": S.volume_slider.value, "svol": S.sound_slider.value,
        "mute": S.music_toggle.value,
    }
    _build_fonts(S)
    _build_ui(S)
    load_game_icons(S)
    S.starfield = Starfield(cfg.WIDTH, cfg.HEIGHT)
    S.addr_input.value = vals["addr"]
    S.code_input.value = vals["code"]
    for inp, v in zip(S.name_inputs, vals["names"]):
        inp.value = v
    S.lobby_name_input.value = vals["lobby"]
    S.max_players_stepper.value = vals["maxp"]
    S.volume_slider.value = vals["vol"]
    S.sound_slider.value = vals["svol"]
    S.music_toggle.value = vals["mute"]


# --- actions ---
def activate_focused(S):
    widget = S.MENU_FOCUS[S.focus_index]
    if widget is S.settings_btn:
        return "settings"
    elif widget is S.quit_btn:
        return "quit"
    for btn, mode in ((S.single_btn, "single"), (S.local_btn, "local"),
                      (S.join_btn, "join"), (S.host_btn, "host")):
        if widget is btn:
            go_setup(S, mode)
    return None


def go_back(S):
    """Per-panel close (X): back out to the main menu."""
    if S.state == STATE_SETUP:
        S.state = STATE_MENU
    else:
        reset_to_menu(S, "")


def setup_name_count(S):
    return max(2, min(S.max_players_stepper.value, LOCAL_MAX))


def go_setup(S, mode):
    S.setup_mode = mode
    S.max_players_stepper.hi = LOCAL_MAX
    S.max_players_stepper.value = min(S.max_players_stepper.value, S.max_players_stepper.hi)
    S.status_msg = ""
    S.state = STATE_SETUP


def reset_to_menu(S, message):
    S.conn.close()
    S.state = STATE_MENU
    S.status_msg = message
    S.last_rtt = None
    S.ping_count = S.pong_count = 0


def do_host(S):
    addr = S.addr_input.value.strip()
    if not addr:
        S.status_msg = "Enter a server address first."
        return
    S.room_code = ""
    S.username = S.name_inputs[0].value.strip() or "Host"
    enter_world(S)
    S.conn.connect(addr, {
        "type": "host",
        "lobby_name": S.lobby_name_input.value.strip(),
        "max_players": S.max_players_stepper.value,
        "username": S.username,
    })
    S.status_msg = "Connecting..."
    S.state = STATE_WAIT


def do_join(S):
    addr = S.addr_input.value.strip()
    code = S.code_input.value.strip().upper()
    if not addr:
        S.status_msg = "Enter a server address first."
        return
    if not code:
        S.status_msg = "Enter a room code first."
        return
    S.room_code = ""
    S.username = S.name_inputs[0].value.strip() or "Player"
    enter_world(S)
    S.conn.connect(addr, {"type": "join", "code": code, "username": S.username})
    S.status_msg = "Joining..."
    S.state = STATE_WAIT


def do_single(S):
    S.lobby_name = "Single Player"
    fx, fy = S.iso.find_free(0.0, 0.0)
    S.local_players = [[fx, fy, 0.0, 0.0]]
    S.local_names = [S.name_inputs[0].value.strip() or "P1"]
    snap_camera(S, fx, fy)
    S.status_msg = ""
    S.state = STATE_LOCAL


def do_local(S):
    n = max(2, min(S.max_players_stepper.value, LOCAL_MAX))
    S.lobby_name = S.lobby_name_input.value.strip() or "Local Co-op"
    S.local_players = []
    S.local_names = []
    # fan the party out around the origin, each on a free (non-solid) cell
    for i in range(n):
        ang = (i / n) * 6.28318
        fx, fy = S.iso.find_free(math.cos(ang) * 3, math.sin(ang) * 3)
        S.local_players.append([fx, fy, 0.0, 0.0])
        S.local_names.append(S.name_inputs[i].value.strip() or f"P{i+1}")
    snap_camera(S, *centroid(S.local_players))
    S.status_msg = ""
    S.state = STATE_LOCAL


# --- world play helpers (shared by single / local / online) ---
def iso_move(S, p, up, down, left, right, dt):
    """Walk the isometric grid axes with collision: up=NE, down=SW, left=NW,
    right=SE. Props (rocks/logs/boulders) are solid — you slide along them,
    unless you're mid-jump, in which case you clear them."""
    dgx = dgy = 0.0
    if up:    dgy -= 1   # north-east
    if down:  dgy += 1   # south-west
    if left:  dgx -= 1   # north-west
    if right: dgx += 1   # south-east
    if not (dgx or dgy):
        return
    L = math.hypot(dgx, dgy)
    step = SPEED_CELLS * dt
    dgx = dgx / L * step
    dgy = dgy / L * step
    iso = S.iso
    airborne = p[2] > JUMP_CLEAR
    if airborne or not iso.solid(p[0] + dgx, p[1] + dgy):
        p[0] += dgx
        p[1] += dgy
    else:  # blocked head-on — try sliding along each axis
        if not iso.solid(p[0] + dgx, p[1]):
            p[0] += dgx
        if not iso.solid(p[0], p[1] + dgy):
            p[1] += dgy


def apply_jump(p, dt):
    """p is [wx, wy, z, vz]; integrate the hop and land on the ground plane."""
    p[3] -= GRAVITY * dt
    p[2] += p[3] * dt
    if p[2] <= 0.0:
        p[2] = 0.0
        p[3] = 0.0


def try_jump(p):
    if p[2] <= 0.0:            # only when grounded
        p[3] = JUMP_V


def centroid(points):
    n = len(points) or 1
    return sum(p[0] for p in points) / n, sum(p[1] for p in points) / n


def draw_avatar(S, p, color, name, me=False):
    """A rover on the terrain at grid cell [fx, fy, z, vz]; z lifts it mid-jump."""
    screen = S.screen
    fx, fy, z = p[0], p[1], p[2]
    PR = max(6, int(PLAYER_R * S.iso.scale / 2))   # scale the body with zoom
    wx, wy = S.iso.world_px(fx, fy)
    sx, sy = S.iso.to_screen(wx, wy)
    sy -= S.iso.elev(fx, fy)                       # follow the tile elevation
    if sx < -60 or sx > cfg.WIDTH + 60 or sy < -60 or sy > cfg.HEIGHT + 120:
        return
    # ground shadow stays on the tile; it shrinks as you rise
    shr = max(0.4, 1.0 - z / 160.0)
    sw, sh = int((PR * 2 + 4) * shr), int((PR + 2) * shr)
    shadow = pygame.Surface((sw, sh), pygame.SRCALPHA)
    pygame.draw.ellipse(shadow, (0, 0, 0, 90), shadow.get_rect())
    screen.blit(shadow, (int(sx) - sw // 2, int(sy) - sh // 2))
    ix, iy = int(sx), int(sy - PR - z)             # body lifted by jump height
    pygame.draw.circle(screen, color, (ix, iy), PR)
    pygame.draw.circle(screen, (245, 250, 255) if me else (12, 14, 18), (ix, iy), PR, 2)
    pygame.draw.circle(screen, (255, 255, 255), (ix - PR // 4, iy - PR // 4), max(2, PR // 4))
    if name:
        draw_text(screen, name, S.small_font, 0, iy - PR - 18, color, center_x=ix)


def follow_camera(S, fx, fy, dt):
    """Ease the camera toward centering grid cell (fx, fy)."""
    wx, wy = S.iso.world_px(fx, fy)
    tx = wx - cfg.WIDTH // 2
    ty = wy - cfg.HEIGHT // 2
    k = min(1.0, CAM_SMOOTH * dt)
    S.iso.cam_x += (tx - S.iso.cam_x) * k
    S.iso.cam_y += (ty - S.iso.cam_y) * k


def snap_camera(S, fx, fy):
    """Instantly center on a grid cell (used after a zoom change)."""
    S.iso.center_on(*S.iso.world_px(fx, fy))


def zoom(S, delta):
    """Zoom in/out around whoever the camera is following."""
    focus = S.me if S.state == STATE_TEST else (
        centroid(S.local_players) if S.local_players else (0, 0))
    if S.iso.set_scale(S.iso.scale + delta):
        snap_camera(S, focus[0], focus[1])


def enter_world(S):
    """Drop this client's avatar onto the map (online modes)."""
    import random
    S.me = list(S.iso.find_free(0.0, 0.0)) + [0.0, 0.0]   # fx, fy, z, vz
    S.peers = {}
    S.client_id = f"{S.username}#{random.randint(1000, 9999)}"
    snap_camera(S, S.me[0], S.me[1])


def send_chat(S, text):
    """Post a chat line: always echo locally; broadcast when online."""
    text = text.strip()
    if not text:
        return
    name = S.username or (S.local_names[0] if S.local_names else "You")
    color = color_for(name)
    S.chat_log.append({"t": time.time(), "name": name, "color": color, "text": text})
    if S.state == STATE_TEST:
        try:
            S.conn.send({"type": "chat", "id": S.client_id, "name": name,
                         "color": list(color), "text": text[:180]})
        except Exception:
            pass


def prune_peers(S, now):
    for pid in [k for k, v in S.peers.items() if now - v["seen"] > PEER_TIMEOUT]:
        del S.peers[pid]


def draw_world_hud(S, lines, hint):
    screen = S.screen
    pad = 10
    surf = [S.small_font.render(ln, True, cfg.WHITE) for ln in lines]
    w = max((s.get_width() for s in surf), default=0) + pad * 2
    h = pad * 2 + len(surf) * 20
    panel = pygame.Surface((w, h), pygame.SRCALPHA)
    panel.fill((6, 10, 14, 180))
    pygame.draw.rect(panel, cfg.CARD_BORDER, panel.get_rect(), 1, border_radius=8)
    screen.blit(panel, (12, 12))
    for i, s in enumerate(surf):
        screen.blit(s, (12 + pad, 12 + pad + i * 20))
    if hint:
        draw_text(screen, hint, S.small_font, 0, cfg.HEIGHT - 30, cfg.GOLD_FAINT,
                  center_x=cfg.WIDTH // 2)


def load_game_icons(S):
    """Slice the Xbox controller sheet (12px grid) into named button icons and
    load the background-free UI glyphs. Both degrade to empty dicts on failure."""
    S.pad = {}
    try:
        sheet = pygame.image.load(
            os.path.join(S.ASSETS_DIR, "controller", "xbox.png")).convert_alpha()
        coords = {"X": (0, 12), "Y": (0, 24), "B": (0, 36), "A": (0, 48), "MENU": (0, 60),
                  "LB": (36, 24), "RB": (48, 24), "LT": (60, 24), "RT": (72, 24)}
        for k, (x, y) in coords.items():
            ic = sheet.subsurface(pygame.Rect(x, y, 12, 12)).copy()
            S.pad[k] = pygame.transform.scale(ic, (26, 26))
    except Exception as e:
        print(f"[icons] controller sheet: {e}")
    S.uicons = {}
    uidir = os.path.join(S.ASSETS_DIR, "ui")
    try:
        for fn in os.listdir(uidir):
            if fn.endswith(".png"):
                ic = pygame.image.load(os.path.join(uidir, fn)).convert_alpha()
                S.uicons[fn[:-4]] = pygame.transform.scale(ic, (22, 22))
    except Exception as e:
        print(f"[icons] ui glyphs: {e}")


def draw_mic(screen, cx, cy, h, color, active=True):
    """Vector microphone glyph, centered on (cx, cy)."""
    bw = max(6, int(h * 0.44))
    bh = int(h * 0.68)
    body = pygame.Rect(0, 0, bw, bh)
    body.center = (cx, cy - int(h * 0.14))
    pygame.draw.rect(screen, color, body, border_radius=bw // 2)
    pygame.draw.rect(screen, (12, 14, 18), body, 2, border_radius=bw // 2)
    # stand + base
    base_y = cy + int(h * 0.46)
    pygame.draw.line(screen, color, (cx, body.bottom - 1), (cx, base_y), 3)
    pygame.draw.line(screen, color, (cx - bw, base_y), (cx + bw, base_y), 3)
    if active:                                   # symmetric sound waves either side
        for r in (bw + 5, bw + 11):
            box = (cx - r, body.centery - r, r * 2, r * 2)
            pygame.draw.arc(screen, color, box, -0.7, 0.7, 2)            # right
            pygame.draw.arc(screen, color, box, math.pi - 0.7, math.pi + 0.7, 2)  # left


def draw_chat(S, now):
    """Minecraft-style chat: recent lines bottom-left, fading when closed; an
    input box appears while typing."""
    screen = S.screen
    x = 12
    input_h = 26
    bottom = cfg.HEIGHT - 44 - (input_h + 6 if S.chat_open else 0)
    line_h = 18
    shown = [m for m in S.chat_log[-9:]
             if S.chat_open or (now - m["t"]) < CHAT_FADE]
    for k, m in enumerate(reversed(shown)):
        age = now - m["t"]
        if S.chat_open:
            alpha = 255
        else:
            alpha = 255 if age < CHAT_FADE - 1.5 else int(255 * max(0.0, (CHAT_FADE - age) / 1.5))
        y = bottom - k * line_h
        name = f"{m['name']}: "
        nsurf = S.small_font.render(name, True, m["color"])
        tsurf = S.small_font.render(m["text"], True, cfg.WHITE)
        w = nsurf.get_width() + tsurf.get_width() + 12
        strip = pygame.Surface((w, line_h), pygame.SRCALPHA)
        strip.fill((6, 10, 14, int(alpha * 0.55)))
        nsurf.set_alpha(alpha); tsurf.set_alpha(alpha)
        strip.blit(nsurf, (6, 1)); strip.blit(tsurf, (6 + nsurf.get_width(), 1))
        screen.blit(strip, (x, y - line_h))
    if S.chat_open:
        box = pygame.Rect(x, cfg.HEIGHT - 44 - input_h, cfg.WIDTH - 24, input_h)
        panel = pygame.Surface(box.size, pygame.SRCALPHA)
        panel.fill((6, 10, 14, 210))
        pygame.draw.rect(panel, cfg.GOLD, panel.get_rect(), 1)
        screen.blit(panel, box.topleft)
        caret = "_" if int(now * 2) % 2 == 0 else " "
        draw_text(screen, "> " + S.chat_input + caret, S.font, box.x + 8, box.y + 4, cfg.WHITE)


# action, key label, ui-glyph name (or "mic"/None), controller button (or None)
KEYBINDS = [
    ("Move (isometric)", "WASD / Arrows", None, None),
    ("Jump", "Space", "up", "A"),
    ("Zoom in / out", "+ / -  ·  wheel", None, None),
    ("Open chat", "T  /  Enter", None, None),
    ("Push-to-talk", "hold V", "mic", None),
    ("Switch tilemap", "Tab", "redo", "Y"),
    ("Regenerate world", "R", "gear", None),
    ("Confirm (menus)", "Enter", "check", "A"),
    ("Back / Menu", "Esc", "back", "B"),
    ("Fullscreen", "F11", None, None),
    ("Keybinds", "F1", "menu", "MENU"),
    ("Quit", "window  X", "close", None),
]


def keybinds_rect():
    w, h = 500, 96 + len(KEYBINDS) * 30
    return pygame.Rect(cfg.WIDTH // 2 - w // 2, cfg.HEIGHT // 2 - h // 2, w, h)


def draw_keybinds(S, now):
    screen = S.screen
    overlay = pygame.Surface((cfg.WIDTH, cfg.HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 150))
    screen.blit(overlay, (0, 0))
    rect = keybinds_rect()
    draw_card(screen, rect)
    icon = S.uicons.get("menu")
    tx = rect.x + 28
    if icon:
        screen.blit(icon, (rect.x + 22, rect.y + 20)); tx = rect.x + 52
    draw_text(screen, "KEYBINDS", S.big_font, tx, rect.y + 20, cfg.GOLD)
    draw_divider(screen, rect.x + 24, rect.y + 58, rect.w - 48)
    y = rect.y + 74
    for action, keylabel, glyph, pad in KEYBINDS:
        draw_text(screen, action, S.font, rect.x + 28, y, cfg.WHITE)
        # right-aligned: [pad icon] [glyph] key-chip
        rx = rect.right - 28
        chip = S.small_font.render(keylabel, True, cfg.GOLD)
        cw = chip.get_width() + 16
        chip_rect = pygame.Rect(rx - cw, y - 1, cw, 22)
        pygame.draw.rect(screen, cfg.INPUT_BG, chip_rect, border_radius=6)
        pygame.draw.rect(screen, cfg.INPUT_BORDER, chip_rect, 1, border_radius=6)
        screen.blit(chip, (chip_rect.x + 8, chip_rect.y + 3))
        rx = chip_rect.x - 8
        if pad and S.pad.get(pad):
            rx -= 26; screen.blit(S.pad[pad], (rx, y - 3))
        if glyph == "mic":
            rx -= 24; draw_mic(screen, rx + 8, y + 9, 16, cfg.GOLD, active=False)
        elif glyph and S.uicons.get(glyph):
            rx -= 24; screen.blit(S.uicons[glyph], (rx, y - 1))
        y += 30
    draw_text(screen, "F1 / Esc to close", S.small_font, 0, rect.bottom - 26,
              cfg.GOLD_FAINT, center_x=rect.centerx)


def draw_header(S, subtitle):
    screen = S.screen
    draw_glow_text(screen, "SPACE TYCOON", S.brand_font, 0, 36, cfg.GOLD, cfg.GOLD, center_x=CENTER_X)
    draw_text(screen, subtitle, S.small_font, 0, 92, cfg.GOLD_DIM, center_x=CENTER_X)
    draw_divider(screen, CENTER_X - 180, 118, 360)


def draw_footer(S):
    screen = S.screen
    if S.using_controller:
        draw_text(screen, "Gamepad: D-pad move · A confirm · B back", S.small_font,
                  0, cfg.HEIGHT - 32, cfg.GOLD_FAINT, center_x=CENTER_X)
    else:
        draw_text(screen, "WebSocket relay over Fly.io — encrypted (wss://)", S.small_font,
                  0, cfg.HEIGHT - 32, cfg.GOLD_FAINT, center_x=CENTER_X)


def frame(S, events, dt, now):
    """One iteration: handle events, update, draw. Returns False to quit."""
    running = True

    for event in events:
        if event.type == pygame.QUIT:
            running = False

        # --- keybinds panel: F1 toggles; swallow all input while it's open ---
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
            S.show_keys = not S.show_keys
            continue
        if S.show_keys:
            if event.type == pygame.MOUSEBUTTONDOWN or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                S.show_keys = False
            continue

        if event.type == pygame.MOUSEBUTTONDOWN and not S.show_settings and S.close_btn.clicked(event.pos):
            running = False
            continue

        # per-panel close (X) at the card corner backs out one level
        if (event.type == pygame.MOUSEBUTTONDOWN and not S.show_settings
                and S.state != STATE_MENU and S.panel_x.clicked(event.pos)):
            go_back(S)
            continue

        if event.type == S.MUSIC_END_EVENT:
            play_next_track(S)

        if event.type == pygame.JOYDEVICEADDED:
            try:
                joy = pygame.joystick.Joystick(event.device_index)
                joy.init()
                print(f"[gamepad] connected: {joy.get_name()}")
            except Exception as e:
                print(f"[gamepad] init failed: {e}")

        if event.type in (pygame.JOYHATMOTION, pygame.JOYBUTTONDOWN):
            S.using_controller = True

        if event.type == pygame.JOYHATMOTION:
            hx, hy = event.value
            if S.show_settings:
                if hx == -1:
                    S.volume_slider.value = max(0.0, S.volume_slider.value - 0.05)
                    apply_volume(S)
                elif hx == 1:
                    S.volume_slider.value = min(1.0, S.volume_slider.value + 0.05)
                    apply_volume(S)
            elif S.state == STATE_MENU:
                if hy == -1:
                    S.focus_index = (S.focus_index + 1) % len(S.MENU_FOCUS)
                elif hy == 1:
                    S.focus_index = (S.focus_index - 1) % len(S.MENU_FOCUS)

        if event.type == pygame.JOYBUTTONDOWN:
            if event.button == JOYSTICK_A:
                if S.show_settings:
                    S.music_toggle.value = not S.music_toggle.value
                    apply_volume(S)
                elif S.state == STATE_MENU:
                    res = activate_focused(S)
                    if res == "settings":
                        S.show_settings = True
                    elif res == "quit":
                        running = False
            elif event.button == JOYSTICK_B and S.show_settings:
                S.show_settings = False

        if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
            S.using_controller = False

        if S.show_settings:
            if event.type == pygame.MOUSEBUTTONDOWN:
                grabbed = (S.volume_slider.handle_mousedown(event.pos)
                           or S.sound_slider.handle_mousedown(event.pos))
                if grabbed:
                    apply_volume(S)
                elif S.settings_x.clicked(event.pos) or S.settings_close_btn.clicked(event.pos) \
                        or not SETTINGS_RECT.collidepoint(event.pos):
                    S.show_settings = False
                elif S.music_toggle.clicked(event.pos):
                    S.music_toggle.value = not S.music_toggle.value
                    apply_volume(S)
                elif S.prev_btn.clicked(event.pos):
                    play_prev_track(S)
                elif S.play_pause_btn.clicked(event.pos):
                    toggle_play_pause(S)
                elif S.next_btn.clicked(event.pos):
                    play_next_track(S)
            elif event.type == pygame.MOUSEBUTTONUP:
                S.volume_slider.handle_mouseup()
                S.sound_slider.handle_mouseup()
            elif event.type == pygame.MOUSEMOTION:
                S.volume_slider.handle_mousemotion(event.pos)
                S.sound_slider.handle_mousemotion(event.pos)
                if S.volume_slider.dragging or S.sound_slider.dragging:
                    apply_volume(S)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                S.show_settings = False
            continue

        # --- MAIN menu: one flat screen ---
        if event.type == pygame.MOUSEBUTTONDOWN and S.state == STATE_MENU:
            if S.single_btn.clicked(event.pos):
                go_setup(S, "single")
            elif S.local_btn.clicked(event.pos):
                go_setup(S, "local")
            elif S.join_btn.clicked(event.pos):
                go_setup(S, "join")
            elif S.host_btn.clicked(event.pos):
                go_setup(S, "host")
            elif S.settings_btn.clicked(event.pos):
                S.show_settings = True
            elif S.quit_btn.clicked(event.pos):
                running = False

        # --- SETUP panel: per-mode fields, then confirm ---
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN) and S.state == STATE_SETUP:
            mode = S.setup_mode
            online = mode in ("join", "host")
            shown = range(setup_name_count(S)) if mode == "local" else range(1)
            if event.type == pygame.MOUSEBUTTONDOWN:
                if online:
                    S.addr_input.handle_click(event.pos)
                if mode == "join":
                    S.code_input.handle_click(event.pos)
                elif mode in ("host", "local"):
                    S.lobby_name_input.handle_click(event.pos)
                    S.max_players_stepper.handle_click(event.pos)
                for i in shown:
                    S.name_inputs[i].handle_click(event.pos)
                if S.setup_confirm_btn.clicked(event.pos):
                    {"single": do_single, "join": do_join,
                     "host": do_host, "local": do_local}[mode](S)
            else:
                if online:
                    S.addr_input.handle_key(event)
                if mode == "join":
                    S.code_input.handle_key(event)
                elif mode in ("host", "local"):
                    S.lobby_name_input.handle_key(event)
                for i in shown:
                    S.name_inputs[i].handle_key(event)

        # --- chat (Minecraft-style): T / Enter opens, keys are swallowed while open ---
        chat_ok = S.state == STATE_TEST or (S.state == STATE_LOCAL and len(S.local_players) == 1)
        if S.chat_open and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                send_chat(S, S.chat_input); S.chat_input = ""; S.chat_open = False
            elif event.key == pygame.K_ESCAPE:
                S.chat_open = False; S.chat_input = ""
            elif event.key == pygame.K_BACKSPACE:
                S.chat_input = S.chat_input[:-1]
            elif event.unicode and event.unicode.isprintable() and len(S.chat_input) < 180:
                S.chat_input += event.unicode
            continue
        if (event.type == pygame.KEYDOWN and chat_ok and not S.chat_open
                and event.key in (pygame.K_RETURN, pygame.K_t)):
            S.chat_open = True; S.chat_input = ""
            continue

        # --- push-to-talk voice (hold V, online) ---
        if S.state == STATE_TEST and not S.chat_open:
            if event.type == pygame.KEYDOWN and event.key == VOICE_KEY:
                S.voice.start_talk()
            elif event.type == pygame.KEYUP and event.key == VOICE_KEY:
                S.voice.stop_talk()

        # --- in-world controls: jump, switch tilemap (Tab), regen (R), zoom ---
        if event.type == pygame.KEYDOWN and S.state in (STATE_LOCAL, STATE_TEST) and not S.chat_open:
            if event.key == pygame.K_TAB:
                S.iso.cycle_theme()
            elif event.key == pygame.K_r:
                import random
                S.iso.reseed(random.randint(1, 2_000_000_000))
            elif event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                zoom(S, +1)
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                zoom(S, -1)
            elif S.state == STATE_TEST and event.key in (pygame.K_SPACE, pygame.K_RSHIFT):
                try_jump(S.me)
            elif S.state == STATE_LOCAL:
                for i in range(len(S.local_players)):
                    if event.key == SCHEMES[i][6]:
                        try_jump(S.local_players[i])
        if event.type == pygame.MOUSEWHEEL and S.state in (STATE_LOCAL, STATE_TEST) \
                and not S.show_settings:
            zoom(S, 1 if event.y > 0 else -1)

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE and S.state != STATE_MENU:
            go_back(S)
        if event.type == pygame.JOYBUTTONDOWN and event.button == JOYSTICK_B and S.state != STATE_MENU:
            go_back(S)

    # --- keep the playlist cycling ---
    # the MUSIC_END_EVENT above handles it on most builds, but some SDL setups
    # never post it, so also advance when the track has simply stopped playing.
    # (get_busy() is False while paused too, hence the music_paused guard)
    if cfg.MUSIC_TRACKS and not S.music_paused and not pygame.mixer.music.get_busy():
        play_next_track(S)

    # --- incoming network messages ---
    try:
        while True:
            msg = S.conn.incoming.get_nowait()
            t = msg.get("type")
            if t == "hosted":
                S.room_code = msg["code"]
                S.lobby_name = msg.get("lobby_name", "")
                S.max_players = msg.get("max_players", 2)
                S.player_count = msg.get("player_count", 1)
                S.status_msg = "Room created — waiting for your friend..."
                S.last_pong_time = now
            elif t == "joined":
                S.room_code = msg["code"]
                S.lobby_name = msg.get("lobby_name", "")
                S.max_players = msg.get("max_players", 2)
                S.player_count = msg.get("player_count", 2)
                S.status_msg = "Joined — waiting for host..."
                S.last_pong_time = now
            elif t == "peer_joined":
                S.player_count = msg.get("player_count", S.player_count + 1)
                S.status_msg = "Peer connected!"
                S.state = STATE_TEST
                S.last_pong_time = now
            elif t == "peer_left":
                S.player_count = msg.get("player_count", max(1, S.player_count - 1))
                S.status_msg = f"A player disconnected ({S.player_count}/{S.max_players} remaining)."
            elif t == "pos":
                pid = msg.get("id", msg.get("name", "peer"))
                nm = msg.get("name", "Peer") or "Peer"
                col = tuple(msg["color"]) if msg.get("color") else color_for(nm)
                S.peers[pid] = {"p": [msg["x"], msg["y"], msg.get("z", 0.0)],
                                "name": nm, "color": col, "seen": now}
            elif t == "chat":
                nm = msg.get("name", "Peer") or "Peer"
                col = tuple(msg["color"]) if msg.get("color") else color_for(nm)
                S.chat_log.append({"t": now, "name": nm, "color": col,
                                   "text": str(msg.get("text", ""))[:180]})
            elif t == "voice":
                S.voice.push_incoming(msg.get("d", ""))
            elif t == "ping":
                S.conn.send({"type": "pong", "t": msg["t"]})
                S.pong_count += 1
            elif t == "pong":
                S.last_rtt = (now - msg["t"]) * 1000
                S.last_pong_time = now
                if S.state == STATE_WAIT:
                    S.state = STATE_TEST
            elif t == "error":
                reset_to_menu(S, f"Error: {msg['msg']}")
            elif t == "connect_error":
                reset_to_menu(S, msg["error"])
            elif t == "disconnected":
                reset_to_menu(S, "Disconnected from server.")
    except queue.Empty:
        pass

    if S.state == STATE_TEST:
        prune_peers(S, now)
        # walk the shared map; WASD + arrows both drive your own avatar
        keys = pygame.key.get_pressed()
        if not S.chat_open:
            up = keys[pygame.K_w] or keys[pygame.K_UP]
            down = keys[pygame.K_s] or keys[pygame.K_DOWN]
            left = keys[pygame.K_a] or keys[pygame.K_LEFT]
            right = keys[pygame.K_d] or keys[pygame.K_RIGHT]
            iso_move(S, S.me, up, down, left, right, dt)
        apply_jump(S.me, dt)
        follow_camera(S, S.me[0], S.me[1], dt)

        # relay any captured voice chunks to the room
        for chunk in S.voice.poll_outgoing():
            try:
                S.conn.send({"type": "voice", "d": chunk})
            except Exception:
                pass
        if now - S.last_pos_sent > 1.0 / POS_SEND_HZ:
            try:
                S.conn.send({"type": "pos", "id": S.client_id, "name": S.username,
                             "color": list(color_for(S.username)),
                             "x": round(S.me[0], 2), "y": round(S.me[1], 2),
                             "z": round(S.me[2], 1)})
                S.last_pos_sent = now
            except Exception:
                reset_to_menu(S, "Send failed — connection lost.")
        if now - S.last_ping_time > cfg.PING_INTERVAL:
            try:
                S.conn.send({"type": "ping", "t": now})
                S.ping_count += 1
                S.last_ping_time = now
            except Exception:
                reset_to_menu(S, "Send failed — connection lost.")
        if S.last_pong_time and now - S.last_pong_time > cfg.CONNECTION_TIMEOUT:
            reset_to_menu(S, f"Connection timed out (no response for {cfg.CONNECTION_TIMEOUT:.0f}s).")

    if S.state == STATE_LOCAL:
        keys = pygame.key.get_pressed()
        for i, p in enumerate(S.local_players):
            _, up, down, left, right, _, _ = SCHEMES[i]
            if S.chat_open:                       # single-player chat freezes movement
                iso_move(S, p, False, False, False, False, dt)
            else:
                iso_move(S, p, keys[up], keys[down], keys[left], keys[right], dt)
            apply_jump(p, dt)
        follow_camera(S, *centroid(S.local_players), dt)

    # --- draw ---
    screen = S.screen
    S.starfield.update(dt)
    screen.fill(cfg.BG)
    S.starfield.draw(screen)
    draw_card(screen, CARD)

    if S.state == STATE_MENU:
        draw_header(S, "Connectivity Tester")
        for btn in (S.single_btn, S.local_btn, S.join_btn, S.host_btn):
            btn.draw(screen, S.font)
        S.settings_btn.draw(screen, S.font)
        S.quit_btn.draw(screen, S.font)
        if S.using_controller:
            draw_focus_ring(screen, S.MENU_FOCUS[S.focus_index].rect)
        if S.status_msg:
            draw_wrapped_text(screen, S.status_msg, S.font, CARD.bottom + 12,
                              cfg.CARD_W - PAD * 2, cfg.RED, center_x=CENTER_X)

    elif S.state == STATE_SETUP and S.setup_mode == "single":
        draw_header(S, "Single Player")
        S.name_inputs[0].label = "YOUR USERNAME"
        S.name_inputs[0].draw(screen, S.font, S.small_font)
        draw_text(screen, "Solo play — move around the play area with WASD.",
                  S.small_font, LEFT_X, CARD_Y + 288, cfg.GOLD_FAINT)
        S.setup_confirm_btn.label = "START"
        S.setup_confirm_btn.draw(screen, S.font)

    elif S.state == STATE_SETUP and S.setup_mode == "join":
        draw_header(S, "Join a Game")
        S.addr_input.draw(screen, S.font, S.small_font)
        S.code_input.draw(screen, S.font, S.small_font)
        S.name_inputs[0].label = "YOUR USERNAME"
        S.name_inputs[0].draw(screen, S.font, S.small_font)
        draw_text(screen, "Enter the 6-character code your friend shared.",
                  S.small_font, LEFT_X, CARD_Y + 288, cfg.GOLD_FAINT)
        S.setup_confirm_btn.label = "JOIN GAME"
        S.setup_confirm_btn.draw(screen, S.font)

    elif S.state == STATE_SETUP and S.setup_mode == "local":
        draw_header(S, "Local Co-op")
        S.lobby_name_input.draw(screen, S.font, S.small_font)
        S.max_players_stepper.draw(screen, S.font, S.small_font)
        n = setup_name_count(S)
        draw_text(screen, "USERNAMES", S.small_font, LEFT_X, CARD_Y + 220, cfg.GOLD_DIM)
        for i in range(n):
            S.name_inputs[i].label = ""
            col = SCHEMES[i][5]
            r = S.name_inputs[i].rect
            pygame.draw.circle(screen, col, (r.x - 10, r.centery), 5)
            draw_text(screen, f"P{i+1}", S.small_font, r.x, r.y - 18, col)
            S.name_inputs[i].draw(screen, S.font, S.small_font)
        S.setup_confirm_btn.label = "START"
        S.setup_confirm_btn.draw(screen, S.font)

    elif S.state == STATE_SETUP:  # host
        draw_header(S, "Host a Game")
        S.addr_input.draw(screen, S.font, S.small_font)
        S.lobby_name_input.draw(screen, S.font, S.small_font)
        S.max_players_stepper.draw(screen, S.font, S.small_font)
        S.name_inputs[0].label = "YOUR USERNAME"
        S.name_inputs[0].draw(screen, S.font, S.small_font)
        S.setup_confirm_btn.label = "HOST GAME"
        S.setup_confirm_btn.draw(screen, S.font)

    elif S.state == STATE_WAIT:
        draw_header(S, S.lobby_name if S.lobby_name else "Standing By")
        draw_wrapped_text(screen, S.status_msg, S.body_font, CARD_Y + 50,
                          cfg.CARD_W - PAD * 2, cfg.WHITE, center_x=CENTER_X)
        if S.room_code:
            draw_text(screen, f"{S.player_count}/{S.max_players} PLAYERS — SHARE THIS CODE",
                      S.small_font, 0, CARD_Y + 120, cfg.GOLD_DIM, center_x=CENTER_X)
            box_w, box_h = 260, 90
            box = pygame.Rect(CENTER_X - box_w // 2, CARD_Y + 150, box_w, box_h)
            alpha = pulse_alpha(now)
            pygame.draw.rect(screen, cfg.INPUT_BG, box, border_radius=12)
            pygame.draw.rect(screen, cfg.GOLD, box, 2, border_radius=12)
            code_surf = S.code_font.render(S.room_code, True, cfg.WHITE)
            code_surf.set_alpha(alpha)
            screen.blit(code_surf, (box.centerx - code_surf.get_width() // 2,
                                    box.centery - code_surf.get_height() // 2))
        else:
            draw_text(screen, "Reaching relay server...", S.small_font,
                      0, CARD_Y + 130, cfg.GOLD_DIM, center_x=CENTER_X)

    elif S.state == STATE_TEST:
        # shared endless world: every player walking the same map
        S.iso.draw(screen)
        crowd = [(pr["p"], pr["color"], pr["name"], False) for pr in S.peers.values()]
        crowd.append((S.me, color_for(S.username), S.username or "You", True))
        for p, col, nm, me in sorted(crowd, key=lambda a: a[0][0] + a[0][1]):  # iso depth
            draw_avatar(S, p, col, nm, me=me)
        # mic sign floating over your head while push-to-talk is held
        if S.voice.talking:
            mx, my = S.iso.to_screen(*S.iso.world_px(S.me[0], S.me[1]))
            my -= S.iso.elev(S.me[0], S.me[1]) + 42 + S.me[2]
            draw_mic(screen, int(mx), int(my), 22, (120, 255, 150))
        # peers who are talking are hard to know per-id; show a room mic flag
        rtt_text = f"{S.last_rtt:.0f} ms" if S.last_rtt is not None else "…"
        talk = "   MIC ON" if S.voice.talking else ""
        draw_world_hud(S, [
            f"ROOM {S.room_code}   {1 + len(S.peers)}/{S.max_players} in view   [{S.iso.theme}]",
            f"RTT {rtt_text}    X {S.me[0]:+.1f}  Y {S.me[1]:+.1f}   {S.iso.scale}x{talk}",
            f"players here: {', '.join([S.username or 'You'] + [p['name'] for p in S.peers.values()])[:60]}",
        ], "WASD walk · Space jump · +/- zoom · T chat · hold V talk · Tab tilemap · F1 keys · Esc")
        if S.voice.talking:
            draw_mic(screen, cfg.WIDTH - 30, 30, 20, (120, 255, 150))
        draw_chat(S, now)

    elif S.state == STATE_LOCAL:
        # same endless world, same screen, up to 4 rovers
        S.iso.draw(screen)
        order = sorted(range(len(S.local_players)),
                       key=lambda i: S.local_players[i][0] + S.local_players[i][1])
        for i in order:
            p = S.local_players[i]
            name = S.local_names[i] if i < len(S.local_names) else f"P{i+1}"
            draw_avatar(S, p, SCHEMES[i][5], name, me=(i == 0))
        title = S.lobby_name if S.lobby_name else "LOCAL CO-OP"
        schemes = "  ".join(f"P{i+1} {SCHEMES[i][0]}" for i in range(len(S.local_players)))
        cx, cy = centroid(S.local_players)
        chat_hint = " · T chat" if len(S.local_players) == 1 else ""
        draw_world_hud(S, [f"{title}   [{S.iso.theme}]   {S.iso.scale}x",
                           f"{len(S.local_players)} rovers   X {cx:+.1f}  Y {cy:+.1f}", schemes],
                       f"move+jump per scheme · +/- zoom · Tab tilemap · R regen{chat_hint} · Esc menu")
        draw_chat(S, now)

    if S.state not in (STATE_TEST, STATE_LOCAL):
        draw_footer(S)
    S.close_btn.draw(screen)
    if S.state != STATE_MENU and not S.show_settings:
        S.panel_x.draw(screen)

    if S.show_settings:
        overlay = pygame.Surface((cfg.WIDTH, cfg.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        screen.blit(overlay, (0, 0))
        draw_card(screen, SETTINGS_RECT)
        draw_text(screen, "SETTINGS", S.big_font, 0, SETTINGS_RECT.y + 24, cfg.GOLD, center_x=CENTER_X)
        draw_divider(screen, SETTINGS_RECT.x + 30, SETTINGS_RECT.y + 66, SETTINGS_RECT.w - 60)

        for slider, icon in ((S.volume_slider, S.music_icon), (S.sound_slider, S.sound_icon)):
            slider.draw(screen, S.font, S.small_font)
            if icon is not None:
                screen.blit(icon, (SETTINGS_RECT.x + 34, slider.rect.centery - 13))
        S.music_toggle.draw(screen, S.small_font)

        draw_text(screen, "NOW PLAYING", S.small_font, SETTINGS_RECT.x + 130, SETTINGS_RECT.y + 220, cfg.GOLD_DIM)
        draw_text(screen, track_display_name(S.music_track_index), S.font,
                  SETTINGS_RECT.x + 130, SETTINGS_RECT.y + 237, cfg.WHITE)

        S.play_pause_btn.label = "PLAY" if S.music_paused else "PAUSE"
        S.prev_btn.draw(screen, S.small_font)
        S.play_pause_btn.draw(screen, S.font)
        S.next_btn.draw(screen, S.small_font)
        S.settings_close_btn.draw(screen, S.font)
        S.settings_x.draw(screen)

    if S.show_keys:
        draw_keybinds(S, now)

    if getattr(S, "reload_flash", 0) > now:
        draw_text(screen, "↻ hot-reloaded", S.small_font, 16, cfg.HEIGHT - 32, cfg.GREEN)

    return running
