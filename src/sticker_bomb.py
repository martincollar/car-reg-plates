"""Sticker-bomb collages of plates from every state, for social posts and model pages.

  python src/sticker_bomb.py      -> output/previews/sticker-bomb-facebook.jpg (1.91:1)
                                     output/previews/sticker-bomb-printables-3x4.jpg (3:4)

Plates are taken from output/states/<state>/plates.json (build those first with src/build_states.py):
mostly vanity serials, plus the real 1954 examples and a few random ones, every state mixed.
The HEROES are drawn last, a bit larger and barely rotated, so each one is fully visible on top.
"""
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plate_engine import ROOT, build_svg  # noqa: E402
from vanity import preview  # noqa: E402

BLANK = json.loads((ROOT / "blanks" / "Licence_Plate.json").read_text())
CANVASES = {"sticker-bomb-facebook.jpg": (3600, 1885), "sticker-bomb-printables-3x4.jpg": (2400, 3200)}
# (state, serial) always on top, fully visible: Martin's H0R-N3T, 3D Sets, Doppler and 51HHMD
HEROES = [("iowa", "H0R-N3T"), ("nebraska", "3D-S3TS"), ("florida", "D0PPL3R"), ("illinois", "51HHMD")]
HERO_SCALE, BACKGROUND_SCALE = 1.3, 0.85


def sticker(name, tpl, p, width):
    """Plate render with rounded corners, a white die-cut border and a soft shadow (RGBA)."""
    plate = {"name": "s", "template": name, "serial": p["serial"]}
    if "county" in p:
        plate["text"] = {"county": p["county"]}
    big = preview(build_svg(plate, tpl, BLANK), tpl["colors"]["background"], tpl["colors"]["ink"], width=width * 2)
    img = big.resize((width, int(big.height * width / big.width)), Image.LANCZOS)
    w, h = img.size
    r = int(w * 0.035)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    border = int(w * 0.03)
    W, H = w + 2 * border, h + 2 * border
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(out).rounded_rectangle((0, 0, W - 1, H - 1), r + border, fill=(255, 255, 255, 255))
    out.paste(img, (border, border), mask)
    pad = int(w * 0.06)
    shadow = Image.new("RGBA", (W + 2 * pad, H + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + pad // 3, pad + W, pad + H + pad // 3), r + border, fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(pad / 2.5))
    shadow.alpha_composite(out, (pad, pad))
    return shadow


def find_plate(name, serial):
    tpl = json.loads((ROOT / "templates" / f"{name}.json").read_text())
    plates = json.loads((ROOT / "output" / "states" / name / "plates.json").read_text())
    p = next((p for p in plates if p["serial"] == serial), {"serial": serial})
    return name, tpl, p


def collage(size, pool, rng, out_path):
    Wc, Hc = size
    canvas = Image.new("RGB", size, (34, 34, 36))
    base_w = int(min(Wc, Hc) * 0.30 * BACKGROUND_SCALE)
    cell_w, cell_h = int(base_w * 0.78), int(base_w * 0.42)
    cells = [(x, y) for y in range(-cell_h // 2, Hc + cell_h, cell_h) for x in range(-cell_w // 2, Wc + cell_w, cell_w)]
    rng.shuffle(cells)
    for (cx, cy) in cells:
        name, tpl, p = rng.choice(pool)
        width = int(base_w * rng.uniform(0.85, 1.2))
        s = sticker(name, tpl, p, width).rotate(rng.uniform(-28, 28), resample=Image.BICUBIC, expand=True)
        x = cx + rng.randint(-cell_w // 3, cell_w // 3) - s.width // 2
        y = cy + rng.randint(-cell_h // 3, cell_h // 3) - s.height // 2
        canvas.paste(s, (x, y), s)
    # heroes on top in a 2 x 2 arrangement, apart from each other
    hero_w = int(min(Wc, Hc) * 0.30 * HERO_SCALE)
    spots = [(0.29, 0.30), (0.71, 0.32), (0.31, 0.70), (0.69, 0.68)]
    if Hc > Wc:  # portrait: narrower and staggered so neighbours don't overlap
        hero_w = int(Wc * 0.37)
        spots = [(0.28, 0.22), (0.72, 0.36), (0.28, 0.58), (0.72, 0.74)]
    for (name, serial), (fx, fy) in zip(HEROES, spots):
        s = sticker(*find_plate(name, serial), hero_w).rotate(rng.uniform(-6, 6), resample=Image.BICUBIC, expand=True)
        canvas.paste(s, (int(fx * Wc - s.width / 2), int(fy * Hc - s.height / 2)), s)
    canvas.save(out_path, quality=90)
    print(f"wrote {out_path} ({len(cells)} stickers + {len(HEROES)} on top)")


def main():
    rng = random.Random(1951)
    pool = []
    for d in sorted((ROOT / "output" / "states").iterdir()):
        if not (d / "plates.json").exists():
            continue
        tpl = json.loads((ROOT / "templates" / f"{d.name}.json").read_text())
        plates = json.loads((d / "plates.json").read_text())
        vanity = [p for p in plates if p["series"] in ("vanity", "custom")]
        pool += [(d.name, tpl, p) for p in rng.sample(vanity, min(10, len(vanity)))]
        pool += [(d.name, tpl, p) for p in plates if p["series"] == "sample"]
        randoms = [p for p in plates if p["series"] == "random"]
        pool += [(d.name, tpl, p) for p in rng.sample(randoms, min(2, len(randoms)))]
    out = ROOT / "output" / "previews"
    out.mkdir(exist_ok=True)
    for fname, size in CANVASES.items():
        collage(size, pool, rng, out / fname)


if __name__ == "__main__":
    main()
