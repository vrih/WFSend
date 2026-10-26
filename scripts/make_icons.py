#!/usr/bin/env python3
"""Draw the site's favicon, home screen icons and share image into site/icons/.

The mark is three rising white bars on a forest green square, standing on an
amber baseline: the masthead's colours, and no text, so it stays legible at
16 pixels. It writes:

  favicon.svg             modern browsers (rounded corners)
  favicon.ico             older browsers and anything requesting /favicon.ico
  apple-touch-icon.png    iPhone and iPad home screen (180px, square: iOS rounds it)
  icon-192.png, icon-512.png   Android and the web app manifest
  icon-maskable-512.png   Android adaptive icons (mark kept inside the safe zone)
  share.png               the preview shown when a link is shared (1200 x 630)

build.py copies these to the root of _site/. The outputs are committed, so
only rerun this after changing the design.

Usage:
  python scripts/make_icons.py

Needs Pillow (pip install pillow), which the site build does not. The share
image uses the site's typeface, Atkinson Hyperlegible, downloaded from Google
Fonts each time, so it also needs network access.
"""
import io
import re
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "site" / "icons"
FOREST, AMBER, WHITE = "#24543a", "#e3a032", "#ffffff"
BARS = (140, 230, 320)  # heights, rising left to right, on a 512 grid
FONT_CSS = "https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700"
UA = {"User-Agent": "wfsend-data-fetch"}


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


def fonts():
    """Atkinson Hyperlegible regular and bold, as font files Pillow can read."""
    with urllib.request.urlopen(urllib.request.Request(FONT_CSS, headers=UA)) as r:
        urls = re.findall(r"url\((https://[^)]+\.ttf)\)", r.read().decode())
    out = []
    for url in urls[:2]:  # 400 then 700, in the order asked for
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA)) as r:
            out.append(r.read())
    return out


def share_image():
    """The mark beside the site's name and tagline, in the masthead colours."""
    regular, bold = fonts()
    font = lambda data, size: ImageFont.truetype(io.BytesIO(data), size)
    im = Image.new("RGB", (1200, 630), FOREST)
    d = ImageDraw.Draw(im)
    k = 170 / 512  # the mark, 170px square, top left
    for fill, b, r in shapes(1.0):
        d.rounded_rectangle([80 + (b[0] - 84) * k, 70 + (b[1] - 80) * k, 80 + (b[2] - 84) * k, 70 + (b[3] - 80) * k],
                            radius=r * k, fill=fill)
    title = font(bold, 84)
    d.text((80, 245), "Waltham Forest", font=title, fill=WHITE)
    x = 80
    for word in ("SEND", " data"):
        d.text((x, 340), word, font=title, fill=WHITE)
        if word == "SEND":  # underlined in amber, as in the masthead
            d.rectangle([x, 340 + 92, x + d.textlength(word, font=title), 340 + 100], fill=AMBER)
        x += d.textlength(word, font=title)
    small = font(regular, 32)
    d.text((80, 480), "How SEND services in Waltham Forest are performing.", font=small, fill=WHITE)
    d.text((80, 522), "Independent. Every figure links to its public source.", font=small, fill="#e4efe6")
    return im


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
    share_image().save(OUT / "share.png", optimize=True)
    print(f"wrote icons to {OUT}")


if __name__ == "__main__":
    main()
