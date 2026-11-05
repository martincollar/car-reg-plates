"""Build plates (face SVG, STLs, top view) and overview sheets.

  python src/build_all.py                       every plate in plates/
  python src/build_all.py hornet iowa-sample    only these plates
  python src/build_all.py --series custom       only one series (sample, custom or random)

Overview sheets (rebuilt from everything in output/):
  output/overview-<series>.png    one sheet per series
  output/overview.png             the state samples
"""
import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(__file__).resolve().parent


def sheet(items, out, cols=4):
    """items: [(label, topview path)] -> contact sheet PNG."""
    if not items:
        return
    ims = [(label, Image.open(p)) for label, p in items]
    w = max(im.width for _, im in ims) // 3
    h = max(im.height for _, im in ims) // 3
    label_h, pad = 26, 16
    rows = (len(ims) + cols - 1) // cols
    img = Image.new("RGB", (cols * (w + pad) + pad, rows * (h + label_h + pad) + pad), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(ROOT / "fonts" / "Saira-SemiBold.ttf"), 17)
    for i, (label, im) in enumerate(ims):
        x = pad + (i % cols) * (w + pad)
        y = pad + (i // cols) * (h + label_h + pad)
        d.text((x, y), label, fill="#333333", font=font)
        img.paste(im.resize((w, h)), (x, y + label_h))
    img.save(out)
    print(f"wrote {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--series")
    args = ap.parse_args()

    plates = []
    for path in sorted(ROOT.glob("plates/*.json")):
        cfg = json.loads(path.read_text())
        if args.names and path.stem not in args.names:
            continue
        if args.series and cfg.get("series") != args.series:
            continue
        plates.append(path)
    for p in plates:
        for script in ("build_face.py", "make_stl.py"):
            subprocess.run([sys.executable, str(SRC / script), str(p)], check=True)

    # Overview sheets of every built plate, grouped by series and ordered by state
    by_series = defaultdict(list)
    for path in sorted(ROOT.glob("plates/*.json")):
        cfg = json.loads(path.read_text())
        view = ROOT / "output" / cfg["name"] / "topview.png"
        if view.exists():
            by_series[cfg.get("series", "random")].append((cfg["template"], cfg["name"], view))
    for series, items in by_series.items():
        items.sort()
        sheet([(name, view) for _, name, view in items], ROOT / "output" / f"overview-{series}.png")
    if "sample" in by_series:
        sheet([(tpl, view) for tpl, _, view in sorted(by_series["sample"])], ROOT / "output" / "overview.png", cols=3)


if __name__ == "__main__":
    main()
