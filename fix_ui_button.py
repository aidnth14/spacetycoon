import re
with open("client/ui.py", "r") as f:
    src = f.read()

button_draw_new = """    def draw(self, surf, font):
        import time, math
        r = self.rect
        hover = r.collidepoint(pygame.mouse.get_pos())
        
        # If palette is provided, render as a solid block button
        if self.palette:
            bg = self.palette.get("fill_hover") if hover and "fill_hover" in self.palette else self.palette.get("fill", cfg.INPUT_BG)
            border = self.palette.get("border_hover") if hover and "border_hover" in self.palette else self.palette.get("border", cfg.GOLD)
            text_color = self.palette.get("text", cfg.WHITE)
            
            import pygame
            pygame.draw.rect(surf, bg, r, border_radius=6)
            pygame.draw.rect(surf, border, r, 2, border_radius=6)
            draw_text(surf, self.label, font, 0, r.centery - font.get_height() // 2, text_color, center_x=r.centerx)
        else:
            # Default minimalistic text button
            color = cfg.SAND_BRIGHT if hover else cfg.SAND
            txt_w = draw_text(surf, self.label, font, 0, r.centery - font.get_height() // 2, color, center_x=r.centerx)
    
            if hover:
                now = time.time()
                px = r.centerx + txt_w // 2 + 14 + int(2 * math.sin(now * 6))
                draw_text(surf, "<", font, px, r.centery - font.get_height() // 2, cfg.SAND_BRIGHT)
"""
src = re.sub(r'    def draw\(self, surf, font\):\n(?:.*?\n)+?(?=    def clicked\(self, pos\):)', button_draw_new, src)
with open("client/ui.py", "w") as f:
    f.write(src)
