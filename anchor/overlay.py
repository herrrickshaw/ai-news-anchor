"""Render the news-graphics layer with PIL (this ffmpeg build has no drawtext)."""
from PIL import Image, ImageDraw, ImageFont
import textwrap

def _font(size, bold=True):
    for p in ["/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc"]:
        try: return ImageFont.truetype(p, size)
        except OSError: pass
    return ImageFont.load_default()

def make_overlay(headline, channel, date, size=(1080, 1920), path="overlay.png"):
    W, H = size
    im = Image.new("RGBA", size, (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 130], fill=(150, 10, 20, 235))                      # top bar
    d.text((40, 38), f"{channel}  |  NEWS", font=_font(52), fill="white")
    d.text((W - 40, 52), date, font=_font(38, False), fill="white", anchor="ra")
    y0 = int(H * 0.70)                                                         # lower third
    lines = textwrap.wrap(headline, 26)[:3]
    box_h = 60 + 72 * len(lines)
    d.rectangle([0, y0, W, y0 + box_h], fill=(10, 20, 60, 225))
    d.rectangle([0, y0, 18, y0 + box_h], fill=(230, 40, 50, 255))
    for i, l in enumerate(lines):
        d.text((50, y0 + 30 + 72 * i), l, font=_font(58), fill="white")
    d.rectangle([0, H - 110, W, H], fill=(0, 0, 0, 230))                       # ticker strip backdrop
    im.save(path); return path

def make_ticker(text, height=110, path="ticker.png"):
    f = _font(50)
    text = "   ◆   ".join([text] * 4)
    w = int(ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(text, font=f)) + 40
    im = Image.new("RGBA", (w, height), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((20, height // 2), text, font=f, fill=(255, 220, 80, 255), anchor="lm")
    im.save(path); return path, w
