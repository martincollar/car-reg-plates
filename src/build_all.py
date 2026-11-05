"""Build plates (face SVG, STLs, top view) and an overview sheet.

  python src/build_all.py                  every plate in plates/
  python src/build_all.py hornet iowa-sample
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(__file__).resolve().parent


def main():
    names = sys.argv[1:]
    plates = sorted(ROOT.glob("plates/*.json"))
    if names:
        plates = [p for p in plates if p.stem in names]
    for p in plates:
        for script in ("build_face.py", "make_stl.py"):
            subprocess.run([sys.executable, str(SRC / script), str(p)], check=True)

    # Overview sheet of every plate built so far
    views = [(p.parent.name, Image.open(p)) for p in sorted(ROOT.glob("output/*/topview.png"))]
    if not views:
        return
    w = max(im.width for _, im in views) // 3
    h = max(im.height for _, im in views) // 3
    cols, label_h, pad = 3, 28, 18
    rows = (len(views) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (w + pad) + pad, rows * (h + label_h + pad) + pad), "white")
    d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(ROOT / "fonts" / "Saira-SemiBold.ttf"), 18)
    for i, (name, im) in enumerate(views):
        x = pad + (i % cols) * (w + pad)
        y = pad + (i // cols) * (h + label_h + pad)
        d.text((x, y), name, fill="#333333", font=font)
        sheet.paste(im.resize((w, h)), (x, y + label_h))
    sheet.save(ROOT / "output" / "overview.png")
    print(f"wrote {ROOT / 'output' / 'overview.png'}")


if __name__ == "__main__":
    main()
