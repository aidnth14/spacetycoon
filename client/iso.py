"""Infinite isometric world — the shared game map for Space Tycoon.

Every visible tile is derived deterministically from its (x, y) world cell, so
the map is endless in all directions with nothing stored to a fixed grid.

Two themes, switchable live (press Tab in-game):
  dirt  — soil cubes (0-18, 21) scattered with brown rocks / logs / mounds
  stone — grey slabs (61,63,66,69) scattered with boulders (62,64,65,67,68)

Low-frequency noise clusters the ground tiles into patches and drives a rolling
elevation; a per-cell hash sprinkles props on top.
"""
import math
import os

import pygame

TILE_SRC = 32                       # source tiles are 32x32
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "tiles")
FEATURE = 30.0                      # larger => bigger patches / hills
MIN_SCALE, MAX_SCALE = 1, 3         # zoom range (kept modest on purpose)

DIRT_GROUND = list(range(19)) + [21]
BROWN_PROPS = [48, 49, 50, 53, 54, 55, 56, 57, 58, 59, 60]
STONE_GROUND = [61, 63, 66, 69]
STONE_PROPS = [62, 64, 65, 67, 68]

THEMES = {
    "dirt":  {"ground": DIRT_GROUND,  "props": BROWN_PROPS, "prop_rate": 0.88, "bg": (54, 38, 30)},
    "stone": {"ground": STONE_GROUND, "props": STONE_PROPS, "prop_rate": 0.86, "bg": (40, 44, 52)},
}
THEME_ORDER = ["dirt", "stone"]
# every tile id any theme needs — loaded up front so switching is instant
ALL_TILES = sorted(set(sum((t["ground"] + t["props"] for t in THEMES.values()), [])))


# --- deterministic fractal value-noise (infinite, seed-based) ---
def _hash01(x, y, seed):
    h = (x * 374761393 + y * 668265263 + seed * 2246822519) & 0xFFFFFFFF
    h = (h ^ (h >> 13)) * 1274126177 & 0xFFFFFFFF
    h ^= h >> 16
    return (h & 0xFFFFFFFF) / 0xFFFFFFFF


def _smooth(t):
    return t * t * (3 - 2 * t)


def _value_noise(x, y, seed):
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = x - x0, y - y0
    v00 = _hash01(x0, y0, seed)
    v10 = _hash01(x0 + 1, y0, seed)
    v01 = _hash01(x0, y0 + 1, seed)
    v11 = _hash01(x0 + 1, y0 + 1, seed)
    sx, sy = _smooth(fx), _smooth(fy)
    a = v00 + (v10 - v00) * sx
    b = v01 + (v11 - v01) * sx
    return a + (b - a) * sy


def fractal(x, y, seed, octaves=4):
    amp, freq, total, norm = 1.0, 1.0, 0.0, 0.0
    for o in range(octaves):
        total += _value_noise(x * freq, y * freq, seed + o * 1013) * amp
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm


def classify(gx, gy, seed, theme):
    """(ground_tile, prop_tile_or_None, elevation_level) for a world cell."""
    t = THEMES[theme]
    ground, props, rate = t["ground"], t["props"], t["prop_rate"]
    h = fractal(gx / FEATURE, gy / FEATURE, seed)
    r = _hash01(gx, gy, seed ^ 0x9E3779B9)
    base = ground[int(((h * 0.7 + r * 0.3) * len(ground))) % len(ground)]
    level = min(6, int(h * 7))
    prop = None
    if r > rate and props:
        prop = props[int(_hash01(gx, gy, seed + 55) * len(props)) % len(props)]
    return base, prop, level


class World:
    def __init__(self, seed, theme):
        self.seed = seed
        self.theme = theme
        self.cache = {}

    def get(self, gx, gy):
        key = (gx, gy)
        c = self.cache.get(key)
        if c is None:
            c = classify(gx, gy, self.seed, self.theme)
            self.cache[key] = c
        return c

    def reseed(self, seed):
        self.seed = seed
        self.cache.clear()

    def set_theme(self, theme):
        self.theme = theme
        self.cache.clear()


def load_tiles(scale):
    """dict {tile_id: surface} at the given integer scale (all themes)."""
    px = TILE_SRC * scale
    tiles = {}
    for i in ALL_TILES:
        img = pygame.image.load(os.path.join(ASSETS, f"tile_{i:03d}.png")).convert_alpha()
        if scale != 1:
            img = pygame.transform.scale(img, (px, px))
        tiles[i] = img
    return tiles


