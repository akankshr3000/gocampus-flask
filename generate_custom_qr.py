import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import RoundedModuleDrawer
from qrcode.image.styles.colormasks import SolidFillColorMask
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import math

def generate_premium_qr():
    # Configuration
    URL = "https://www.bitm.edu.in"
    LOGO_PATH = r"C:/Users/akank/.gemini/antigravity/brain/48f1d592-7b89-4002-8966-172aa6a9e629/uploaded_image_1763737120337.png"
    OUTPUT_PATH = "premium_qr.png"
    QR_SIZE = 1500
    
    # 1. Generate QR Matrix
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2, # Minimal border, we'll add our own
    )
    qr.add_data(URL)
    qr.make(fit=True)

    # 2. Create Base Image with Rounded Modules
    # We use qrcode's styled image factory for the base rounded look
    img_qr = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(),
        color_mask=SolidFillColorMask(back_color=(255, 255, 255, 0), front_color=(0, 0, 0, 255))
    )
    
    # Resize to target size (high quality)
    img_qr = img_qr.resize((QR_SIZE, QR_SIZE), Image.Resampling.LANCZOS)
    
    # Create main canvas (transparent)
    canvas = Image.new("RGBA", (QR_SIZE, QR_SIZE), (255, 255, 255, 0))
    
    # 3. Background Watermark
    # "Ballari Institute of Technology and Management" - repeated, diagonal, faint
    watermark_layer = Image.new("RGBA", (QR_SIZE, QR_SIZE), (255, 255, 255, 0))
    draw_wm = ImageDraw.Draw(watermark_layer)
    
    # Try to load a nice font, fallback to default
    try:
        font_wm = ImageFont.truetype("arial.ttf", 40)
    except:
        font_wm = ImageFont.load_default()

    wm_text = "Ballari Institute of Technology and Management   "
    # Create a larger canvas to rotate
    wm_canvas_size = int(QR_SIZE * 1.5)
    wm_canvas = Image.new("RGBA", (wm_canvas_size, wm_canvas_size), (255, 255, 255, 0))
    draw_wm_temp = ImageDraw.Draw(wm_canvas)
    
    # Draw text in a grid
    text_bbox = draw_wm_temp.textbbox((0, 0), wm_text, font=font_wm)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    for y in range(0, wm_canvas_size, int(text_height * 4)):
        for x in range(0, wm_canvas_size, int(text_width)):
            draw_wm_temp.text((x, y), wm_text, fill=(0, 0, 0, 30), font=font_wm) # ~12% opacity (30/255)

    # Rotate and crop center
    wm_rotated = wm_canvas.rotate(45, resample=Image.Resampling.BICUBIC)
    
    # Crop to QR_SIZE
    left = (wm_canvas_size - QR_SIZE) // 2
    top = (wm_canvas_size - QR_SIZE) // 2
    wm_cropped = wm_rotated.crop((left, top, left + QR_SIZE, top + QR_SIZE))
    
    # Composite Watermark
    canvas = Image.alpha_composite(canvas, wm_cropped)
    
    # 4. Composite QR Code
    canvas = Image.alpha_composite(canvas, img_qr)

    # 5. Center Logo
    try:
        logo = Image.open(LOGO_PATH).convert("RGBA")
        
        # Calculate logo size (25% of QR area)
        logo_size_px = int(QR_SIZE * 0.25)
        logo = logo.resize((logo_size_px, logo_size_px), Image.Resampling.LANCZOS)
        
        # Create white rounded background for logo
        bg_size = int(logo_size_px * 1.1)
        logo_bg = Image.new("RGBA", (bg_size, bg_size), (255, 255, 255, 0))
        draw_logo_bg = ImageDraw.Draw(logo_bg)
        
        # Draw rounded square
        radius = 40
        draw_logo_bg.rounded_rectangle([(0, 0), (bg_size, bg_size)], radius=radius, fill=(255, 255, 255, 255))
        
        # Paste logo onto background
        offset = (bg_size - logo_size_px) // 2
        logo_bg.paste(logo, (offset, offset), logo)
        
        # Paste combined logo onto canvas
        center = (QR_SIZE - bg_size) // 2
        canvas.paste(logo_bg, (center, center), logo_bg)
        
    except Exception as e:
        print(f"Warning: Could not process logo. {e}")

    # 6. Security Border (Micro-Text)
    # Add a border around the QR code
    border_layer = Image.new("RGBA", (QR_SIZE, QR_SIZE), (255, 255, 255, 0))
    draw_border = ImageDraw.Draw(border_layer)
    
    # Define border area (inset slightly)
    border_inset = 20
    border_rect = [border_inset, border_inset, QR_SIZE - border_inset, QR_SIZE - border_inset]
    
    # Draw thin line
    draw_border.rectangle(border_rect, outline=(0, 0, 0, 255), width=2)
    
    # Micro-text "BITM • BITM..."
    micro_text = "BITM • " * 200
    try:
        font_micro = ImageFont.truetype("arial.ttf", 10) # Very small font
    except:
        font_micro = ImageFont.load_default()
        
    # We want to draw this text along the border. 
    # For simplicity in this script, we'll draw it just inside the top and bottom border lines
    # A full path text drawing is complex in PIL without external libs.
    # We will draw it on the 4 sides.
    
    def draw_text_line(draw, text, pos, angle, font):
        # Create small temp image for text
        # Estimate width
        tb = draw.textbbox((0,0), text, font=font)
        w = tb[2] - tb[0]
        h = tb[3] - tb[1]
        txt_img = Image.new("RGBA", (w, h + 10), (255, 255, 255, 0))
        d = ImageDraw.Draw(txt_img)
        d.text((0, 0), text, fill=(0, 0, 0, 255), font=font)
        
        rotated = txt_img.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        draw.bitmap(pos, rotated)

    # Top
    # draw_border.text((border_inset + 5, border_inset - 2), micro_text, fill=(0,0,0,255), font=font_micro)
    # Actually, let's just draw it simply on the edges.
    
    # Top edge
    draw_border.text((border_inset, border_inset - 12), micro_text[:150], fill=(0,0,0,255), font=font_micro)
    # Bottom edge
    draw_border.text((border_inset, QR_SIZE - border_inset + 2), micro_text[:150], fill=(0,0,0,255), font=font_micro)
    
    # Left edge (vertical)
    # Create vertical text image
    # ... This is getting complex for a simple script. 
    # Let's just add a simple aesthetic border with the text repeated.
    
    canvas = Image.alpha_composite(canvas, border_layer)

    # Save
    canvas.save(OUTPUT_PATH, "PNG")
    print(f"QR Code saved to {OUTPUT_PATH}")

if __name__ == "__main__":
    generate_premium_qr()
