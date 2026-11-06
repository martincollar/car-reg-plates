"""Static web page with every plate of every state, for GitHub Pages: html/

  python src/build_site.py   -> html/index.html          the page (state / type / plate dropdowns)
                                html/data.js             the plate list (from output/states/*/plates.json)
                                html/plates/<state>/<file>.svg   one vector preview per plate
                                html/img/, html/fonts/    lineup and sticker-bomb pictures, heading font

Run it after src/build_states.py (it reads plates.json) and src/lineup.py / src/sticker_bomb.py
(it copies their pictures). The page needs no server: open html/index.html directly or push it,
the workflow in .github/workflows/pages.yml publishes the folder.
"""
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plate_engine import ROOT, build_svg  # noqa: E402

SITE = ROOT / "html"
BLANK = json.loads((ROOT / "blanks" / "Licence_Plate.json").read_text())
SERIES = {"sample": "Original example", "custom": "Personal", "vanity": "Vanity", "random": "Random"}
PICTURES = {  # output/previews/<src> -> html/img/<dst>, longest side
    "all-states.jpg": ("all-states.jpg", 2000),
    "sticker-bomb-facebook.jpg": ("sticker-bomb.jpg", 1800),
}


def plate_svg(name, tpl, p):
    plate = {"name": p["file"], "template": name, "serial": p["serial"]}
    if "county" in p:
        plate["text"] = {"county": p["county"]}
    return build_svg(plate, tpl, BLANK)


def copy_pictures():
    dst_dir = SITE / "img"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for src, (dst, side) in PICTURES.items():
        img = Image.open(ROOT / "output" / "previews" / src).convert("RGB")
        img.thumbnail((side, side), Image.LANCZOS)
        img.save(dst_dir / dst, quality=85, optimize=True, progressive=True)


def copy_font():
    (SITE / "fonts").mkdir(parents=True, exist_ok=True)
    for f in ("Saira-SemiBold.ttf", "OFL-Saira.txt"):
        shutil.copy2(ROOT / "fonts" / f, SITE / "fonts" / f)


def main():
    states = []
    for d in sorted((ROOT / "output" / "states").iterdir()):
        if not (d / "plates.json").exists():
            continue
        tpl = json.loads((ROOT / "templates" / f"{d.name}.json").read_text())
        plates = json.loads((d / "plates.json").read_text())
        out = SITE / "plates" / d.name
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        for p in plates:
            (out / f"{p['file']}.svg").write_text(plate_svg(d.name, tpl, p))
        states.append({
            "id": d.name,
            "name": tpl["state"],
            "year": tpl["year"],
            "colors": tpl["colors"],
            "format": tpl["serial_format"],
            "photo": tpl.get("photo"),
            "plates": [{k: p[k] for k in ("series", "serial", "file", "county") if k in p} for p in plates],
        })
        print(f"{d.name}: {len(plates)} plates")
    data = {"series": SERIES, "states": states}
    (SITE / "data.js").write_text("window.PLATES = " + json.dumps(data, separators=(",", ":")) + ";\n")
    copy_pictures()
    copy_font()
    total = sum(len(s["plates"]) for s in states)
    print(f"wrote {SITE.relative_to(ROOT)}/: {len(states)} states, {total} plates")


if __name__ == "__main__":
    main()
