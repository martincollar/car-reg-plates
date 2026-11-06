"""Generate vanity serials from keywords for every state, with letter-to-number swaps,
and draw preview sheets (no STL) so you can pick favourites.

  python src/vanity.py                     keywords -> vanity_plates.json + output/vanity/<state>-NN.jpg
  python src/vanity.py --states iowa utah  only these states
  python src/vanity.py --no-sheets         only the list

A serial is kept for a state only if it has exactly as many characters as that state's
format (e.g. Michigan LL-99-99 = 6, Florida 9L99999 = 7); the characters are then poured
into the state's grouping, separators and stacked prefix.

To build real plates from a pick, copy serials into custom_plates.json and run
python src/generate.py --list custom_plates.json && python src/build_all.py --series custom
"""
import argparse
import itertools
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from shapely import affinity
from shapely.geometry import MultiPolygon
from svgelements import SVG, Path as SvgPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plate_engine import ROOT, build_svg  # noqa: E402
from make_stl import path_geometry  # noqa: E402
from generate import random_serial  # noqa: E402

LEET = {"O": "0", "E": "3", "A": "4", "I": "1", "S": "5", "T": "7", "G": "6", "B": "8"}


def leet_variants(word):
    """Every combination of swap types present in the word (O->0 everywhere, E->3 everywhere, ...)."""
    kinds = sorted({c for c in word if c in LEET})
    out = []
    for n in range(len(kinds) + 1):
        for combo in itertools.combinations(kinds, n):
            out.append(("".join(LEET[c] if c in combo else c for c in word), n))
    return out


def pour(serial_chars, fmt):
    """Put characters into a format: '9'/'L' take the next character, anything else is copied."""
    it = iter(serial_chars)
    return "".join(next(it) if c in "9L" else c for c in fmt)


def slots(fmt):
    return sum(c in "9L" for c in fmt)


def preview(svg_text, bg, ink, width=420):
    """Rasterise a face SVG with PIL (works without Cairo)."""
    tmp = Path("/tmp/_vanity_face.svg")
    tmp.write_text(svg_text)
    svg = SVG.parse(str(tmp), ppi=25.4)
    W, H = svg.width, svg.height
    s = width / W
    img = Image.new("RGB", (width, int(H * s)), bg)
    d = ImageDraw.Draw(img)

    def fill(geom, colour):
        parts = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
        for g in parts:
            if g.is_empty:
                continue
            d.polygon([(x * s, y * s) for x, y in g.exterior.coords], fill=colour)
            for h in g.interiors:
                d.polygon([(x * s, y * s) for x, y in h.coords], fill=bg)

    for el in svg.elements():
        if not isinstance(el, SvgPath):
            continue
        if el.id == "face":
            continue
        g = path_geometry(el, samples_per_curve=8)
        stroke = el.values.get("stroke")
        if stroke and stroke != "none":
            g = g.buffer(float(el.values.get("stroke-width", 0)) / 2)
        fill(g, ink)
    return img


