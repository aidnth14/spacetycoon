import os
import pygame

class Weapon:
    def __init__(self, name, fire_rate, bullet_speed, damage, gun_image_path, bullet_image_path, recoil=0.0):
        self.name = name
        self.fire_rate = fire_rate
        self.bullet_speed = bullet_speed
        self.damage = damage
        self.gun_image_path = gun_image_path
        self.bullet_image_path = bullet_image_path
        self.recoil = recoil
        self.image = None
        self.bullet_image = None
        
    def load(self, assets_dir):
        if not self.image:
            try:
                self.image = pygame.image.load(os.path.join(assets_dir, self.gun_image_path)).convert_alpha()
            except:
                self.image = pygame.Surface((32, 32))
        if not self.bullet_image:
            try:
                self.bullet_image = pygame.image.load(os.path.join(assets_dir, self.bullet_image_path)).convert_alpha()
            except:
                self.bullet_image = pygame.Surface((8, 8))

WEAPONS = {
    "AK47": Weapon("AK47", 0.12, 1200, 20, "items/weapons/AK47.png", "items/bullets/RifleAmmoBig.png", recoil=1.0),
    "Luger": Weapon("Luger", 0.3, 800, 15, "items/weapons/Luger.png", "items/bullets/PistolAmmoBig.png", recoil=0.5),
    "M15": Weapon("M15", 0.1, 1400, 22, "items/weapons/M15.png", "items/bullets/RifleAmmoBig.png", recoil=1.5),
    "M24": Weapon("M24", 1.2, 2500, 90, "items/weapons/M24.png", "items/bullets/RifleAmmoBig.png", recoil=5.0),
    "M92": Weapon("M92", 0.2, 850, 18, "items/weapons/M92.png", "items/bullets/PistolAmmoBig.png", recoil=0.8),
    "MP5": Weapon("MP5", 0.08, 900, 14, "items/weapons/MP5.png", "items/bullets/PistolAmmoBig.png", recoil=0.6),
    "Revolver": Weapon("Revolver", 0.5, 1200, 45, "items/weapons/Revolver.png", "items/bullets/PistolAmmoBig.png", recoil=2.5),
    "SawedOffShotgun": Weapon("SawedOffShotgun", 0.8, 700, 80, "items/weapons/SawedOffShotgun.png", "items/bullets/ShotgunShellBig.png", recoil=4.0),
    "Gun": Weapon("Gun", 0.3, 800, 15, "items/weapons/gun.png", "items/bullets/PistolAmmoSmall.png", recoil=0.5),
    "Sword": Weapon("Sword", 0.4, 600, 30, "items/weapons/sword.png", "items/weapons/sword.png", recoil=0.0),
    "Shotgunshellsmall": Weapon("Shotgunshellsmall", 0.4, 600, 10, "items/bullets/ShotgunShellSmall.png", "items/bullets/ShotgunShellSmall.png", recoil=0.5),
    "Axe": Weapon("Axe", 0.4, 600, 10, "items/tools/axe.png", "items/tools/axe.png", recoil=0.5),
    "Pickaxe": Weapon("Pickaxe", 0.4, 600, 10, "items/tools/pickaxe.png", "items/tools/pickaxe.png", recoil=0.5),
    "Shovel": Weapon("Shovel", 0.4, 600, 10, "items/tools/shovel.png", "items/tools/shovel.png", recoil=0.5),
    "Fishing_rod": Weapon("Fishing_rod", 0.4, 600, 10, "items/tools/fishing_rod.png", "items/tools/fishing_rod.png", recoil=0.5),
    "Hammer": Weapon("Hammer", 0.4, 600, 10, "items/tools/hammer.png", "items/tools/hammer.png", recoil=0.5),
    "Scythe": Weapon("Scythe", 0.4, 600, 10, "items/tools/scythe.png", "items/tools/scythe.png", recoil=0.5),
    "Mallet": Weapon("Mallet", 0.4, 600, 10, "items/tools/mallet.png", "items/tools/mallet.png", recoil=0.5),
    "Mushroom": Weapon("Mushroom", 0.4, 600, 10, "items/food/mushroom.png", "items/food/mushroom.png", recoil=0.5),
    "Apple": Weapon("Apple", 0.4, 600, 10, "items/food/apple.png", "items/food/apple.png", recoil=0.5),
    "Bread": Weapon("Bread", 0.4, 600, 10, "items/food/bread.png", "items/food/bread.png", recoil=0.5),
    "Fish": Weapon("Fish", 0.4, 600, 10, "items/food/fish.png", "items/food/fish.png", recoil=0.5),
    "Meat": Weapon("Meat", 0.4, 600, 10, "items/food/meat.png", "items/food/meat.png", recoil=0.5),
    "Wheat": Weapon("Wheat", 0.4, 600, 10, "items/food/wheat.png", "items/food/wheat.png", recoil=0.5),
    "Brick": Weapon("Brick", 0.4, 600, 10, "items/material/brick.png", "items/material/brick.png", recoil=0.5),
    "Coal": Weapon("Coal", 0.4, 600, 10, "items/material/coal.png", "items/material/coal.png", recoil=0.5),
    "Iron_ore": Weapon("Iron_ore", 0.4, 600, 10, "items/material/iron_ore.png", "items/material/iron_ore.png", recoil=0.5),
    "Wood": Weapon("Wood", 0.4, 600, 10, "items/material/wood.png", "items/material/wood.png", recoil=0.5),
    "Copper_ore": Weapon("Copper_ore", 0.4, 600, 10, "items/material/copper_ore.png", "items/material/copper_ore.png", recoil=0.5),
    "Gold_ore": Weapon("Gold_ore", 0.4, 600, 10, "items/material/gold_ore.png", "items/material/gold_ore.png", recoil=0.5),
    "Diamond": Weapon("Diamond", 0.4, 600, 10, "items/material/diamond.png", "items/material/diamond.png", recoil=0.5),
    "Key": Weapon("Key", 0.4, 600, 10, "items/key.png", "items/key.png", recoil=0.5),
    "Book": Weapon("Book", 0.4, 600, 10, "items/book.png", "items/book.png", recoil=0.5),
    "Map": Weapon("Map", 0.4, 600, 10, "items/map.png", "items/map.png", recoil=0.5),
    "Letter": Weapon("Letter", 0.4, 600, 10, "items/letter.png", "items/letter.png", recoil=0.5),
    "Sack": Weapon("Sack", 0.4, 600, 10, "items/sack.png", "items/sack.png", recoil=0.5),
    "Boots": Weapon("Boots", 0.4, 600, 10, "items/boots.png", "items/boots.png", recoil=0.5),
    "Stick": Weapon("Stick", 0.4, 600, 10, "items/material/stick.png", "items/material/stick.png", recoil=0.5),
    "Log1": Weapon("Log1", 0.4, 600, 10, "items/material/log1.png", "items/material/log1.png", recoil=0.5),
    "Log2": Weapon("Log2", 0.4, 600, 10, "items/material/log2.png", "items/material/log2.png", recoil=0.5),
    "Log3": Weapon("Log3", 0.4, 600, 10, "items/material/log3.png", "items/material/log3.png", recoil=0.5),
    "Log4": Weapon("Log4", 0.4, 600, 10, "items/material/log4.png", "items/material/log4.png", recoil=0.5),
}

GLOBAL_HOTBAR = [k for k, w in WEAPONS.items() if "weapons" in w.gun_image_path or "tools" in w.gun_image_path]
