"""Turn output/<name>/face.svg into raised text on the blank STL.

- Text and dash are raised from the face (blank.face_z) up to relief.text_top_z,
  and start relief.embed mm below the face so they bond with it.
- The blank mesh is not closed, so no boolean union is done: the text bodies are added
  to the same STL and the slicer merges overlapping parts of one object.

Writes:
  output/<name>/plate.stl       blank + raised text
  output/<name>/text_only.stl   just the raised text (same position) for a second colour
  output/<name>/topview.png     top-down render of plate.stl, to check placement

Usage: python src/make_stl.py plates/hornet.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import shapely
import trimesh
from PIL import Image, ImageDraw
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union
from svgelements import SVG, Close, Move, Path as SvgPath

ROOT = Path(__file__).resolve().parent.parent


def path_geometry(el, samples_per_curve=24):
    """SVG path -> shapely geometry (even-odd fill)."""
    rings, cur = [], []
    for seg in el.segments(transformed=True):
        if isinstance(seg, Move):
            if len(cur) > 2:
                rings.append(cur)
            cur = [(seg.end.x, seg.end.y)]
            continue
        if isinstance(seg, Close):
            if len(cur) > 2:
                rings.append(cur)
            cur = []
            continue
        n = 1 if seg.__class__.__name__ == "Line" else samples_per_curve
        for t in np.linspace(0, 1, n + 1)[1:]:
            p = seg.point(t)
            cur.append((p.x, p.y))
    if len(cur) > 2:
        rings.append(cur)
    geom = Polygon()
    for r in rings:
        geom = geom.symmetric_difference(Polygon(r).buffer(0))
    return geom


def clean(geom):
    """Snap to a 1 micron grid and drop slivers so every extruded body is a closed solid."""
    geom = shapely.set_precision(geom.buffer(0), 0.001)
    geom = geom.simplify(0.002).buffer(0)
    # open up single-point contacts (pinches) that would make non-manifold vertices
    geom = geom.buffer(-0.003, join_style="mitre").buffer(0.002, join_style="mitre")
    parts = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    kept = []
    for g in parts:
        if g.is_empty or g.area < 1e-3:
            continue
        holes = [h for h in g.interiors if Polygon(h).area > 1e-3]
        kept.append(Polygon(g.exterior, holes).buffer(0))
    return unary_union(kept)


def extrude(geom, z0, z1):
    geom = clean(geom)
    parts = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    meshes = []
    for g in parts:
        if g.is_empty or g.area < 1e-4:
            continue
        m = trimesh.creation.extrude_polygon(g, z1 - z0)
        m.apply_translation((0, 0, z0))
        meshes.append(m)
    return trimesh.util.concatenate(meshes)


def top_view(mesh, face_z, text_z, out_png, background="#D7D4CD", ink="#1E1E1E", scale=36):
    (x0, y0, _), (x1, y1, _) = mesh.bounds
    img = Image.new("RGB", (int((x1 - x0) * scale) + 2, int((y1 - y0) * scale) + 2), "white")
    d = ImageDraw.Draw(img)
    v, f, nz = mesh.vertices, mesh.faces, mesh.face_normals[:, 2]
    for i in np.argsort(v[f].mean(axis=1)[:, 2]):
        if nz[i] < 0.9:
            continue
        z = v[f[i]][:, 2].mean()
        colour = ink if z > text_z - 0.05 else background if z > face_z - 0.1 else "#A0A0A0"
        d.polygon([((q[0] - x0) * scale, (y1 - q[1]) * scale) for q in v[f[i]]], fill=colour)
    img.save(out_png)


def main():
    plate = json.loads(Path(sys.argv[1]).read_text())
    template = json.loads((ROOT / "templates" / f"{plate['template']}.json").read_text())
    blank = json.loads((ROOT / plate.get("blank", "blanks/Licence_Plate.json")).read_text())
    out_dir = ROOT / "output" / plate["name"]
    M = blank["rim_margin"]

    # 1 user unit = 1 mm; svgelements moves the viewBox origin (-M, -M) to (0, 0)
    svg = SVG.parse(str(out_dir / "face.svg"), ppi=25.4)
    shapes = []
    for el in svg.elements():
        if isinstance(el, SvgPath) and "relief" in (el.values.get("class") or ""):
            g = path_geometry(el)
            stroke = float(el.values.get("stroke-width", 0) or 0) if el.values.get("stroke") not in (None, "none") else 0
            if stroke > 0.001:
                g = g.buffer(stroke / 2, join_style="round", quad_segs=8)
            shapes.append(g)
    text2d = unary_union(shapes)

    # SVG (y down, origin at face corner) -> blank coordinates (y up)
    text2d = affinity.scale(text2d, 1, -1, origin=(0, 0))
    text2d = affinity.translate(text2d, blank["face_x0"] - M, blank["face_y_top"] + M)

    face_z, top_z = blank["face_z"], blank["text_top_z"]
    text_mesh = extrude(text2d, face_z - blank["embed"], top_z)

    base = trimesh.load(ROOT / blank["stl"])
    plate_mesh = trimesh.util.concatenate([base, text_mesh])
    plate_mesh.export(out_dir / "plate.stl")
    extrude(text2d, face_z, top_z).export(out_dir / "text_only.stl")
    top_view(plate_mesh, face_z, top_z, out_dir / "topview.png", **template["colors"])
    print(f"{plate['name']}: plate.stl, text_only.stl, topview.png")


if __name__ == "__main__":
    main()
