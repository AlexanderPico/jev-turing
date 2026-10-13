"""Render the Safety Dance parody with exact, non-generated captions.

Run from any directory: python scripts/render_jev_dance_meme.py
Requires Pillow. The source frame is retained in docs/memes/.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/memes/safety-dance-template.jpg"
OUTPUT = ROOT / "site/media/we-can-jev.png"
FONT = Path("/System/Library/Fonts/Supplemental/Impact.ttf")
TOP = "We can Jev if we want to"
BOTTOM = "We can leave your models behind"


def main():
    base = Image.open(SOURCE).convert("RGB")
    width = 1200
    height = round(base.height * width / base.width)
    band = 150
    canvas = Image.new("RGB", (width, height + 2 * band), "black")
    canvas.paste(base.resize((width, height), Image.Resampling.LANCZOS), (0, band))
    draw = ImageDraw.Draw(canvas)
    for text, y in ((TOP, 0), (BOTTOM, band + height)):
        size = 82
        while True:
            font = ImageFont.truetype(str(FONT), size)
            bounds = draw.textbbox((0, 0), text, font=font)
            if bounds[2] - bounds[0] <= width - 64:
                break
            size -= 1
        x = (width - (bounds[2] - bounds[0])) / 2 - bounds[0]
        ty = y + (band - (bounds[3] - bounds[1])) / 2 - bounds[1]
        draw.text((x, ty), text, font=font, fill="white")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUTPUT)
    print(f"{OUTPUT}: {canvas.width}x{canvas.height}")


if __name__ == "__main__":
    main()