class Iso:
    """Projection metrics + camera for one running world at a fixed scale."""
    def __init__(self, seed=1337, scale=2, view=(800, 640), theme="dirt"):
        self.theme = theme
        self.world = World(seed, theme)
        self.scale = scale
        self.tiles = load_tiles(scale)
        self.HALF_W = TILE_SRC * scale // 2
        self.HALF_H = TILE_SRC * scale // 4
        self.LIFT = 6 * scale
        self.TILE_PX = TILE_SRC * scale
        self.SW, self.SH = view
        self.cam_x = -self.SW // 2
        self.cam_y = -self.SH // 2

    def reseed(self, seed):
        self.world.reseed(seed)

    def cycle_theme(self):
        i = (THEME_ORDER.index(self.theme) + 1) % len(THEME_ORDER)
        self.theme = THEME_ORDER[i]
        self.world.set_theme(self.theme)
        return self.theme

    def set_scale(self, scale):
        """Rebuild render metrics at a new zoom. Positions are grid-space so
        they don't move; the caller just re-centers the camera."""
        scale = max(MIN_SCALE, min(MAX_SCALE, scale))
        if scale == self.scale:
            return False
        self.scale = scale
        self.tiles = load_tiles(scale)
        self.HALF_W = TILE_SRC * scale // 2
        self.HALF_H = TILE_SRC * scale // 4
        self.LIFT = 6 * scale
        self.TILE_PX = TILE_SRC * scale
        return True

    @property
    def bg(self):
        return THEMES[self.theme]["bg"]

    # world-pixel <-> screen
    def to_screen(self, wx, wy):
        return wx - self.cam_x, wy - self.cam_y

    def center_on(self, wx, wy):
        self.cam_x = wx - self.SW // 2
        self.cam_y = wy - self.SH // 2

    def cell_at(self, wx, wy):
        u = wx / self.HALF_W          # gx - gy
        v = wy / self.HALF_H          # gx + gy
        return int(round((u + v) / 2)), int(round((v - u) / 2))

    # --- grid-space avatars (independent of zoom) ---
    def world_px(self, fx, fy):
        """Fractional grid cell -> world pixels at the current scale."""
        return (fx - fy) * self.HALF_W, (fx + fy) * self.HALF_H

    def solid(self, fx, fy):
        """Collision layer: any cell carrying a prop (rock/log/boulder) blocks."""
        return self.world.get(round(fx), round(fy))[1] is not None

    def elev(self, fx, fy):
        """Screen-y footing lift of the ground under a grid cell."""
        return self.world.get(round(fx), round(fy))[2] * self.LIFT

    def find_free(self, fx, fy, radius=8):
        """Nearest non-solid cell (spiral) so avatars never spawn inside a rock."""
        if not self.solid(fx, fy):
            return fx, fy
        cx, cy = round(fx), round(fy)
        for r in range(1, radius + 1):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r:
                        continue
                    if not self.solid(cx + dx, cy + dy):
                        return float(cx + dx), float(cy + dy)
        return fx, fy

    def draw(self, screen, reveal=None):
        """Render the world. When `reveal` is a set of (gx, gy) cells, only
        those tiles are drawn (fog of war) and the rest stays black — the map
        is discovered as players move. `reveal=None` draws everything (menu)."""
        cam_x, cam_y = self.cam_x, self.cam_y
        HW, HH, LIFT, TPX = self.HALF_W, self.HALF_H, self.LIFT, self.TILE_PX
        SW, SH = self.SW, self.SH
        screen.fill((0, 0, 0) if reveal is not None else self.bg)
        cgx, cgy = self.cell_at(cam_x + SW // 2, cam_y + SH // 2)
        R = int(max(SW / HW, SH / HH)) + 8
        visible = []
        for dgy in range(-R, R + 1):
            for dgx in range(-R, R + 1):
                gx, gy = cgx + dgx, cgy + dgy
                if reveal is not None and (gx, gy) not in reveal:
                    continue
                sx = (gx - gy) * HW - cam_x
                sy = (gx + gy) * HH - cam_y
                if sx < -TPX or sx > SW or sy < -TPX * 2 or sy > SH + TPX:
                    continue
                visible.append((gx + gy, gx, gy, sx, sy))
        visible.sort()  # back-to-front
        blit = screen.blit
        get = self.world.get
        tiles = self.tiles
        for _, gx, gy, sx, sy in visible:
            base, prop, level = get(gx, gy)
            oy = sy - level * LIFT
            blit(tiles[base], (sx - HW, oy - HH))
            if prop is not None:
                blit(tiles[prop], (sx - HW, oy - HH))
