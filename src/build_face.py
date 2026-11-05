"""Render a plate config to output/<name>/face.svg (millimetres, text as outlines).

Usage: python src/build_face.py plates/hornet.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plate_engine import ROOT, build_svg, load_plate


def main():
    plate, template = load_plate(sys.argv[1])
    blank = json.loads((ROOT / plate.get("blank", "blanks/Licence_Plate.json")).read_text())
    out_dir = ROOT / "output" / plate["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "face.svg").write_text(build_svg(plate, template, blank))
    print(f"{plate['name']}: {template['state']} {template['year']} template, serial {plate.get('serial') or template['serial_example']}")


if __name__ == "__main__":
    main()
