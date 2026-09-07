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

STATE_MENU, STATE_SETUP, STATE_WAIT, STATE_TEST, STATE_LOCAL, STATE_WAKE = \
    "menu", "setup", "wait", "test", "local", "wake"

JOYSTICK_A, JOYSTICK_B = 0, 1  # standard Xbox/PlayStation layout button indices
SPEED_CELLS = 5.5  # avatar walk speed in grid cells / sec (zoom-independent)
PLAYER_R = 12
LOCAL_MAX = 4  # same-screen coop supports up to 4 keyboard controllers
POS_SEND_HZ = 6  # online position updates/sec (stays under the relay rate cap)
CAM_SMOOTH = 6.0  # camera easing — lower = smoother/laggier follow
REVEAL_RADIUS = 6  # cells visible around each player (circular fog of war)

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

SETTINGS_W, SETTINGS_H = 680, 560
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
        pygame.mixer.music.play()
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


def update_menu_layout(S):
    if not hasattr(S, "menu_page"):
        S.menu_page = "root"
    if S.menu_page == "root":
        S.MENU_FOCUS = [S.play_btn, S.settings_btn, S.quit_btn]
    elif S.menu_page == "play":
        S.MENU_FOCUS = [S.menu_local_btn, S.menu_online_btn, S.menu_back_btn]
    elif S.menu_page == "online":
        S.MENU_FOCUS = [S.menu_join_btn, S.menu_host_btn, S.menu_back_btn]
    elif S.menu_page == "host":
        S.MENU_FOCUS = [S.host_local_coop_btn, S.host_online_coop_btn, S.menu_back_btn]
    else:
        S.menu_page = "root"
        S.MENU_FOCUS = [S.play_btn, S.settings_btn, S.quit_btn]
        
    S.focus_index = 0
    MW, bh, gap = 260, 34, 6
    MX = 44
    y0 = cfg.HEIGHT - len(S.MENU_FOCUS) * (bh + gap) - 40
    for i, btn in enumerate(S.MENU_FOCUS):
        btn.rect = pygame.Rect(MX, y0 + i * (bh + gap), MW, bh)


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

    def _mb(label):
        return Button(0, 0, 260, 34, label)
    
    S.play_btn = _mb("PLAY")
    S.settings_btn = _mb("SETTINGS")
    S.quit_btn = _mb("QUIT")
    S.menu_local_btn = _mb("LOCAL")
    S.menu_online_btn = _mb("ONLINE")
    S.menu_join_btn = _mb("JOIN")
    S.menu_host_btn = _mb("HOST")
    S.host_local_coop_btn = _mb("LOCAL CO-OP")
    S.host_online_coop_btn = _mb("ONLINE CO-OP")
    S.menu_back_btn = _mb("BACK")

    # in-world pause menu
    PR = pygame.Rect(CENTER_X - 170, cfg.HEIGHT // 2 - 175, 340, 350)
    S.pause_rect = PR
    py0, pbh, pgap = PR.y + 88, 44, 12
    def _pb(i, label):
        return Button(CENTER_X - 120, py0 + i * (pbh + pgap), 240, pbh, label)
    S.pause_resume_btn = _pb(0, "RESUME")
    S.pause_help_btn = _pb(1, "HOW TO PLAY")
    S.pause_settings_btn = _pb(2, "SETTINGS")
    S.pause_quit_btn = _pb(3, "QUIT TO MENU")

    S.close_btn = IconButton(cfg.WIDTH - 42, 14, 30, kind="close")  # quits the app
    S.panel_x = IconButton(CARD.right - 42, CARD_Y + 12, 28, kind="close")  # closes current panel
    S.help_icon_btn = IconButton(cfg.WIDTH - 42, cfg.HEIGHT - 42, 30, kind="help")

    S.music_icon = _load_icon(os.path.join(S.ASSETS_DIR, "music.png"), 26)
    S.sound_icon = _load_icon(os.path.join(S.ASSETS_DIR, "sound.png"), 26)

    # Column 1
    col1_x = SETTINGS_RECT.x + 40
    y = SETTINGS_RECT.y + 110
    S.master_vol_slider = Slider(col1_x, y, 200, value=1.0, label="MASTER VOLUME")
    S.volume_slider = Slider(col1_x, y + 60, 200, value=cfg.MUSIC_VOLUME, label="MUSIC")
    S.sound_slider = Slider(col1_x, y + 120, 200, value=0.6, label="SOUND")
    S.particles_slider = Slider(col1_x, y + 180, 200, value=0.8, label="PARTICLES")
    S.cam_smooth_slider = Slider(col1_x, y + 240, 200, value=0.5, label="CAMERA SMOOTHING")
    
    # Column 2
    col2_x = SETTINGS_RECT.x + 320
    S.render_dist_stepper = Stepper(col2_x, y, 200, 30, "RENDER DISTANCE", 16, 8, 32)
    S.ui_scale_stepper = Stepper(col2_x, y + 60, 200, 30, "UI SCALE", 100, 50, 200)
    S.chunk_sim_toggle = Toggle(col2_x, y + 120, 56, 28, "CHUNK SIMULATIONS", value=True)
    S.fps_toggle = Toggle(col2_x, y + 180, 56, 28, "SHOW FPS", value=False)
    S.vsync_toggle = Toggle(col2_x, y + 240, 56, 28, "V-SYNC", value=True)

    S.music_toggle = Toggle(col1_x, y + 300, 56, 28, "MUTE", value=False)
    S.keybinds_btn = Button(col2_x, y + 295, 200, 36, "KEYBINDS")

    transport_y = SETTINGS_RECT.y + 460
    tw, th, tgap, mid_w = 100, 40, 16, 140
    total = tw * 2 + mid_w + tgap * 2
    tx = SETTINGS_RECT.centerx - total // 2
    S.prev_btn = Button(tx, transport_y, tw, th, "PREV")
    S.play_pause_btn = Button(S.prev_btn.rect.right + tgap, transport_y, mid_w, th, "PAUSE")
    S.next_btn = Button(S.play_pause_btn.rect.right + tgap, transport_y, tw, th, "NEXT")
    S.settings_close_btn = Button(SETTINGS_RECT.centerx - 80, SETTINGS_RECT.bottom - 52, 160, 40, "CLOSE")
    S.settings_x = IconButton(SETTINGS_RECT.right - 40, SETTINGS_RECT.y + 12, 26, kind="close")


    update_menu_layout(S)


def init(S):
    """First-time setup. Creates everything, including persistent state."""
    _build_fonts(S)
    _build_ui(S)
    S.starfield = Starfield(cfg.WIDTH, cfg.HEIGHT)
    # a slowly drifting procedural world used as the menu backdrop
    S.menu_iso = iso.Iso(seed=90210, scale=2, view=(cfg.WIDTH, cfg.HEIGHT))
    S.vignette = ui.make_vignette(cfg.WIDTH, cfg.HEIGHT)
    S.paused = False

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
    S.chat_log = []
    S.lobby_players = {}
    S.is_host = False
    S.lobby_ready = False
    S.lobby_start_btn = None
    S.lobby_ready_btn = None
    S.lobby_kick_btns = {}
    S.lobby_restrict_btns = {}
    S.lobby_player_list = []
               # list of {"t":ts, "name":str, "color":rgb, "text":str}
    S.voice = voicelib.Voice()
    S.show_keys = False           # keybinds panel
    load_game_icons(S)
    load_cursors(S)

    S.focus_index = 0  # PLAY focused by default
    S.using_controller = False
    S.show_settings = False
    S.spawn_cell = None      # original spawn, marked with a pixel-art X
    S.pressed_tile = None    # tile clicked (drawn white)
    S.pressed_until = 0.0    # timestamp the white tile expires (debug: 5s)

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
    load_cursors(S)
    S.starfield = Starfield(cfg.WIDTH, cfg.HEIGHT)
    # backdrop world + vignette persist across reloads; create if this session
    # predates them (first hot-reload after the feature was added)
    if not hasattr(S, "menu_iso"):
        S.menu_iso = iso.Iso(seed=90210, scale=2, view=(cfg.WIDTH, cfg.HEIGHT))
    S.vignette = ui.make_vignette(cfg.WIDTH, cfg.HEIGHT)
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
def update_menu_bg(S, dt):
    """Slowly pan the backdrop world so the menu feels alive."""
    S.menu_iso.cam_x += 15 * dt
    S.menu_iso.cam_y += 7.5 * dt


def activate_focused(S):
    widget = S.MENU_FOCUS[S.focus_index]
    if widget is getattr(S, "settings_btn", None):
        return "settings"
    elif widget is getattr(S, "help_btn", None):
        return "help"
    elif widget is getattr(S, "quit_btn", None):
        return "quit"
    
    if widget is getattr(S, "play_btn", None):
        S.menu_page = "play"
        update_menu_layout(S)
    elif widget is getattr(S, "menu_local_btn", None):
        go_setup(S, "single")
    elif widget is getattr(S, "menu_online_btn", None):
        S.menu_page = "online"
        update_menu_layout(S)
    elif widget is getattr(S, "menu_join_btn", None):
        go_setup(S, "join")
    elif widget is getattr(S, "menu_host_btn", None):
        S.menu_page = "host"
        update_menu_layout(S)
    elif widget is getattr(S, "host_local_coop_btn", None):
        go_setup(S, "local")
    elif widget is getattr(S, "host_online_coop_btn", None):
        start_wake_server(S)
    elif widget is getattr(S, "menu_back_btn", None):
        if S.menu_page == "host":
            S.menu_page = "online"
        elif S.menu_page == "online":
            S.menu_page = "play"
        elif S.menu_page == "play":
            S.menu_page = "root"
        update_menu_layout(S)
        
    return None


def start_wake_server(S):
    S.state = STATE_WAKE
    S.wake_start_time = time.time()
    
    def _ping_server():
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
    threading.Thread(target=_ping_server, daemon=True).start()


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
    S.menu_page = "root"
    update_menu_layout(S)
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
    S.spawn_cell = (fx, fy)
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
        S.local_players.append([fx, fy, 0.0, 0.0, 0.0, 0.0, 0.0])
        S.local_names.append(S.name_inputs[i].value.strip() or f"P{i+1}")
    S.spawn_cell = tuple(centroid(S.local_players))
    snap_camera(S, *centroid(S.local_players))
    S.status_msg = ""
    S.state = STATE_LOCAL


# --- world play helpers (shared by single / local / online) ---
def iso_move(S, p, up, down, left, right, dash, dt):
    """Walk the isometric grid axes with collision and dashing."""
    if len(p) < 7:
        p.extend([0.0, 0.0, 0.0])  # ensure dash state exists
        
    dgx = dgy = 0.0
    if up:    dgy -= 1
    if down:  dgy += 1
    if left:  dgx -= 1
    if right: dgx += 1
    
    if dash and p[4] <= 0 and (dgx or dgy):
        p[4] = 0.8  # cooldown
        L = math.hypot(dgx, dgy)
        p[5] = (dgx / L) * 45.0  # dash burst velocity
        p[6] = (dgy / L) * 45.0
        S.shake = 0.5            # juicy screen shake
        
    if p[4] > 0: p[4] -= dt
    
    # friction on dash velocity
    p[5] *= (0.001 ** dt)
    p[6] *= (0.001 ** dt)
    
    if dgx or dgy:
        L = math.hypot(dgx, dgy)
        step = SPEED_CELLS * dt
        dgx = dgx / L * step
        dgy = dgy / L * step
        
    total_dx = dgx + p[5] * dt
    total_dy = dgy + p[6] * dt
    
    if not (total_dx or total_dy):
        return
        
    iso = S.iso
    airborne = p[2] > JUMP_CLEAR
    nx, ny = p[0] + total_dx, p[1] + total_dy
    
    if airborne or not iso.solid(nx, ny):
        p[0] = nx
        p[1] = ny
    else:
        if not iso.solid(nx, p[1]):
            p[0] = nx
            p[5] = 0  # kill x velocity if walled
        elif not iso.solid(p[0], ny):
            p[1] = ny
            p[6] = 0  # kill y velocity if walled
            
    # Juicy Knockback: If dashing fast, push other local players
    if abs(p[5]) > 10 or abs(p[6]) > 10:
        if hasattr(S, 'local_players'):
            for other in S.local_players:
                if other is not p:
                    dist = math.hypot(other[0] - p[0], other[1] - p[1])
                    if dist < 0.8 and abs(other[2] - p[2]) < 10:  # hit radius
                        other[5] += p[5] * 0.8  # transfer momentum
                        other[6] += p[6] * 0.8
                        p[5] *= 0.2  # slow self down on impact
                        p[6] *= 0.2
                        S.shake = max(S.shake, 0.8)  # bigger shake on hit!


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


def visible_cells(S):
    """Union of circular reveal areas around every on-screen player. Tiles
    outside this set aren't rendered, so the world is discovered as players
    move — locally and (via peer positions) in multiplayer too."""
    if S.state == STATE_TEST:
        pts = [S.me] + [pr["p"] for pr in S.peers.values()]
    else:
        pts = S.local_players
    cells = set()
    R, R2 = REVEAL_RADIUS, REVEAL_RADIUS * REVEAL_RADIUS
    for p in pts:
        cx, cy = round(p[0]), round(p[1])
        for dx in range(-R, R + 1):
            for dy in range(-R, R + 1):
                if dx * dx + dy * dy <= R2:
                    cells.add((cx + dx, cy + dy))
    return cells


def tile_at_screen(S, mx, my):
    """Canvas mouse position -> the grid cell whose (elevated) top-face diamond
    is under the cursor. Tests nearby cells and picks the front-most one so the
    entire visible top face is clickable, not just a quadrant."""
    iso = S.iso
    HW, HH = iso.HALF_W, iso.HALF_H
    base = iso.cell_at(mx + iso.cam_x, my + iso.cam_y)   # flat guess to bound the search
    best = None
    for dgy in range(-3, 4):
        for dgx in range(-3, 4):
            gx, gy = base[0] + dgx, base[1] + dgy
            cx, cy = _tile_anchor(S, gx, gy)            # top-face centre
            if abs(mx - cx) / HW + abs(my - cy) / HH <= 1.0:   # inside the diamond
                key = (gx + gy, iso.world.get(gx, gy)[2])       # front-most, then taller
                if best is None or key > best[0]:
                    best = (key, (gx, gy))
    return best[1] if best else base


def _tile_anchor(S, fx, fy):
    """Screen position of a grid cell's ground center, following elevation."""
    sx, sy = S.iso.to_screen(*S.iso.world_px(fx, fy))
    return int(sx), int(sy - S.iso.elev(fx, fy))


def draw_spawn_marker(S):
    """Draw the tilex1 marker tile on the original spawn cell, seated like a
    normal world tile (position + elevation lift)."""
    cell = getattr(S, "spawn_cell", None)
    img = getattr(S, "spawn_img", None)
    if not cell or not img:
        return
    iso = S.iso
    gx, gy = round(cell[0]), round(cell[1])
    _, _, level = iso.world.get(gx, gy)
    HW, HH = iso.HALF_W, iso.HALF_H
    sx = (gx - gy) * HW - iso.cam_x
    sy = (gx + gy) * HH - iso.cam_y
    oy = sy - level * iso.LIFT
    if sx < -iso.TILE_PX or sx > cfg.WIDTH + iso.TILE_PX or oy < -iso.TILE_PX or oy > cfg.HEIGHT + iso.TILE_PX:
        return
    tile = pygame.transform.scale(img, (iso.TILE_PX, iso.TILE_PX))
    S.screen.blit(tile, (int(sx - HW), int(oy - HH)))


def draw_tile_press(S):
    """While a tile is held (mouse down), recolor only its top face white — the
    cube sides stay untouched (they're hidden when surrounded anyway)."""
    cell = getattr(S, "pressed_tile", None)
    if not cell or time.time() > getattr(S, "pressed_until", 0):
        return
    gx, gy = cell
    iso = S.iso
    base, prop, level = iso.world.get(gx, gy)
    HW, HH, TPX = iso.HALF_W, iso.HALF_H, iso.TILE_PX
    sx = (gx - gy) * HW - iso.cam_x
    sy = (gx + gy) * HH - iso.cam_y
    oy = sy - level * iso.LIFT
    w = iso.tiles[base].copy()
    w.fill((255, 255, 255, 0), special_flags=pygame.BLEND_RGB_MAX)      # opaque -> white
    mask = pygame.Surface((TPX, TPX), pygame.SRCALPHA)                  # top-face diamond only
    pygame.draw.polygon(mask, (255, 255, 255, 255),                     # centred at local 2*HH
                        [(HW, HH), (2 * HW, 2 * HH), (HW, 3 * HH), (0, 2 * HH)])
    w.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)          # keep white only on top face
    S.screen.blit(w, (sx - HW, oy - HH))


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
    S.me = list(S.iso.find_free(0.0, 0.0)) + [0.0, 0.0, 0.0, 0.0, 0.0]   # fx, fy, z, vz, dash_time, dash_x, dash_y
    S.spawn_cell = (S.me[0], S.me[1])
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
        draw_text(screen, hint, S.small_font, 0, cfg.HEIGHT - 90, cfg.GOLD_FAINT,
                  center_x=cfg.WIDTH // 2)

    # --- Draw Hearts (Top Left, below HUD) — pixel-art heart from the pack ---
    heart_img = getattr(S, "heart_img", None)
    HS = 28  # heart draw size (px)
    for i in range(5):
        hx, hy = 16 + i * (HS + 4), h + 24
        if heart_img:
            screen.blit(heart_img, (hx, hy))
        else:
            pygame.draw.circle(screen, cfg.RED, (hx + 7, hy + 7), 7)
            pygame.draw.circle(screen, cfg.RED, (hx + 17, hy + 7), 7)
            pygame.draw.polygon(screen, cfg.RED, [(hx, hy + 10), (hx + 24, hy + 10), (hx + 12, hy + 22)])



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
    # pixel-art heart (crisp nearest-neighbor scale, aspect preserved)
    S.heart_img = None
    try:
        hi = pygame.image.load(os.path.join(S.ASSETS_DIR, "ui", "heart.png")).convert_alpha()
        w, h = hi.get_size()
        S.heart_img = pygame.transform.scale(hi, (28, max(1, round(28 * h / w))))
    except Exception as e:
        print(f"[icons] heart: {e}")
    # spawn-point marker tile (a full cube tile drawn on the spawn cell)
    S.spawn_img = None
    try:
        S.spawn_img = pygame.image.load(
            os.path.join(S.ASSETS_DIR, "tiles", "tilex1.png")).convert_alpha()
    except Exception as e:
        print(f"[icons] tilex1: {e}")
    S.uicons = {}
    uidir = os.path.join(S.ASSETS_DIR, "ui")
    try:
        for fn in os.listdir(uidir):
            if fn.endswith(".png"):
                ic = pygame.image.load(os.path.join(uidir, fn)).convert_alpha()
                S.uicons[fn[:-4]] = pygame.transform.scale(ic, (22, 22))
    except Exception as e:
        print(f"[icons] ui glyphs: {e}")


CURSOR_SCALE = 1.75  # 16px source -> 28px on the canvas
CURSOR_HOTSPOTS = {   # in source (16px) coords, before scaling
    "arrow": (1, 1), "point": (5, 1), "grab": (8, 8),
    "open": (8, 8), "hand": (8, 8), "busy": (8, 8),
}


def load_cursors(S):
    """Load the Kenney pixel cursors and hide the OS cursor so we can draw our
    own on the canvas (scales correctly with the letterbox)."""
    S.cursors = {}
    cdir = os.path.join(S.ASSETS_DIR, "cursors")
    try:
        for name in ("arrow", "point", "open", "grab", "hand", "busy"):
            img = pygame.image.load(os.path.join(cdir, name + ".png")).convert_alpha()
            w, h = img.get_size()
            S.cursors[name] = pygame.transform.scale(
                img, (round(w * CURSOR_SCALE), round(h * CURSOR_SCALE)))
    except Exception as e:
        print(f"[cursors] {e}")
    # full selectable pack — press F2 to cycle your pointer through all of them
    S.cursor_pack = []
    pdir = os.path.join(cdir, "pack")
    try:
        for fn in sorted(os.listdir(pdir)):
            if fn.endswith(".png"):
                img = pygame.image.load(os.path.join(pdir, fn)).convert_alpha()
                w, h = img.get_size()
                S.cursor_pack.append(pygame.transform.scale(
                    img, (round(w * CURSOR_SCALE), round(h * CURSOR_SCALE))))
    except Exception as e:
        print(f"[cursors] pack: {e}")
    if not hasattr(S, "cursor_index"):
        S.cursor_index = 0   # 0 = contextual set; >0 picks pack[index-1] as pointer
    pygame.mouse.set_visible(not S.cursors)  # keep OS cursor only if load failed


def cursor_kind(S):
    """Pick which cursor to show for the current context."""
    if S.state in (STATE_WAKE, STATE_WAIT):
        return "busy"
    mp = pygame.mouse.get_pos()
    hot = lambda rects: any(r.collidepoint(mp) for r in rects)
    if S.show_settings:
        if S.volume_slider.dragging or S.sound_slider.dragging:
            return "grab"
        return "point" if hot([S.volume_slider.rect, S.sound_slider.rect,
                                S.music_toggle.rect, S.prev_btn.rect, S.play_pause_btn.rect,
                                S.next_btn.rect, S.settings_close_btn.rect,
                                S.settings_x.rect]) else "arrow"
    if S.show_keys:
        return "point"
    if getattr(S, "paused", False) and S.state in (STATE_LOCAL, STATE_TEST):
        return "point" if hot([S.pause_resume_btn.rect, S.pause_help_btn.rect,
                               S.pause_settings_btn.rect, S.pause_quit_btn.rect]) else "arrow"
    if hot([S.help_icon_btn.rect, S.close_btn.rect]):
        return "point"
    if S.state == STATE_MENU:
        return "point" if hot([b.rect for b in S.MENU_FOCUS]) else "arrow"
    if S.state == STATE_SETUP:
        rects = [S.setup_confirm_btn.rect, S.panel_x.rect] + [i.rect for i in S.name_inputs]
        if S.setup_mode in ("join", "host"):
            rects.append(S.addr_input.rect)
        if S.setup_mode == "join":
            rects.append(S.code_input.rect)
        if S.setup_mode in ("host", "local"):
            rects += [S.lobby_name_input.rect, S.max_players_stepper.rect]
        return "point" if hot(rects) else "arrow"
    return "arrow"


def draw_cursor(S, now):
    if not getattr(S, "cursors", None):
        return
    kind = cursor_kind(S)
    mx, my = pygame.mouse.get_pos()
    # a chosen pack cursor overrides the plain pointer states (arrow/point)
    idx = getattr(S, "cursor_index", 0)
    if idx and kind in ("arrow", "point") and getattr(S, "cursor_pack", None):
        img = S.cursor_pack[(idx - 1) % len(S.cursor_pack)]
        hx, hy = CURSOR_HOTSPOTS.get(kind, (1, 1))
        S.screen.blit(img, (int(mx - hx * CURSOR_SCALE), int(my - hy * CURSOR_SCALE)))
        return
    img = S.cursors.get(kind) or S.cursors.get("arrow")
    if not img:
        return
    if kind == "busy":  # spin the loading ring, centered on the pointer
        rot = pygame.transform.rotate(img, (-now * 300) % 360)
        S.screen.blit(rot, (int(mx - rot.get_width() / 2), int(my - rot.get_height() / 2)))
        return
    hx, hy = CURSOR_HOTSPOTS.get(kind, (1, 1))
    S.screen.blit(img, (int(mx - hx * CURSOR_SCALE), int(my - hy * CURSOR_SCALE)))


def draw_mic(S, screen, cx, cy, h, color, active=True):
    """Microphone glyph, centered on (cx, cy)."""
    if active and S.uicons.get("mic"):
        ic = S.uicons["mic"]
        screen.blit(ic, (cx - ic.get_width() // 2, cy - ic.get_height() // 2))
        return
    if not active and S.uicons.get("mute_red"):
        ic = S.uicons["mute_red"]
        screen.blit(ic, (cx - ic.get_width() // 2, cy - ic.get_height() // 2))
        return
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


HELP_INTRO = ("Explore an endless, procedurally-generated isometric world. Walk the "
              "terrain, hop over rocks, and reshape the map on the fly — solo, in "
              "same-screen co-op, or online with a friend via a room code.")


def keybinds_rect():
    w, h = 520, 158 + len(KEYBINDS) * 30
    return pygame.Rect(cfg.WIDTH // 2 - w // 2, cfg.HEIGHT // 2 - h // 2, w, h)


def draw_keybinds(S, now):
    screen = S.screen
    overlay = pygame.Surface((cfg.WIDTH, cfg.HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    screen.blit(overlay, (0, 0))
    rect = keybinds_rect()
    # removed draw_card(screen, rect)
    icon = S.uicons.get("menu")
    tx = rect.x + 28
    if icon:
        screen.blit(icon, (rect.x + 22, rect.y + 20)); tx = rect.x + 52
    draw_text(screen, "HOW TO PLAY", S.big_font, tx, rect.y + 20, cfg.GOLD)
    # intro / goal blurb
    ih = draw_wrapped_text(screen, HELP_INTRO, S.small_font, rect.y + 58,
                           rect.w - 56, cfg.MUTED, line_gap=3)
    draw_text(screen, "CONTROLS", S.small_font, rect.x + 28, rect.y + 62 + ih, cfg.GOLD_DIM)
    div_y = rect.y + 82 + ih
    draw_divider(screen, rect.x + 24, div_y, rect.w - 48)
    y = div_y + 14
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


def draw_pause(S, now):
    """In-world pause overlay: dims the game and offers resume / help /
    settings / quit."""
    screen = S.screen
    overlay = pygame.Surface((cfg.WIDTH, cfg.HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 150))
    screen.blit(overlay, (0, 0))
    rect = S.pause_rect
    # removed draw_card(screen, rect)
    draw_glow_text(screen, "PAUSED", S.big_font, 0, rect.y + 26, cfg.GOLD, cfg.GOLD,
                   center_x=rect.centerx)
    sub = S.lobby_name or ("ROOM " + S.room_code if S.room_code else "")
    if sub:
        draw_text(screen, sub[:34], S.small_font, 0, rect.y + 58, cfg.GOLD_DIM,
                  center_x=rect.centerx)
    draw_divider(screen, rect.x + 28, rect.y + 78, rect.w - 56)
    for btn in (S.pause_resume_btn, S.pause_help_btn, S.pause_settings_btn, S.pause_quit_btn):
        btn.draw(screen, S.font)
    draw_text(screen, "Esc to resume", S.small_font, 0, rect.bottom - 26,
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
        # F2 cycles the pointer through the whole cursor pack (0 = default set)
        if event.type == pygame.KEYDOWN and event.key == pygame.K_F2:
            n = len(getattr(S, "cursor_pack", [])) + 1
            S.cursor_index = (getattr(S, "cursor_index", 0) + 1) % n
            continue
        if S.show_keys:
            if event.type == pygame.MOUSEBUTTONDOWN or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                S.show_keys = False
            continue

        # (Removed close_btn click handler)

        if event.type == pygame.MOUSEBUTTONDOWN and not S.show_settings and S.help_icon_btn.clicked(event.pos):
            S.show_keys = True
            continue

        # per-panel close (X) at the card corner backs out one level
        if (event.type == pygame.MOUSEBUTTONDOWN and not S.show_settings
                and S.state in (STATE_SETUP, STATE_WAIT) and S.panel_x.clicked(event.pos)):
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
                    elif res == "help":
                        S.show_keys = True
                    elif res == "quit":
                        running = False
            elif event.button == JOYSTICK_B:
                if S.show_settings:
                    S.show_settings = False
                elif S.state == STATE_MENU and getattr(S, "menu_page", "root") != "root":
                    if S.menu_page == "host":
                        S.menu_page = "online"
                    elif S.menu_page == "online":
                        S.menu_page = "play"
                    elif S.menu_page == "play":
                        S.menu_page = "root"
                    update_menu_layout(S)

        if event.type in (pygame.MOUSEMOTION, pygame.MOUSEBUTTONDOWN):
            S.using_controller = False

        if S.show_settings:
            if event.type == pygame.MOUSEBUTTONDOWN:
                grabbed = (S.master_vol_slider.handle_mousedown(event.pos)
                           or S.volume_slider.handle_mousedown(event.pos)
                           or S.sound_slider.handle_mousedown(event.pos)
                           or S.particles_slider.handle_mousedown(event.pos)
                           or S.cam_smooth_slider.handle_mousedown(event.pos))
                if grabbed:
                    apply_volume(S)
                elif S.settings_x.clicked(event.pos) or S.settings_close_btn.clicked(event.pos) \
                        or not SETTINGS_RECT.collidepoint(event.pos):
                    S.show_settings = False
                elif S.music_toggle.clicked(event.pos):
                    S.music_toggle.value = not S.music_toggle.value
                    apply_volume(S)
                elif S.chunk_sim_toggle.clicked(event.pos):
                    S.chunk_sim_toggle.value = not S.chunk_sim_toggle.value
                elif S.fps_toggle.clicked(event.pos):
                    S.fps_toggle.value = not S.fps_toggle.value
                elif S.vsync_toggle.clicked(event.pos):
                    S.vsync_toggle.value = not S.vsync_toggle.value
                elif S.keybinds_btn.clicked(event.pos):
                    S.show_keys = True
                elif S.render_dist_stepper.handle_click(event.pos):
                    pass
                elif S.ui_scale_stepper.handle_click(event.pos):
                    pass
                elif S.prev_btn.clicked(event.pos):
                    play_prev_track(S)
                elif S.play_pause_btn.clicked(event.pos):
                    toggle_play_pause(S)
                elif S.next_btn.clicked(event.pos):
                    play_next_track(S)
            elif event.type == pygame.MOUSEBUTTONUP:
                S.master_vol_slider.handle_mouseup()
                S.volume_slider.handle_mouseup()
                S.sound_slider.handle_mouseup()
                S.particles_slider.handle_mouseup()
                S.cam_smooth_slider.handle_mouseup()
            elif event.type == pygame.MOUSEMOTION:
                S.master_vol_slider.handle_mousemotion(event.pos)
                S.volume_slider.handle_mousemotion(event.pos)
                S.sound_slider.handle_mousemotion(event.pos)
                S.particles_slider.handle_mousemotion(event.pos)
                S.cam_smooth_slider.handle_mousemotion(event.pos)
                if S.master_vol_slider.dragging or S.volume_slider.dragging or S.sound_slider.dragging:
                    apply_volume(S)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                S.show_settings = False
            continue

        # --- in-world pause menu (Esc toggles; overlays take Esc first) ---
        if (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                and S.state in (STATE_LOCAL, STATE_TEST)
                and not S.show_settings and not S.show_keys):
            S.paused = not getattr(S, "paused", False)
            continue
        if getattr(S, "paused", False) and S.state in (STATE_LOCAL, STATE_TEST):
            if event.type == pygame.MOUSEBUTTONDOWN:
                if S.pause_resume_btn.clicked(event.pos):
                    S.paused = False
                elif S.pause_help_btn.clicked(event.pos):
                    S.show_keys = True
                elif S.pause_settings_btn.clicked(event.pos):
                    S.show_settings = True
                elif S.pause_quit_btn.clicked(event.pos):
                    S.paused = False
                    go_back(S)
            continue  # freeze all other in-world input while paused

        # --- MAIN menu: keyboard nav (Up/Down + Enter) drives the cursor ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if S.state == STATE_WAIT:
                pos = event.pos
                if S.lobby_ready_btn and S.lobby_ready_btn.rect.collidepoint(pos):
                    # Toggle ready if not restricted
                    my_info = S.lobby_players.get(S.client_id, {})
                    if not my_info.get("restricted", False):
                        is_ready = my_info.get("ready", False)
                        if S.is_host:
                            S.lobby_players[S.client_id]["ready"] = not is_ready
                            S.conn.send({"type": "lobby_state", "players": S.lobby_players})
                        else:
                            S.conn.send({"type": "lobby_action", "id": S.client_id, "action": "ready", "value": not is_ready})
                if S.is_host and S.lobby_start_btn and S.lobby_start_btn.rect.collidepoint(pos):
                    # Check if all ready
                    if all(p.get("ready") for p in S.lobby_players.values()):
                        S.conn.send({"type": "lobby_start"})
                        S.state = STATE_TEST
                if S.is_host:
                    for pid, btn in S.lobby_kick_btns.items():
                        if btn.rect.collidepoint(pos):
                            if pid in S.lobby_players:
                                del S.lobby_players[pid]
                                S.conn.send({"type": "lobby_state", "players": S.lobby_players})
                    for pid, btn in S.lobby_restrict_btns.items():
                        if btn.rect.collidepoint(pos):
                            if pid in S.lobby_players:
                                S.lobby_players[pid]["restricted"] = not S.lobby_players[pid].get("restricted", False)
                                if S.lobby_players[pid]["restricted"]:
                                    S.lobby_players[pid]["ready"] = False
                                S.conn.send({"type": "lobby_state", "players": S.lobby_players})
        if event.type == pygame.KEYDOWN and S.state == STATE_MENU:
            if event.key in (pygame.K_DOWN, pygame.K_s):
                S.focus_index = (S.focus_index + 1) % len(S.MENU_FOCUS)
            elif event.key in (pygame.K_UP, pygame.K_w):
                S.focus_index = (S.focus_index - 1) % len(S.MENU_FOCUS)
            elif event.key == pygame.K_RETURN:
                res = activate_focused(S)
                if res == "settings":
                    S.show_settings = True
                elif res == "help":
                    S.show_keys = True
                elif res == "quit":
                    running = False
            elif event.key == pygame.K_ESCAPE and getattr(S, "menu_page", "root") != "root":
                if S.menu_page == "host":
                    S.menu_page = "online"
                elif S.menu_page == "online":
                    S.menu_page = "play"
                elif S.menu_page == "play":
                    S.menu_page = "root"
                update_menu_layout(S)

        # --- MAIN menu: one flat screen ---
        if event.type == pygame.MOUSEBUTTONDOWN and S.state == STATE_MENU:
            for i, btn in enumerate(S.MENU_FOCUS):
                if btn.clicked(event.pos):
                    S.focus_index = i
                    res = activate_focused(S)
                    if res == "settings":
                        S.show_settings = True
                    elif res == "help":
                        S.show_keys = True
                    elif res == "quit":
                        running = False
                    break

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

        # --- click any tile: hold to turn that tile white, release to restore ---
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and S.state in (STATE_LOCAL, STATE_TEST)
                and not S.show_settings and not S.show_keys
                and not getattr(S, "paused", False)
                and not S.help_icon_btn.rect.collidepoint(event.pos)
                and not S.close_btn.rect.collidepoint(event.pos)):
            S.pressed_tile = tile_at_screen(S, *event.pos)
            S.pressed_until = now + 5.0   # debug: keep it white for 5 seconds

        if (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                and S.state in (STATE_SETUP, STATE_WAIT)):
            go_back(S)
        if event.type == pygame.JOYBUTTONDOWN and event.button == JOYSTICK_B \
                and S.state in (STATE_SETUP, STATE_WAIT):
            go_back(S)

    if S.state == STATE_WAKE:
        if S.server_woken:
            go_setup(S, "host")

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
                S.is_host = False
                S.room_code = msg["code"]
                S.lobby_name = msg.get("lobby_name", "")
                S.max_players = msg.get("max_players", 2)
                S.player_count = msg.get("player_count", 2)
                S.last_pong_time = now
                S.status_msg = "Joined — waiting for host..."
                try:
                    S.conn.send({
                        "type": "lobby_hello", 
                        "id": S.client_id,
                        "name": S.username,
                        "profile": "Pilot",
                        "skin": "Default",
                        "color": list(color_for(S.username))
                    })
                except:
                    pass
                    S.status_msg = "Joined — waiting for host..."
            elif t == "peer_joined":
                S.player_count = msg.get("player_count", S.player_count + 1)
                S.status_msg = "Peer connected!"
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
            elif t == "lobby_hello" and S.is_host:
                pid = msg["id"]
                S.lobby_players[pid] = {
                    "name": msg["name"],
                    "profile": msg.get("profile", "Pilot"),
                    "skin": msg.get("skin", "Default"),
                    "color": msg.get("color", [255,255,255]),
                    "ready": False,
                    "restricted": False,
                    "is_host": False,
                    "last_seen": now
                }
                S.conn.send({"type": "lobby_state", "players": S.lobby_players})
            elif t == "lobby_action":
                if S.is_host:
                    pid = msg.get("id")
                    if pid in S.lobby_players and not S.lobby_players[pid]["restricted"]:
                        if msg.get("action") == "ready":
                            S.lobby_players[pid]["ready"] = bool(msg.get("value"))
                        S.conn.send({"type": "lobby_state", "players": S.lobby_players})
            elif t == "lobby_state":
                S.lobby_players = msg.get("players", {})
                if S.client_id not in S.lobby_players:
                    reset_to_menu(S, "You were kicked by the host.")
            elif t == "lobby_start":
                S.state = STATE_TEST
            elif t == "lobby_ping":
                S.conn.send({"type": "lobby_pong", "id": S.client_id})
            elif t == "lobby_pong":
                if S.is_host:
                    pid = msg.get("id")
                    if pid in getattr(S, "lobby_players", {}):
                        S.lobby_players[pid]["last_seen"] = now
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

            elif t == "error":
                reset_to_menu(S, f"Error: {msg['msg']}")
            elif t == "connect_error":
                reset_to_menu(S, msg["error"])
            elif t == "disconnected":
                if S.state != STATE_MENU:
                    err = msg.get("error", "closed")
                    reset_to_menu(S, f"Disconnected from server ({err}).")
    except queue.Empty:
        pass

    if S.state == STATE_WAIT and S.is_host:
        if now - getattr(S, "last_lobby_ping", 0) > 2.0:
            S.conn.send({"type": "lobby_ping"})
            S.last_lobby_ping = now
            changed = False
            for pid, p in S.lobby_players.items():
                if not p.get("is_host") and now - p.get("last_seen", now) > 6.0:
                    if not p.get("disconnected"):
                        p["disconnected"] = True
                        p["ready"] = False
                        changed = True
            if changed:
                S.conn.send({"type": "lobby_state", "players": S.lobby_players})

    if S.state == STATE_TEST:
        prune_peers(S, now)
        # walk the shared map; WASD + arrows both drive your own avatar
        keys = pygame.key.get_pressed()
        if not S.chat_open and not getattr(S, "paused", False):
            up = keys[pygame.K_w] or keys[pygame.K_UP]
            down = keys[pygame.K_s] or keys[pygame.K_DOWN]
            left = keys[pygame.K_a] or keys[pygame.K_LEFT]
            right = keys[pygame.K_d] or keys[pygame.K_RIGHT]
            dash = keys[pygame.K_LSHIFT]
            iso_move(S, S.me, up, down, left, right, dash, dt)
        apply_jump(S.me, dt)
        follow_camera(S, S.me[0], S.me[1], dt)

        # relay any captured voice chunks to the room
        for chunk in S.voice.poll_outgoing():
            try:
                S.conn.send({"type": "voice", "d": chunk})
            except Exception:
                pass
        my_info = getattr(S, "lobby_players", {}).get(S.client_id, {})
        if not my_info.get("restricted") and now - S.last_pos_sent > 1.0 / POS_SEND_HZ:
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
                reset_to_menu(S, "Ping failed.")
        if S.last_pong_time and now - S.last_pong_time > cfg.CONNECTION_TIMEOUT:
            reset_to_menu(S, f"Connection timed out (no response for {cfg.CONNECTION_TIMEOUT:.0f}s).")

    if S.state == STATE_LOCAL:
        keys = pygame.key.get_pressed()
        for i in range(len(S.local_players)):
            p = S.local_players[i]
            scheme, up, down, left, right, color, jump = SCHEMES[i]
            my_info = getattr(S, "lobby_players", {}).get(S.client_id, {})
            if getattr(S, "paused", False) or S.chat_open or my_info.get("restricted"):
                iso_move(S, p, False, False, False, False, False, dt)
            else:
                dash = False # We can map dash to a specific key per player if we want, or just let them jump
                iso_move(S, p, keys[up], keys[down], keys[left], keys[right], dash, dt)
            apply_jump(p, dt)
        follow_camera(S, *centroid(S.local_players), dt)

    # --- draw ---
    screen = S.screen
    if S.state in (STATE_TEST, STATE_LOCAL):
        screen.fill(cfg.BG)  # the world is drawn by each play-state branch below
    else:
        # menu-family: a slowly drifting procedural world as the backdrop
        update_menu_bg(S, dt)
        S.menu_iso.draw(screen)
        dim = pygame.Surface((cfg.WIDTH, cfg.HEIGHT), pygame.SRCALPHA)
        dim.fill((6, 8, 14, 155))
        screen.blit(dim, (0, 0))
        screen.blit(S.vignette, (0, 0))
        if S.state != STATE_MENU:
            pass # Removed card background to look like main lobby UI

    if S.state == STATE_WAKE:
        draw_header(S, "")
        elapsed = time.time() - S.wake_start_time
        
        # Juicy orbital loading animation
        cx, cy = CENTER_X, CARD_Y + 120
        num_orbs = 6
        for i in range(num_orbs):
            ang = now * 4.0 + (i * 6.28318 / num_orbs)
            rad = 40 + math.sin(now * 6.0 + i) * 15
            ox = cx + math.cos(ang) * rad
            oy = cy + math.sin(ang) * rad * 0.4  # flatten to isometric perspective!
            
            # depth sorting hack: draw back half darker
            is_back = math.sin(ang) < 0
            color = cfg.GOLD_DIM if is_back else cfg.GOLD
            size = max(2, int(5 + math.cos(ang) * 2))
            
            pygame.draw.circle(screen, color, (int(ox), int(oy)), size)
            if not is_back:
                pygame.draw.circle(screen, cfg.WHITE, (int(ox), int(oy)), size // 2)

        # Pulsing loading text
        msg = f"WAKING SERVER [{elapsed:.1f}s]"
        alpha = int(180 + 75 * math.sin(now * 5))
        text_surf = S.big_font.render(msg, True, cfg.GOLD_FAINT)
        text_surf.set_alpha(alpha)
        screen.blit(text_surf, (cx - text_surf.get_width() // 2, cy + 60))

    elif S.state == STATE_MENU:
        # no header/footer on the lobby — just the sand text menu over the world
        # hovering a menu item selects it (keeps mouse + keyboard in sync)
        mouse = pygame.mouse.get_pos()
        for i, btn in enumerate(S.MENU_FOCUS):
            if btn.rect.collidepoint(mouse):
                S.focus_index = i
                break
        for i, btn in enumerate(S.MENU_FOCUS):
            selected = (i == S.focus_index)
            color = cfg.SAND_BRIGHT if selected else cfg.SAND
            r = btn.rect
            # drop shadow for legibility over the world
            draw_text(screen, btn.label, S.body_font, r.x + 1, r.centery - 12 + 1,
                      cfg.SAND_SHADOW)
            w = draw_text(screen, btn.label, S.body_font, r.x, r.centery - 12, color)
            if selected:  # cursor pointing at the current selection
                px = r.x + w + 14 + int(2 * math.sin(now * 6))  # gentle nudge
                draw_text(screen, "<", S.body_font, px, r.centery - 12, cfg.SAND_BRIGHT)
        if S.status_msg:
            draw_wrapped_text(screen, S.status_msg, S.font, 126,
                              cfg.WIDTH - 120, cfg.RED, center_x=CENTER_X)

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
        if S.room_code:
            draw_text(screen, f"{len(S.lobby_players)}/{S.max_players} PLAYERS — SHARE THIS CODE",
                      S.small_font, 0, CARD_Y + 40, cfg.GOLD_DIM, center_x=CENTER_X)
            box_w, box_h = 220, 60
            box = pygame.Rect(CENTER_X - box_w // 2, CARD_Y + 60, box_w, box_h)
            alpha = pulse_alpha(now)
            pygame.draw.rect(screen, cfg.INPUT_BG, box, border_radius=8)
            pygame.draw.rect(screen, cfg.GOLD, box, 2, border_radius=8)
            code_surf = S.big_font.render(S.room_code, True, cfg.WHITE)
            code_surf.set_alpha(alpha)
            screen.blit(code_surf, (box.centerx - code_surf.get_width() // 2,
                                    box.centery - code_surf.get_height() // 2))
            
            # Draw lobby players
            py = CARD_Y + 140
            
            # Recreate buttons dicts for click handling
            S.lobby_kick_btns = {}
            S.lobby_restrict_btns = {}
            
            all_ready = len(S.lobby_players) > 0
            
            # Use fixed order for players
            for pid, p in S.lobby_players.items():
                is_me = (pid == S.client_id)
                prof, skin, col, nm = p.get("profile", "Pilot"), p.get("skin", "Default"), p.get("color", [255,255,255]), p.get("name", "Unknown")
                status = "HOST" if p.get("is_host") else ("DISCONNECTED" if p.get("disconnected") else ("RESTRICTED" if p.get("restricted") else ("READY" if p.get("ready") else "NOT READY")))
                
                if not p.get("ready") and not p.get("is_host") and not p.get("restricted"):
                    all_ready = False
                
                # Format: [Profile] / [Skin] / [Colour] — [Name] — [Status]
                color_hex = f"#{col[0]:02X}{col[1]:02X}{col[2]:02X}"
                txt = f"[{prof}] / [{skin}] / [{color_hex}] — {nm}"
                
                if is_me: txt = ">> " + txt
                
                status_color = cfg.GREEN if status == "READY" else (cfg.RED if status in ("RESTRICTED", "KICKED") else cfg.WHITE)
                
                # Draw text and status
                draw_text(screen, txt, S.small_font, CENTER_X - 280, py, col)
                draw_text(screen, status, S.small_font, CENTER_X + 80, py, status_color)
                
                # If host, draw host controls for OTHER players
                if S.is_host and not p.get("is_host"):
                    # KICK button
                    kx, ky = CENTER_X + 180, py - 6
                    kick_btn = Button(kx, ky, 50, 24, "KICK", palette={"fill": cfg.RED, "border": cfg.RED})
                    S.lobby_kick_btns[pid] = kick_btn
                    kick_btn.draw(screen, S.small_font)
                    # RESTRICT button
                    rx, ry = kx + 60, ky
                    rlabel = "UNRESTRICT" if p.get("restricted") else "RESTRICT"
                    rbg = cfg.GREEN if p.get("restricted") else (200, 100, 20)
                    r_btn = Button(rx, ry, 100, 24, rlabel, palette={"fill": rbg, "border": rbg})
                    S.lobby_restrict_btns[pid] = r_btn
                    r_btn.draw(screen, S.small_font)
                    
                py += 35
                
            # Draw my ready button
            my_info = S.lobby_players.get(S.client_id, {})
            if my_info and not my_info.get("is_host") and not my_info.get("restricted"):
                ready_label = "NOT READY" if my_info.get("ready") else "READY"
                ready_bg = (100, 100, 100) if my_info.get("ready") else cfg.GREEN
                S.lobby_ready_btn = Button(CENTER_X - 60, cfg.HEIGHT - 120, 120, 40, ready_label, palette={"fill": ready_bg, "border": ready_bg})
                S.lobby_ready_btn.draw(screen, S.small_font)
                
            # Draw host START GAME button
            if S.is_host:
                start_bg = cfg.GREEN if all_ready else (100, 100, 100)
                S.lobby_start_btn = Button(CENTER_X - 80, cfg.HEIGHT - 120, 160, 40, "START GAME", palette={"fill": start_bg, "border": start_bg})
                S.lobby_start_btn.draw(screen, S.small_font)
                
        else:
            draw_text(screen, "Reaching relay server...", S.small_font,
                      0, CARD_Y + 130, cfg.GOLD_DIM, center_x=CENTER_X)

    elif S.state == STATE_TEST:
        # shared endless world: every player walking the same map
        S.iso.draw(screen, visible_cells(S))
        draw_tile_press(S)
        crowd = [(pr["p"], pr["color"], pr["name"], False) for pr in S.peers.values()]
        crowd.append((S.me, color_for(S.username), S.username or "You", True))
        for p, col, nm, me in sorted(crowd, key=lambda a: a[0][0] + a[0][1]):  # iso depth
            draw_avatar(S, p, col, nm, me=me)
        # mic sign floating over your head
        mx, my = S.iso.to_screen(*S.iso.world_px(S.me[0], S.me[1]))
        my -= S.iso.elev(S.me[0], S.me[1]) + 42 + S.me[2]
        draw_mic(S, screen, int(mx), int(my), 22, (120, 255, 150), active=S.voice.talking)
        # peers who are talking are hard to know per-id; show a room mic flag
        rtt_text = f"{S.last_rtt:.0f} ms" if S.last_rtt is not None else "…"
        talk = "   MIC ON" if S.voice.talking else ""
        draw_world_hud(S, [
            f"ROOM {S.room_code}   {1 + len(S.peers)}/{S.max_players} in view   [{S.iso.theme}]",
            f"RTT {rtt_text}    X {S.me[0]:+.1f}  Y {S.me[1]:+.1f}   {S.iso.scale}x{talk}",
            f"players here: {', '.join([S.username or 'You'] + [p['name'] for p in S.peers.values()])[:60]}",
        ], "")
        if S.voice.talking:
            draw_mic(screen, cfg.WIDTH - 30, 30, 20, (120, 255, 150))
        draw_chat(S, now)

    elif S.state == STATE_LOCAL:
        # same endless world, same screen, up to 4 rovers
        S.iso.draw(screen, visible_cells(S))
        draw_tile_press(S)
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
                       "")
        draw_chat(S, now)

    if S.state not in (STATE_TEST, STATE_LOCAL, STATE_MENU):
        draw_footer(S)

    S.help_icon_btn.draw(screen)
    # the close-X only belongs on the setup/wait panels, not floating in-world
    if S.state in (STATE_SETUP, STATE_WAIT) and not S.show_settings:
        S.panel_x.draw(screen)

    if getattr(S, "paused", False) and S.state in (STATE_LOCAL, STATE_TEST) \
            and not S.show_settings and not S.show_keys:
        draw_pause(S, now)

    if S.show_settings:
        overlay = pygame.Surface((cfg.WIDTH, cfg.HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        screen.blit(overlay, (0, 0))
        # removed draw_card(screen, SETTINGS_RECT)
        draw_text(screen, "SETTINGS", S.big_font, 0, SETTINGS_RECT.y + 24, cfg.GOLD, center_x=CENTER_X)
        draw_divider(screen, SETTINGS_RECT.x + 30, SETTINGS_RECT.y + 66, SETTINGS_RECT.w - 60)

        for slider in (S.master_vol_slider, S.volume_slider, S.sound_slider, S.particles_slider, S.cam_smooth_slider):
            slider.draw(screen, S.font, S.small_font)
        
        # We manually aligned the sliders, let's just place the icons dynamically or near music/sound
        if S.music_icon is not None:
            screen.blit(S.music_icon, (SETTINGS_RECT.x + 8, S.volume_slider.rect.centery - 13))
        if S.sound_icon is not None:
            screen.blit(S.sound_icon, (SETTINGS_RECT.x + 8, S.sound_slider.rect.centery - 13))
        
        S.music_toggle.draw(screen, S.small_font)
        
        S.render_dist_stepper.draw(screen, S.font, S.small_font)
        S.ui_scale_stepper.draw(screen, S.font, S.small_font)
        S.chunk_sim_toggle.draw(screen, S.small_font)
        S.fps_toggle.draw(screen, S.small_font)
        S.vsync_toggle.draw(screen, S.small_font)
        S.keybinds_btn.draw(screen, S.font)

        draw_text(screen, "NOW PLAYING", S.small_font, SETTINGS_RECT.centerx - 80, SETTINGS_RECT.bottom - 130, cfg.GOLD_DIM)
        draw_text(screen, track_display_name(S.music_track_index), S.font,
                  SETTINGS_RECT.centerx - 80, SETTINGS_RECT.bottom - 110, cfg.WHITE)

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

    draw_cursor(S, now)  # custom pixel cursor, always on top

    return running
