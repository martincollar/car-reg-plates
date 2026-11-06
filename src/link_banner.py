"""Banner for the Printables description that points to the plate picker website:
output/previews/browse-link-banner.png and .jpg

Printables images are not clickable, so the arrow points down at the text link that goes
right under the image. Edit the constants below to change the wording or the plates.
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plate_engine import ROOT  # noqa: E402
from sticker_bomb import find_plate, sticker  # noqa: E402

SIZE = (1600, 640)
BG_TOP, BG_BOTTOM = (255, 255, 255), (255, 255, 255)
TEXT, MUTED, ACCENT, ARROW = (30, 30, 34), (105, 103, 98), (233, 178, 60), (30, 30, 34)
HEADLINE = ["You can use this website", "to preview all."]
SUBLINE = "Every plate of every state, with a Download STL button"
URL = "martincollar.github.io/car-reg-plates"
PLATES = [("montana", "H-0RN3T", -9), ("florida", "D0PPL3R", 6), ("iowa", "H0R-N3T", -3)]
PLATE_W = 400
FONT = ROOT / "fonts" / "Saira-SemiBold.ttf"


def gradient(size, top, bottom):
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(size[1]):
        t = y / (size[1] - 1)
        d.line([(0, y), (size[0], y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img.convert("RGBA")


def bezier(p0, p1, p2, p3, steps=80):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        pts.append(tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t ** 2 * c + t ** 3 * e
                         for a, b, c, e in zip(p0, p1, p2, p3)))
    return pts


def arrow(d, pts, width, head, color):
    """Curved arrow along pts that tapers in from the tail, with a triangular head at the end."""
    (x1, y1), (x2, y2) = pts[-4], pts[-1]
    ang = math.atan2(y2 - y1, x2 - x1)
    base = (x2 - head * 0.8 * math.cos(ang), y2 - head * 0.8 * math.sin(ang))
    body = [p for p in pts if math.dist(p, pts[-1]) > head * 0.7]
    for i in range(len(body) - 1):
        w = width * (0.45 + 0.55 * min(1, i / (len(body) * 0.4)))
        d.line([body[i], body[i + 1]], fill=color, width=int(w))
        d.ellipse((body[i][0] - w / 2, body[i][1] - w / 2, body[i][0] + w / 2, body[i][1] + w / 2), fill=color)
    left = (base[0] + head * 0.6 * math.cos(ang + math.pi / 2), base[1] + head * 0.6 * math.sin(ang + math.pi / 2))
    right = (base[0] + head * 0.6 * math.cos(ang - math.pi / 2), base[1] + head * 0.6 * math.sin(ang - math.pi / 2))
    d.polygon([(x2, y2), left, right], fill=color)


def main():
    canvas = gradient(SIZE, BG_TOP, BG_BOTTOM)
    d = ImageDraw.Draw(canvas)

    # fanned plates on the left
    for i, (name, serial, angle) in enumerate(PLATES):
        state, tpl, p = find_plate(name, serial)
        s = sticker(state, tpl, p, PLATE_W).rotate(angle, resample=Image.BICUBIC, expand=True)
        cx, cy = 1290 + (i - 1) * 40, 160 + i * 155
        canvas.alpha_composite(s, (int(cx - s.width / 2), int(cy - s.height / 2)))

    # headline, subline and the URL pill
    x = 90
    f_head = ImageFont.truetype(str(FONT), 68)
    f_sub = ImageFont.truetype(str(FONT), 30)
    f_url = ImageFont.truetype(str(FONT), 40)
    y = 90
    for line in HEADLINE:
        d.text((x, y), line, fill=TEXT, font=f_head)
        y += 88
    d.text((x, y + 14), SUBLINE, fill=MUTED, font=f_sub)
    y += 90
    uw = d.textlength(URL, font=f_url)
    pill = (x, y, x + uw + 70, y + 76)
    d.rounded_rectangle(pill, 38, fill=ACCENT)
    d.text((x + 35, y + 38), URL, fill=(26, 26, 28), font=f_url, anchor="lm")

    # arrow from under the button curving down to the bottom-left corner, toward the text link
    # under the image (Printables images can't be clicked), which sits at the left of the page
    start = (pill[0] + 330, pill[3] + 26)
    end = (pill[0] + 70, SIZE[1] - 18)
    pts = bezier(start, (start[0] + 20, start[1] + 110), (end[0], end[1] - 150), end)
    arrow(d, pts, 16, 54, ARROW)

    out = ROOT / "output" / "previews"
    out.mkdir(parents=True, exist_ok=True)
    canvas.save(out / "browse-link-banner.png")
    canvas.convert("RGB").save(out / "browse-link-banner.jpg", quality=92)
    print(f"wrote {out / 'browse-link-banner'}.png and .jpg")


if __name__ == "__main__":
    main()
