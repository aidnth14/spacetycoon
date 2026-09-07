import re

with open("game.py", "r") as f:
    src = f.read()

draw_wait_new = """    elif S.state == STATE_WAIT:
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
                status = "HOST" if p.get("is_host") else ("RESTRICTED" if p.get("restricted") else ("READY" if p.get("ready") else "NOT READY"))
                
                if not p.get("ready") and not p.get("is_host"):
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
                    kick_btn = Button("KICK", kx, ky, 50, 24, bg=cfg.RED)
                    S.lobby_kick_btns[pid] = kick_btn
                    kick_btn.draw(screen)
                    # RESTRICT button
                    rx, ry = kx + 60, ky
                    rlabel = "UNRESTRICT" if p.get("restricted") else "RESTRICT"
                    rbg = cfg.GREEN if p.get("restricted") else (200, 100, 20)
                    r_btn = Button(rlabel, rx, ry, 100, 24, bg=rbg)
                    S.lobby_restrict_btns[pid] = r_btn
                    r_btn.draw(screen)
                    
                py += 35
                
            # Draw my ready button
            my_info = S.lobby_players.get(S.client_id, {})
            if my_info and not my_info.get("is_host") and not my_info.get("restricted"):
                ready_label = "NOT READY" if my_info.get("ready") else "READY"
                ready_bg = (100, 100, 100) if my_info.get("ready") else cfg.GREEN
                S.lobby_ready_btn = Button(ready_label, CENTER_X - 60, cfg.HEIGHT - 120, 120, 40, bg=ready_bg)
                S.lobby_ready_btn.draw(screen)
                
            # Draw host START GAME button
            if S.is_host:
                start_bg = cfg.GREEN if all_ready else (100, 100, 100)
                S.lobby_start_btn = Button("START GAME", CENTER_X - 80, cfg.HEIGHT - 120, 160, 40, bg=start_bg)
                S.lobby_start_btn.draw(screen)
                
        else:
            draw_text(screen, "Reaching relay server...", S.small_font,
                      0, CARD_Y + 130, cfg.GOLD_DIM, center_x=CENTER_X)
"""

src = re.sub(r'    elif S.state == STATE_WAIT:\n(?:.*?\n)+?    elif S.state == STATE_TEST:', draw_wait_new + '\n    elif S.state == STATE_TEST:', src)

with open("game.py", "w") as f:
    f.write(src)
