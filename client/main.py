#!/usr/bin/env python3
"""Bootstrapper + live hot-reloader.

The whole per-frame game lives in game.py. This file owns the persistent
state object `S` (which it never rebuilds) and watches game.py / ui.py /
config.py. The instant any of them changes on disk it reloads the modules and
rebuilds the UI in place — the pygame window keeps running, the network
connection and music keep going, no restart needed.
"""
import importlib
import os
import sys
import time
from types import SimpleNamespace

import pygame

import config as cfg
from network import Connection, install_dns_fallback
import ui
import game

install_dns_fallback()

pygame.init()

S = SimpleNamespace()
S.ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# The game always draws to a fixed logical canvas (cfg.WIDTH x cfg.HEIGHT); the
# window can be freely resized or made fullscreen and we letterbox-scale the
# canvas into it. This keeps all UI layout math resolution-independent.
CW, CH = cfg.WIDTH, cfg.HEIGHT
S.window = pygame.display.set_mode((CW, CH), pygame.RESIZABLE)
S.screen = pygame.Surface((CW, CH))          # the canvas game.frame renders to
S.fullscreen = False
S.windowed_size = (CW, CH)
pygame.display.set_caption("Space Tycoon")


def canvas_fit():
    ww, wh = S.window.get_size()
    scale_x = ww / CW
    scale_y = wh / CH
    return scale_x, scale_y


def to_canvas(pos):
    scale_x, scale_y = canvas_fit()
    return (pos[0] / scale_x, pos[1] / scale_y)


def remap_events(events):
    """Translate mouse coords from window space into canvas space, and handle
    window-level keys (F11 fullscreen) / resize here."""
    out = []
    for e in events:
        if e.type == pygame.VIDEORESIZE and not S.fullscreen:
            S.windowed_size = (e.w, e.h)
            S.window = pygame.display.set_mode((e.w, e.h), pygame.RESIZABLE)
            continue
        if e.type == pygame.KEYDOWN and e.key == pygame.K_F11:
            S.fullscreen = not S.fullscreen
            if S.fullscreen:
                S.window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                S.window = pygame.display.set_mode(S.windowed_size, pygame.RESIZABLE)
            continue
        if e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
            d = e.dict.copy()
            d["pos"] = to_canvas(e.pos)
            out.append(pygame.event.Event(e.type, d))
        else:
            out.append(e)
    return out


# widgets read pygame.mouse.get_pos() for hover — remap it to canvas space too
_real_mouse_pos = pygame.mouse.get_pos
pygame.mouse.get_pos = lambda: tuple(int(v) for v in to_canvas(_real_mouse_pos()))


def present():
    """Scale the canvas into the window, stretching to fill completely."""
    ww, wh = S.window.get_size()
    scaled = pygame.transform.smoothscale(S.screen, (ww, wh))
    
    # Screen shake
    dx = dy = 0
    if getattr(S, "shake", 0.0) > 0.0:
        import random
        intensity = S.shake * 15
        dx = random.randint(-int(intensity), int(intensity))
        dy = random.randint(-int(intensity), int(intensity))
        S.shake = max(0.0, S.shake - 0.05)
        
    S.window.blit(scaled, (dx, dy))
    pygame.display.flip()

S.clock = pygame.time.Clock()
S.MUSIC_END_EVENT = pygame.USEREVENT + 1
pygame.mixer.music.set_endevent(S.MUSIC_END_EVENT)
S.conn = Connection()
S.reload_flash = 0

game.init(S)

# --- file watcher: modules that hot-reload live ---
WATCHED = [cfg, ui, game]
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))


def _watch_paths():
    paths = {}
    for mod in WATCHED:
        p = getattr(mod, "__file__", None)
        if p:
            paths[mod] = p
    return paths


def _mtimes(paths):
    out = {}
    for mod, p in paths.items():
        try:
            out[mod] = os.path.getmtime(p)
        except OSError:
            pass
    return out


_paths = _watch_paths()
_last_mtimes = _mtimes(_paths)
_last_check = 0.0
CHECK_INTERVAL = 0.3  # seconds between disk polls


def check_for_reload(now):
    """Poll watched files; reload changed modules and rebuild UI in place.
    Returns True if a reload happened."""
    global _last_mtimes
    current = _mtimes(_paths)
    changed = [m for m, t in current.items() if _last_mtimes.get(m) != t]
    if not changed:
        return False
    _last_mtimes = current
    try:
        # reload config first so ui/game see new values, then ui, then game
        for mod in (cfg, ui, game):
            if mod in changed or mod is game:
                importlib.reload(mod)
        game.rebuild(S)
        S.reload_flash = now + 1.5
        print(f"[hot-reload] {', '.join(m.__name__ for m in changed)} @ {time.strftime('%H:%M:%S')}")
        return True
    except Exception as e:
        # keep the old, working code running instead of crashing
        print(f"[hot-reload] FAILED, keeping previous version: {type(e).__name__}: {e}")
        return False


running = True
while running:
    dt = S.clock.tick(30) / 1000.0
    now = time.time()

    if now - _last_check > CHECK_INTERVAL:
        _last_check = now
        check_for_reload(now)

    events = remap_events(pygame.event.get())
    running = game.frame(S, events, dt, now)
    present()

S.conn.close()
if getattr(S, "voice", None):
    S.voice.close()
pygame.quit()
sys.exit()
