from PIL import Image, ImageDraw, ImageFont
import os

# Create a 200x200 image with a light gray background
img = Image.new('RGB', (200, 200), color='#f5f5f5')
draw = ImageDraw.Draw(img)

# Add a simple board icon
draw.rectangle([50, 50, 150, 150], outline='#e60023', width=3)
draw.line([50, 50, 150, 150], fill='#e60023', width=3)
draw.line([150, 50, 50, 150], fill='#e60023', width=3)

# Save the image
os.makedirs('static/images', exist_ok=True)
img.save('static/images/default_board.png') 