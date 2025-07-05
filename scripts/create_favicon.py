from PIL import Image, ImageDraw
import os

# Create a 32x32 image with transparent background
size = (32, 32)
img = Image.new('RGBA', size, (255, 255, 255, 0))
draw = ImageDraw.Draw(img)

# Draw a simple colored circle in the center
circle_radius = 12
center = (size[0] // 2, size[1] // 2)
draw.ellipse([
    (center[0] - circle_radius, center[1] - circle_radius),
    (center[0] + circle_radius, center[1] + circle_radius)
], fill=(41, 128, 185, 255))  # blue color

# Optionally, add a white letter in the center (e.g., 'S' for Scrapbook)
# from PIL import ImageFont
# font = ImageFont.truetype('arial.ttf', 18)
# draw.text((10, 6), 'S', font=font, fill=(255,255,255,255))

# Ensure static directory exists
os.makedirs('static', exist_ok=True)

# Save as favicon.ico
img.save('static/favicon.ico', format='ICO')
print('Favicon saved to static/favicon.ico') 