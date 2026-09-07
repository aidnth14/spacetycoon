import pygame
pygame.init()
pygame.display.set_mode((100, 100))
img = pygame.image.load("client/assets/ui/mute.png").convert_alpha()
red_img = img.copy()
red_img.fill((255, 0, 0, 255), special_flags=pygame.BLEND_RGB_ADD)
pygame.image.save(red_img, "client/assets/ui/mute_red.png")
