"""Generate the app icons in web/static (run: python web/scripts/make_icons.py).

Motif: a graduated measuring tape (a "pige" is a measuring rod) under the letter P.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

INK = (36, 64, 184)
TAPE = (242, 194, 48)
TICK = (26, 34, 48)
WHITE = (255, 255, 255)
OUT = Path(__file__).resolve().parent.parent / "static"


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw(size: int, safe: float) -> Image.Image:
    """``safe`` = fraction of the canvas kept free on each side (maskable icons need ~10%)."""
    img = Image.new("RGB", (size, size), INK)
    d = ImageDraw.Draw(img)
    inner = size * (1 - 2 * safe)
    x0 = size * safe
    # Letter
    font = _font(int(inner * 0.62))
    box = d.textbbox((0, 0), "P", font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text((size / 2 - w / 2 - box[0], x0 + inner * 0.36 - h / 2 - box[1]), "P", font=font, fill=WHITE)
    # Tape with graduations
    ty0, ty1 = x0 + inner * 0.72, x0 + inner * 0.90
    d.rectangle([x0, ty0, x0 + inner, ty1], fill=TAPE)
    steps = 10
    for i in range(1, steps):
        tx = x0 + inner * i / steps
        tall = i % 5 == 0
        d.line([tx, ty0, tx, ty0 + (ty1 - ty0) * (0.7 if tall else 0.4)], fill=TICK, width=max(1, size // 96))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw(192, 0.08).save(OUT / "icon-192.png")
    draw(512, 0.08).save(OUT / "icon-512.png")
    draw(512, 0.16).save(OUT / "icon-maskable-512.png")
    draw(180, 0.08).save(OUT / "apple-touch-icon.png")
    tb = Path(__file__).resolve().parents[2] / "thunderbird" / "icons"
    tb.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 64, 128):
        draw(size, 0.0).save(tb / f"icon-{size}.png")


if __name__ == "__main__":
    main()