def sheet(items, title, out, cols=5):
    w, h = items[0][1].size
    pad, label_h, title_h = 12, 22, 44
    rows = (len(items) + cols - 1) // cols
    img = Image.new("RGB", (cols * (w + pad) + pad, title_h + rows * (h + label_h + pad) + pad), "white")
    d = ImageDraw.Draw(img)
    f_title = ImageFont.truetype(str(ROOT / "fonts" / "Saira-SemiBold.ttf"), 26)
    f_label = ImageFont.truetype(str(ROOT / "fonts" / "Saira-SemiBold.ttf"), 16)
    d.text((pad, 8), title, fill="#222222", font=f_title)
    for i, (label, im) in enumerate(items):
        x = pad + (i % cols) * (w + pad)
        y = title_h + (i // cols) * (h + label_h + pad)
        d.text((x, y), label, fill="#333333", font=f_label)
        img.paste(im, (x, y + label_h))
    img.save(out, quality=75)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", nargs="*")
    ap.add_argument("--keywords", default=str(ROOT / "vanity_keywords.json"))
    ap.add_argument("--per-sheet", type=int, default=100)
    ap.add_argument("--no-sheets", action="store_true")
    ap.add_argument("--random", type=int, default=0, help="also make N random serials per state")
    ap.add_argument("--seed", type=int, default=1954)
    args = ap.parse_args()

    kw = json.loads(Path(args.keywords).read_text())["keywords"]
    pool = {}
    for spellings in kw.values():
        for level, c in enumerate(spellings):
            exact = c.startswith("=")  # "=C4RB8R": use exactly as written, no extra swaps
            c = c.lstrip("=").upper()
            styled = any(ch.isdigit() for ch in c)
            for v, n_swaps in ([(c, 0)] if exact else leet_variants(c)):
                if not any(ch.isdigit() for ch in v):
                    continue  # a plate can't be all letters
                # styled spellings as written come first, then by number of extra swaps
                rank = (0 if (styled and n_swaps == 0) else 1, n_swaps, level)
                pool[v] = min(rank, pool.get(v, (9, 99, 99)))

    blank = json.loads((ROOT / "blanks" / "Licence_Plate.json").read_text())
    names = args.states or sorted(p.stem for p in (ROOT / "templates").glob("*.json"))
    result = {}
    for name in names:
        tpl = json.loads((ROOT / "templates" / f"{name}.json").read_text())
        n = slots(tpl["serial_format"])
        # styled spellings as written first, then fewer extra swaps, then keyword list order
        chosen = sorted((v for v in pool if len(v) == n), key=lambda v: (pool[v], v))
        result[name] = [pour(v, tpl["serial_format"]) for v in chosen]
        print(f"{name}: {len(chosen)} serials ({n} characters)")

    out_json = ROOT / "vanity_plates.json"
    old = json.loads(out_json.read_text()) if out_json.exists() and args.states else {}
    old.update(result)
    out_json.write_text(json.dumps(old, indent=1) + "\n")

    randoms = {}
    if args.random:
        rng = random.Random(args.seed)
        for name in names:
            tpl = json.loads((ROOT / "templates" / f"{name}.json").read_text())
            seen = []
            while len(seen) < args.random:
                s = random_serial(tpl["serial_format"], rng)
                if s not in seen:
                    seen.append(s)
            randoms[name] = seen
        out_r = ROOT / "random_plates.json"
        old_r = json.loads(out_r.read_text()) if out_r.exists() and args.states else {}
        old_r.update(randoms)
        out_r.write_text(json.dumps(old_r, indent=1) + "\n")

    if args.no_sheets:
        return
    for kind, lists in (("vanity", result), ("random", randoms)):
        out_dir = ROOT / "output" / kind
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, serials in lists.items():
            tpl = json.loads((ROOT / "templates" / f"{name}.json").read_text())
            bg, ink = tpl["colors"]["background"], tpl["colors"]["ink"]
            rng = random.Random(name)
            pages = max(1, (len(serials) + args.per_sheet - 1) // args.per_sheet)
            for page, start in enumerate(range(0, len(serials), args.per_sheet), 1):
                items = []
                for serial in serials[start:start + args.per_sheet]:
                    plate = {"name": "v", "template": name, "serial": serial}
                    if "counties" in tpl:
                        plate["text"] = {"county": rng.choice(tpl["counties"])}
                    svg = build_svg(plate, tpl, blank)
                    items.append((serial, preview(svg, bg, ink, width=300)))
                title = f"{tpl['state']} {tpl['year']} - {kind} {page}/{pages} ({len(serials)} total)"
                suffix = f"-{page:02d}" if pages > 1 or kind == "vanity" else ""
                sheet(items, title, out_dir / f"{name}{suffix}.jpg")
            print(f"{name}: {kind} sheets written")


if __name__ == "__main__":
    main()
