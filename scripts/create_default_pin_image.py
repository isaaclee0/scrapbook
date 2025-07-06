#!/usr/bin/env python3
"""
Script to create a default pin image.
This creates a simple placeholder image for pins that don't have an image.
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_default_pin_image():
    # Create a 400x300 image with a light gray background
    width, height = 400, 300
    image = Image.new('RGB', (width, height), color='#f5f5f5')
    draw = ImageDraw.Draw(image)
    
    # Add a border
    draw.rectangle([0, 0, width-1, height-1], outline='#e0e0e0', width=2)
    
    # Add a placeholder icon (simple image icon)
    icon_size = 60
    icon_x = (width - icon_size) // 2
    icon_y = (height - icon_size) // 2 - 20
    
    # Draw a simple image frame icon
    draw.rectangle([icon_x, icon_y, icon_x + icon_size, icon_y + icon_size], 
                   outline='#999', width=3)
    draw.rectangle([icon_x + 8, icon_y + 8, icon_x + icon_size - 8, icon_y + icon_size - 8], 
                   fill='#ccc')
    
    # Add some dots to represent an image
    for i in range(3):
        for j in range(3):
            x = icon_x + 15 + i * 15
            y = icon_y + 15 + j * 15
            draw.ellipse([x, y, x + 6, y + 6], fill='#666')
    
    # Add text
    try:
        # Try to use a system font
        font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 16)
    except:
        try:
            # Fallback to a different font
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
        except:
            # Use default font
            font = ImageFont.load_default()
    
    text = "No Image Available"
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_x = (width - text_width) // 2
    text_y = icon_y + icon_size + 20
    
    draw.text((text_x, text_y), text, fill='#666', font=font)
    
    # Save the image
    output_path = '../static/images/default_pin.png'
    image.save(output_path, 'PNG')
    print(f"✅ Default pin image created: {output_path}")

if __name__ == '__main__':
    create_default_pin_image() 