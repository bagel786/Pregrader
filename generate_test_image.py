from PIL import Image, ImageDraw
import os

def create_test_card():
    # Create directory if not exists
    os.makedirs('test/assets', exist_ok=True)
    
    # Create a 800x600 black background
    img = Image.new('RGB', (800, 600), color='black')
    draw = ImageDraw.Draw(img)
    
    # Draw a card (yellow border)
    # Card size: 300x400, centered
    # Center is 400, 300
    # Top-Left: 250, 100
    # Bottom-Right: 550, 500
    
    # Draw Yellow Border (Outer Card)
    draw.rectangle([250, 100, 550, 500], fill='yellow')
    
    # Draw Art (Inner Content) - slightly off-center to test scoring?
    # Perfect center would be margin 20 all around?
    # Let's make it perfect first.
    # Yellow border is 50px wide? No that's huge.
    # Let's make border 10px.
    draw.rectangle([260, 110, 540, 490], fill='blue')
    
    img.save('test/assets/test_card.jpg')
    print("Created test/assets/test_card.jpg")

if __name__ == "__main__":
    create_test_card()
