"""Create plate configs: random serials in each state's real 1954 format, or your own text.

  python src/generate.py michigan                 one random Michigan plate
  python src/generate.py michigan -n 5            five random Michigan plates
  python src/generate.py all -n 2                 two random plates for every state
  python src/generate.py iowa --serial H0R-N3T    your own text on the Iowa layout
  python src/generate.py iowa --serial H0R-N3T --set year_right=51   override any text by id
  python src/generate.py --list custom_plates.json   custom serials for many states at once

Serial formats use 9 for a digit and L for a letter; "-" is the state's separator
(dot, dash or cross) and a space is a gap. Plate configs go to plates/, then build them
with: python src/build_all.py <name> ...
"""
import argparse
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"   # no I, O, Q: easily confused with 1 and 0


def random_serial(fmt, rng):
    return "".join(rng.choice("0123456789") if c == "9" else rng.choice(LETTERS) if c == "L" else c for c in fmt)


def write_plate(tpl_name, serial, series, text, name, rng):
    """Write plates/<name>.json and return the name."""
    tpl = json.loads((ROOT / "templates" / f"{tpl_name}.json").read_text())
    slug = re.sub(r"[^A-Za-z0-9]+", "", serial).lower()
    plate = {"name": name or f"{tpl_name}-{slug}", "template": tpl_name, "series": series, "serial": serial}
    text = dict(text)
    if "counties" in tpl and "county" not in text:
        text["county"] = rng.choice(tpl["counties"])
    if text:
        plate["text"] = text
    (ROOT / "plates" / f"{plate['name']}.json").write_text(json.dumps(plate, indent=2) + "\n")
    return plate["name"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("template", nargs="?", help="template name (see templates/) or 'all'")
    ap.add_argument("--list", help="JSON file {state: [serial, ...]} of custom serials")
    ap.add_argument("-n", "--count", type=int, default=1)
    ap.add_argument("--serial", help="your own serial, e.g. H0R-N3T")
    ap.add_argument("--name", help="plate name (default: <template>-<serial>)")
    ap.add_argument("--set", action="append", default=[], metavar="ID=TEXT", help="override an element's text by id")
    ap.add_argument("--seed", type=int)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    if args.list:
        made = []
        for tpl_name, serials in json.loads(Path(args.list).read_text()).items():
            if tpl_name.startswith("_") or not isinstance(serials, list):
                continue  # notes, and the "personal" section used by build_states.py
            for serial in serials:
                made.append(write_plate(tpl_name, serial, "custom", {}, None, rng))
        print("created:", " ".join(made))
        return
    if not args.template:
        ap.error("give a template name, 'all', or --list")
    names = sorted(p.stem for p in (ROOT / "templates").glob("*.json")) if args.template == "all" else [args.template]
    made = []
    for tpl_name in names:
        tpl = json.loads((ROOT / "templates" / f"{tpl_name}.json").read_text())
        for _ in range(1 if args.serial else args.count):
            serial = args.serial or random_serial(tpl["serial_format"], rng)
            text = dict(kv.split("=", 1) for kv in args.set)
            made.append(write_plate(tpl_name, serial, "custom" if args.serial else "random", text, args.name, rng))
    print("created:", " ".join(made))


if __name__ == "__main__":
    main()
