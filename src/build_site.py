"""Static web page with every plate of every state, for GitHub Pages: html/

  python src/build_site.py   -> html/index.html          landing page (sticker bomb, Browse + Printables links)
                                html/browse.html         the picker (state / type / plate dropdowns)
                                html/data.js             the plate list (from output/states/*/plates.json)
                                html/plates/<state>/<file>.svg   one vector preview per plate
                                html/stl/blank.gz, html/stl/<state>/<file>.gz   STL pieces for direct download
                                html/img/, html/fonts/    lineup and sticker-bomb pictures, heading font

Every plate STL from build_states.py is the same blank (BLANK_TRIS triangles) followed by the
plate's raised text. The site keeps the blank once and only the text part per plate, gzipped;
the page joins them back into the exact same binary STL when you click Download STL.

Run it after src/build_states.py (it reads plates.json) and src/lineup.py / src/sticker_bomb.py
(it copies their pictures). The page needs no server: open html/index.html directly or push it,
the workflow in .github/workflows/pages.yml publishes the folder.
"""
import gzip
import json
import shutil
import struct
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plate_engine import ROOT, build_svg  # noqa: E402

SITE = ROOT / "html"
BLANK = json.loads((ROOT / "blanks" / "Licence_Plate.json").read_text())
SERIES = {"sample": "Original example", "vanity": "Vanity", "random": "Random"}
BLANK_TRIS = 6648  # triangles of blanks/Licence_Plate.stl at the start of every plate STL
SHOWN_AS = {"custom": "vanity"}  # personal plates are listed with the vanity ones on the page
PICTURES = {  # output/previews/<src> -> html/img/<dst>, longest side
    "all-states.jpg": ("all-states.jpg", 2000),
    "sticker-bomb-facebook.jpg": ("sticker-bomb.jpg", 2600),
    "sticker-bomb-printables-3x4.jpg": ("sticker-bomb-3x4.jpg", 1800),
}


def plate_svg(name, tpl, p):
    plate = {"name": p["file"], "template": name, "serial": p["serial"]}
    if "county" in p:
        plate["text"] = {"county": p["county"]}
    return build_svg(plate, tpl, BLANK)


def stl_triangles(path):
    """Raw 50-byte triangle records of a binary STL."""
    b = path.read_bytes()
    n = struct.unpack_from("<I", b, 80)[0]
    if len(b) != 84 + 50 * n:
        raise ValueError(f"{path} is not a binary STL")
    return b[84:]


def write_gz(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", compresslevel=9, mtime=0) as gz:
        gz.write(data)


def split_stls(name, plates, blank):
    """Write the text part of each plate's STL to html/stl/<name>/<file>.gz; return the blank part.

    Plates without an STL (build_states.py --skip-stl) get no download.
    """
    out = SITE / "stl" / name
    if out.exists():
        shutil.rmtree(out)
    have = set()
    for p in plates:
        src = ROOT / "output" / "states" / name / "stl" / f"{p['file']}.stl"
        if not src.exists():
            continue
        tris = stl_triangles(src)
        head, text = tris[:50 * BLANK_TRIS], tris[50 * BLANK_TRIS:]
        if blank is None:
            blank = head
        elif head != blank:
            raise ValueError(f"{src}: does not start with the shared blank")
        write_gz(out / f"{p['file']}.gz", text)
        have.add(p["file"])
    return blank, have


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
    states, blank, n_stl = [], None, 0
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
        blank, have = split_stls(d.name, plates, blank)
        n_stl += len(have)
        states.append({
            "id": d.name,
            "name": tpl["state"],
            "year": tpl["year"],
            "colors": tpl["colors"],
            "format": tpl["serial_format"],
            "photo": tpl.get("photo"),
            "plates": [{k: p[k] for k in ("series", "serial", "file", "county") if k in p}
                       | {"series": SHOWN_AS.get(p["series"], p["series"])}
                       | ({"stl": 1} if p["file"] in have else {}) for p in plates],
        })
        print(f"{d.name}: {len(plates)} plates, {len(have)} STLs")
    data = {"series": SERIES, "states": states}
    (SITE / "data.js").write_text("window.PLATES = " + json.dumps(data, separators=(",", ":")) + ";\n")
    if blank is not None:
        write_gz(SITE / "stl" / "blank.gz", blank)
    copy_pictures()
    copy_font()
    total = sum(len(s["plates"]) for s in states)
    print(f"wrote {SITE.relative_to(ROOT)}/: {len(states)} states, {total} plates, {n_stl} STLs")


if __name__ == "__main__":
    main()
