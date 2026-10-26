#!/usr/bin/env python3
"""Draw the site's favicon and home screen icons into site/icons/.

The mark is three rising white bars on a forest green square, standing on an
amber baseline: the masthead's colours, and no text, so it stays legible at
16 pixels. It writes:

  favicon.svg             modern browsers (rounded corners)
  favicon.ico             older browsers and anything requesting /favicon.ico
  apple-touch-icon.png    iPhone and iPad home screen (180px, square: iOS rounds it)
  icon-192.png, icon-512.png   Android and the web app manifest
  icon-maskable-512.png   Android adaptive icons (mark kept inside the safe zone)

build.py copies these to the root of _site/. The outputs are committed, so
only rerun this after changing the design.

Usage:
  python scripts/make_icons.py

Needs Pillow (pip install pillow), which the site build does not.
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "site" / "icons"
FOREST, AMBER, WHITE = "#24543a", "#e3a032", "#ffffff"
BARS = (140, 230, 320)  # heights, rising left to right, on a 512 grid


def shapes(scale):
    """(fill, box, corner radius) for each shape on a 512 square. scale < 1
    shrinks the mark towards the centre, for icons cropped to a circle."""
    def box(x, y, w, h):
        return [256 + (v - 256) * scale for v in (x, y, x + w, y + h)]
    out = [(WHITE, box(84 + i * 128, 400 - h, 88, h), 6 * scale) for i, h in enumerate(BARS)]
    return out + [(AMBER, box(84, 400, 344, 28), 4 * scale)]


def svg(radius=0, scale=1.0):
    def rect(fill, b, r):
        return f'<rect x="{b[0]:g}" y="{b[1]:g}" width="{b[2] - b[0]:g}" height="{b[3] - b[1]:g}" rx="{r:g}" fill="{fill}"/>'
    body = "".join(rect(*s) for s in shapes(scale))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
            f'<rect width="512" height="512" rx="{radius}" fill="{FOREST}"/>{body}</svg>\n')


def png(size, radius=0, scale=1.0):
    """Draw at 512px (or more), then shrink, which smooths the edges."""
    big = max(512, size * 4)
    k = big / 512
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, big - 1, big - 1], radius=radius * k, fill=FOREST)
    for fill, b, r in shapes(scale):
        d.rounded_rectangle([v * k for v in b], radius=r * k, fill=fill)
    return im.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "favicon.svg").write_text(svg(radius=96), encoding="utf-8")
    # home screen icons are full squares: the platform rounds or crops them
    png(180).convert("RGB").save(OUT / "apple-touch-icon.png", optimize=True)
    png(192).save(OUT / "icon-192.png", optimize=True)
    png(512).save(OUT / "icon-512.png", optimize=True)
    png(512, scale=0.78).save(OUT / "icon-maskable-512.png", optimize=True)
    # one .ico holding 48, 32 and 16 pixel versions, each drawn at its own size
    frames = [png(s, radius=96) for s in (48, 32, 16)]
    frames[0].save(OUT / "favicon.ico", format="ICO", sizes=[(s, s) for s in (48, 32, 16)],
                   append_images=frames[1:])
    print(f"wrote icons to {OUT}")


if __name__ == "__main__":
    main()
