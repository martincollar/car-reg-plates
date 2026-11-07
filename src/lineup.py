"""One picture with one plate for every state: output/previews/all-states.png (transparent)
and all-states.jpg (white background)

Each state shows its best plate. Martin's four favourites go to the states they suit
(H0R-N3T on Iowa, 3D Sets on Nebraska, Doppler on Florida, 51HHMD on Illinois),
and every other state gets a different vanity serial, so all keywords show up somewhere.
Edit PICKS to change a state's plate.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plate_engine import ROOT  # noqa: E402
from sticker_bomb import find_plate, sticker  # noqa: E402

PICKS = {
    "alaska": "PLA3D", "florida": "D0PPL3R", "georgia": "E-LIM8R", "idaho": "S/H 1F T3D",
    "illinois": "51HHMD", "iowa": "H0R-N3T", "kentucky": "1NF-1LL", "michigan": "HU-D5-0N",
    "minnesota": "R4C-1NG", "nebraska": "3D-S3TS", "new-york": "TW1N-HP", "ohio": "HRN-3T",
    "montana": "H-0RN3T", "pennsylvania": "HUD51", "utah": "H/R N3T", "wisconsin": "C4R-B8R",
    "ontario": "H0RN T", "alberta": "HR N3T", "cuba": "HUD-S0N",
}
COLS, PLATE_W = 5, 560
WIDTH, TOP, ROW_H = 3200, 150, 463


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", help="put this one serial on every state instead of PICKS")
    args = ap.parse_args()
    if args.serial:
        picks = {t.stem: args.serial for t in (ROOT / "templates").glob("*.json")}
        stem = "all-states-" + re.sub(r"[^A-Za-z0-9]+", "", args.serial).lower()
        title = f'"{args.serial}" - {len(picks)} states'
    else:
        picks, stem, title = PICKS, "all-states", "1950s license plates - 16 US states, Ontario, Alberta and Cuba"
    names = sorted(picks)
    rows = (len(names) + COLS - 1) // COLS
    SIZE = (WIDTH, TOP + 20 + rows * ROW_H)
    canvas = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    f_title = ImageFont.truetype(str(ROOT / "fonts" / "Saira-SemiBold.ttf"), 64)
    f_label = ImageFont.truetype(str(ROOT / "fonts" / "Saira-SemiBold.ttf"), 30)
    tw = d.textlength(title, font=f_title)
    d.text(((SIZE[0] - tw) / 2, 40), title, fill=(34, 34, 36), font=f_title)
    top = TOP
    cell_w, cell_h = SIZE[0] / COLS, (SIZE[1] - top - 20) / rows
    for i, name in enumerate(names):
        state, tpl, p = find_plate(name, picks[name])
        s = sticker(state, tpl, p, PLATE_W)
        cx = cell_w * (i % COLS) + cell_w / 2
        cy = top + cell_h * (i // COLS) + cell_h / 2 - 18
        canvas.paste(s, (int(cx - s.width / 2), int(cy - s.height / 2)), s)
        label = f"{tpl['state']} {tpl['year']}"
        lw = d.textlength(label, font=f_label)
        d.text((cx - lw / 2, cy + s.height / 2 - 30), label, fill=(70, 70, 74), font=f_label)
    out = ROOT / "output" / "previews"
    out.mkdir(parents=True, exist_ok=True)
    canvas.save(out / f"{stem}.png")
    white = Image.new("RGB", SIZE, (255, 255, 255))
    white.paste(canvas, (0, 0), canvas)
    white.save(out / f"{stem}.jpg", quality=92)
    print(f"wrote {out / stem}.png and {stem}.jpg")


if __name__ == "__main__":
    main()
