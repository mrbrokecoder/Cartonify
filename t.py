import pygame
import random
import math

# Initialize Pygame
pygame.init()

# Set up the display
width, height = 1000, 800
screen = pygame.display.set_mode((width, height))
pygame.display.set_caption("Detailed Flask App Pipeline Visualization")

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)

# Fonts
font_small = pygame.font.Font(None, 24)
font_large = pygame.font.Font(None, 32)

# Pipeline stages
stages = [
    {"name": "User Input", "color": BLUE, "substages": ["Form Data", "File Upload"]},
    {"name": "Authentication", "color": GREEN, "substages": ["Check Credentials", "Generate Token"]},
    {"name": "Image Generation", "color": MAGENTA, "substages": ["Process Request", "Generate Image", "Save Image"]},
    {"name": "Database Update", "color": YELLOW, "substages": ["Connect to DB", "Update Records"]},
    {"name": "Response", "color": CYAN, "substages": ["Prepare Data", "Send Response"]}
]

# Particle system
class Particle:
    def __init__(self, x, y, target_y):
        self.x = x
        self.y = y
        self.target_y = target_y
        self.color = WHITE
        self.speed = random.uniform(1, 3)
        self.size = random.randint(2, 4)
        self.completed_stages = 0

    def move(self):
        if self.y < self.target_y:
            self.y += self.speed
            if self.y >= self.target_y:
                self.completed_stages += 1
                if self.completed_stages < len(stages):
                    self.target_y = (self.completed_stages + 1) * (height / len(stages))
                else:
                    self.y = 0
                    self.target_y = height / len(stages)
                    self.completed_stages = 0

    def draw(self):
        pygame.draw.circle(screen, self.color, (int(self.x), int(self.y)), self.size)

particles = [Particle(random.randint(0, width), 0, height / len(stages)) for _ in range(20)]

# Main loop
running = True
clock = pygame.time.Clock()

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # Clear the screen
    screen.fill(BLACK)

    # Draw pipeline stages
    stage_height = height // len(stages)
    for i, stage in enumerate(stages):
        y = i * stage_height
        pygame.draw.rect(screen, stage["color"], (0, y, width, stage_height), 2)
        text = font_large.render(stage["name"], True, WHITE)
        screen.blit(text, (10, y + 10))

        # Draw substages
        substage_height = stage_height // (len(stage["substages"]) + 1)
        for j, substage in enumerate(stage["substages"]):
            sub_y = y + (j + 1) * substage_height
            pygame.draw.rect(screen, stage["color"], (50, sub_y, width - 100, substage_height), 1)
            text = font_small.render(substage, True, WHITE)
            screen.blit(text, (60, sub_y + 5))

    # Update and draw particles
    for particle in particles:
        particle.move()
        particle.draw()

    # Draw connections between stages
    for i in range(len(stages) - 1):
        start_y = (i + 1) * stage_height
        end_y = (i + 2) * stage_height
        pygame.draw.line(screen, WHITE, (width // 2, start_y), (width // 2, end_y), 2)

    # Update the display
    pygame.display.flip()

    # Cap the frame rate
    clock.tick(60)

# Quit Pygame
pygame.quit()