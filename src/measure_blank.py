"""Measure a plate blank STL and print the "blank" section for a config.

Expects a blank with a flat face and a thin raised rim around it (like blanks/Licence_Plate.stl).
The output is the blank's JSON file that plates point to with "blank".
Finds the face level, the rim top level and the rim's inner edge, i.e. the area the
design is laid out in.

Usage: python src/measure_blank.py blanks/Licence_Plate.stl > blanks/Licence_Plate.json
"""
import json
import sys
from collections import defaultdict

import numpy as np
import trimesh
from shapely.geometry import Polygon
from shapely.ops import unary_union


def main():
    path = sys.argv[1]
    mesh = trimesh.load(path)
    tris = mesh.triangles
    up = mesh.face_normals[:, 2] > 0.99

    # Up-facing area per height level
    levels = defaultdict(float)
    for t, a in zip(tris[up], mesh.area_faces[up]):
        levels[round(t[:, 2].mean(), 2)] += a
    top = max(levels)
    face = max((z for z in levels if z < top), key=lambda z: levels[z])

    def region(z):
        sel = tris[up & (np.abs(tris[:, :, 2].mean(axis=1) - z) < 0.02)]
        return unary_union([Polygon(t[:, :2]).buffer(1e-4) for t in sel])

    face_poly = region(face)
    rim = region(top)
    rim = max(getattr(rim, "geoms", [rim]), key=lambda g: g.area)
    if not rim.interiors:
        sys.exit("No raised rim with an opening found; set the blank values by hand.")
    inner = Polygon(rim.interiors[0])
    fx0, fy0, fx1, fy1 = face_poly.bounds
    rx0, ry0, rx1, ry1 = rim.exterior.bounds
    ix0, iy0, ix1, iy1 = inner.bounds

    print(json.dumps({
        "stl": path,
        "face_x0": round(ix0, 3),
        "face_y_top": round(iy1, 3),
        "face_width": round(ix1 - ix0, 3),
        "face_height": round(iy1 - iy0, 3),
        "face_z": face,
        "rim_margin": round(ix0 - fx0, 3),
        "rim_outer": round(rx0 - fx0, 3),
        "text_top_z": top,     # raised text ends level with the rim
        "embed": 0.1,          # text bodies start this far below the face
    }, indent=2))


if __name__ == "__main__":
    main()
