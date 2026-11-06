"""Build everything per state into output/states/<state>/.

  output/states/<state>/<state>-vanity.jpg          preview: the real 1954 example, your own plates and the vanity serials
  output/states/<state>/<state>-random.jpg          preview: random serials in the state's format
  output/states/<state>/stl/<state>-<series>-<serial>.stl     every plate (blank + raised text)
  output/OrcaSlicer/<State>-OrcaSlicer.3mf                    every plate for Bambu Studio / OrcaSlicer (P1S, AMS), several plates
  output/PrusaPrinter/<State>-PrusaSlicer.3mf                 the same for PrusaSlicer 2.9 (MK4S MMU3), several beds
  output/states/<state>/plates.json                          what is in the folder

Serials come from vanity_plates.json and random_plates.json (make them with src/vanity.py),
plus the template's own example and personal plates listed in custom_plates.json under "personal".

Both 3MF projects use two filaments, the state's background colour (1) and ink colour (2): every
plate starts on 1 and a filament change to 2 is set at the first layer above the face (z 3.7), so
the rim and text print in the ink colour (automatic with an AMS / MMU3).
Settings come from slicer_refs/: Martin's own Bambu Lab P1S project (0.2 nozzle, 0.1 mm layers) and
the Original Prusa MK4S MMU3 0.10 mm profile (0.2 first layer).

  python src/build_states.py                    all states
  python src/build_states.py --states iowa utah
  python src/build_states.py --skip-stl --skip-3mf   previews only
"""
import argparse
import io
import json
import math
import random
import re
import sys
import zipfile
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
import trimesh
from shapely import affinity
from shapely.ops import unary_union
from svgelements import SVG, Path as SvgPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plate_engine import ROOT, build_svg  # noqa: E402
from make_stl import path_geometry, extrude  # noqa: E402
from vanity import preview, sheet  # noqa: E402

BLANK = json.loads((ROOT / "blanks" / "Licence_Plate.json").read_text())
SPACING = 4.0                                                 # mm between plates on the bed
BED_MARGIN = 6.0
REFS = ROOT / "slicer_refs"
ORCA_SETTINGS = REFS / "orca_p1s_0.2_project_settings.json"   # Martin's own P1S project (0.2 nozzle, 0.1 layers, AMS)
PRUSA_TEMPLATE = REFS / "prusa_mk4s_mmu3_0.10.ini"            # Original Prusa MK4S MMU3, 0.10 mm, Prusament PLA
ORCA_BED = (256.0, 256.0)
ORCA_AREA = (BED_MARGIN, BED_MARGIN, 256.0 - BED_MARGIN, 226.0)     # back kept free for the prime tower
PRUSA_BED = (250.0, 210.0)
PRUSA_AREA = (BED_MARGIN, BED_MARGIN, 250.0 - BED_MARGIN, 158.0)    # back kept free for the wipe tower
PRUSA_WIPE_TOWER = (15.0, 165.0)

_blank_mesh = None


def blank_mesh():
    global _blank_mesh
    if _blank_mesh is None:
        m = trimesh.load(ROOT / BLANK["stl"])
        m.merge_vertices()
        _blank_mesh = m
    return _blank_mesh


def slug(serial):
    return re.sub(r"[^A-Za-z0-9]+", "", serial).lower()


# ---------------------------------------------------------------- plate list

def plate_list(name, tpl):
    vanity = json.loads((ROOT / "vanity_plates.json").read_text()).get(name, [])
    randoms = json.loads((ROOT / "random_plates.json").read_text()).get(name, [])
    custom = json.loads((ROOT / "custom_plates.json").read_text())
    personal = custom.get("personal", {}).get(name, [])
    rng = random.Random(name)
    out, seen = [], set()
    for series, serials in (("sample", [tpl["serial_example"]]), ("custom", personal),
                            ("vanity", vanity), ("random", randoms)):
        for s in serials:
            if s in seen:
                continue
            seen.add(s)
            p = {"series": series, "serial": s, "file": f"{name}-{series}-{slug(s)}"}
            if "counties" in tpl:
                p["county"] = tpl["serial_example"] == s and "JEFFERSON" or rng.choice(tpl["counties"])
            out.append(p)
    return out


def plate_svg(name, tpl, p):
    plate = {"name": p["file"], "template": name, "serial": p["serial"]}
    if "county" in p:
        plate["text"] = {"county": p["county"]}
    return build_svg(plate, tpl, BLANK)


# ---------------------------------------------------------------- mesh

def plate_mesh(svg_text):
    """Blank + raised text, centred on the origin in X/Y, standing on z = 0."""
    tmp = io.StringIO(svg_text)
    doc = SVG.parse(tmp, ppi=25.4)
    shapes = []
    for el in doc.elements():
        if isinstance(el, SvgPath) and "relief" in (el.values.get("class") or ""):
            g = path_geometry(el, samples_per_curve=10)
            if el.values.get("stroke") not in (None, "none"):
                g = g.buffer(float(el.values.get("stroke-width", 0)) / 2, join_style="round", quad_segs=3)
            shapes.append(g)
    text2d = unary_union(shapes).simplify(0.01)
    M = BLANK["rim_margin"]
    text2d = affinity.scale(text2d, 1, -1, origin=(0, 0))
    text2d = affinity.translate(text2d, BLANK["face_x0"] - M, BLANK["face_y_top"] + M)
    text = extrude(text2d, BLANK["face_z"] - BLANK["embed"], BLANK["text_top_z"])
    mesh = trimesh.util.concatenate([blank_mesh(), text])
    lo, hi = mesh.bounds
    mesh.apply_translation((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]))
    return mesh


def work_plate(args):
    """Worker: build one plate's mesh and STL, return arrays for the 3MF."""
    name, p, stl_dir = args
    tpl = json.loads((ROOT / "templates" / f"{name}.json").read_text())
    mesh = plate_mesh(plate_svg(name, tpl, p))
    if stl_dir:
        mesh.export(Path(stl_dir) / f"{p['file']}.stl")
    return p["file"], np.asarray(mesh.vertices, dtype=np.float32), np.asarray(mesh.faces, dtype=np.int32)


# ---------------------------------------------------------------- layout

def grid(n, area, w, h):
    """Centres for n plates in an area (x0, y0, x1, y1), filled from the front row; several beds if needed."""
    x0a, y0a, x1a, y1a = area
    cols = int((x1a - x0a + SPACING) // (w + SPACING))
    rows = int((y1a - y0a + SPACING) // (h + SPACING))
    per_bed = cols * rows
    used_w = cols * (w + SPACING) - SPACING
    x0 = x0a + (x1a - x0a - used_w) / 2 + w / 2
    y0 = y0a + h / 2
    pos = []
    for i in range(n):
        k = i % per_bed
        pos.append((i // per_bed, x0 + (k % cols) * (w + SPACING), y0 + (k // cols) * (h + SPACING)))
    return pos, per_bed


def change_z(layer, first):
    """Height of the first text layer, checking that the face (z 3.7) ends exactly on a layer."""
    n = (BLANK["face_z"] - first) / layer
    if abs(n - round(n)) > 1e-6:
        raise ValueError(f"layers {first}+{layer}*n don't end at the face z {BLANK['face_z']}")
    return round(BLANK["face_z"] + layer, 3)


def mesh_xml(oid, verts, faces, uuid=""):
    v = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in verts)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
    return f'  <object id="{oid}"{uuid} type="model"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>\n'


# ---------------------------------------------------------------- PrusaSlicer (2.9, multiple beds)

def prusa_settings():
    txt = PRUSA_TEMPLATE.read_text()
    layer = float(re.search(r"^; layer_height = (.*)$", txt, re.M).group(1))
    first = float(re.search(r"^; first_layer_height = (.*)$", txt, re.M).group(1))
    return txt, layer, first


def prusa_config(tpl):
    txt, _, _ = prusa_settings()
    bg, ink = tpl["colors"]["background"], tpl["colors"]["ink"]
    out = []
    for line in txt.splitlines(keepends=True):
        if line.startswith("; filament_colour = ") or line.startswith("; extruder_colour = "):
            n = len(line.split("=", 1)[1].split(";"))
            cols = ([bg, ink] + ["#808080"] * n)[:n]
            line = line.split("=")[0] + "= " + ";".join(cols) + "\n"
        out.append(line)
    txt = "".join(out)
    for k, v in (("wipe_tower_x", PRUSA_WIPE_TOWER[0]), ("wipe_tower_y", PRUSA_WIPE_TOWER[1]), ("wipe_tower_rotation_angle", 0)):
        txt, n = re.subn(rf"^; {k} = .*$", f"; {k} = {v:g}", txt, flags=re.M)
        if n == 0:
            txt += f"; {k} = {v:g}\n"
    return "; generated by PrusaSlicer 2.9.3 (build_states.py)\n\n" + txt


def prusa_bed_translation(i, bed=PRUSA_BED):
    """PrusaSlicer 2.9 multiple beds: bed i sits on a grid (MultipleBeds::get_bed_translation)."""
    if i == 0:
        return 0.0, 0.0
    idx = i + 1
    a = 1
    while (a + 1) * (a + 1) < idx:
        a += 1
    idx -= a * a
    x, y = a, a
    if idx <= a:
        y = idx - 1
    else:
        x = idx - a - 1
    gap = min(100.0, math.hypot(*bed) * 0.3)
    return x * (bed[0] + gap), y * (bed[1] + gap)


def write_prusa(path, title, tpl, items, n_beds):
    """items: [(name, verts, faces, bed, x, y)]. One project, one PrusaSlicer bed per group of plates.
    Every plate starts on filament 1 (background); a tool change to filament 2 (ink) at the first text layer."""
    _, layer, first = prusa_settings()
    z = change_z(layer, first)
    ink = tpl["colors"]["ink"]
    res, build, cfg = [], [], []
    for i, (name, v, f, bed, x, y) in enumerate(items, 1):
        tx, ty = prusa_bed_translation(bed)
        res.append(mesh_xml(i, v, f).replace(f'<object id="{i}"', f'<object id="{i}" name="{escape(name)}"', 1))
        build.append(f'<item objectid="{i}" transform="1 0 0 0 1 0 0 0 1 {x + tx:.4f} {y + ty:.4f} 0" printable="1"/>')
        cfg.append(f' <object id="{i}" instances_count="1">\n  <metadata type="object" key="name" value="{escape(name)}"/>\n'
                   '  <metadata type="object" key="extruder" value="1"/>\n'
                   f'  <volume firstid="0" lastid="{len(f) - 1}">\n   <metadata type="volume" key="name" value="{escape(name)}"/>\n'
                   '   <metadata type="volume" key="volume_type" value="ModelPart"/>\n  </volume>\n </object>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06">\n'
             f'<metadata name="slic3rpe:Version3mf">1</metadata>\n<metadata name="Title">{escape(title)}</metadata>\n'
             f'<resources>\n{"".join(res)}</resources>\n<build>{"".join(build)}</build>\n</model>\n')
    code = f'<code print_z="{z}" type="2" extruder="2" color="{ink}" extra="" gcode="tool_change"/>\n'
    gcode = ('<?xml version="1.0" encoding="utf-8"?>\n' +
             "".join(f'<custom_gcodes_per_print_z bed_idx="{b}">\n{code}<mode value="MultiAsSingle"/>\n</custom_gcodes_per_print_z>\n'
                     for b in range(n_beds)))
    ctypes = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("[Content_Types].xml", ctypes)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("3D/3dmodel.model", model)
        zf.writestr("Metadata/Slic3r_PE_model.config", '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(cfg) + "\n</config>\n")
        zf.writestr("Metadata/Slic3r_PE.config", prusa_config(tpl))
        zf.writestr("Metadata/Prusa_Slicer_custom_gcode_per_print_z.xml", gcode)


# ---------------------------------------------------------------- Bambu Studio / OrcaSlicer

def orca_settings():
    ps = json.loads(ORCA_SETTINGS.read_text())
    return ps, float(ps["layer_height"]), float(ps["initial_layer_print_height"])


def write_orca(path, title, tpl, items, n_plates):
    """items: [(name, verts, faces, plate, x, y)] with x, y on that plate.
    Laid out like a project saved by Bambu Studio / OrcaSlicer: one 3D/Objects/*.model per plate, the
    printer, process and filament settings from Martin's own P1S project, two filaments (background,
    ink) and a filament change to the ink at the first text layer on every plate (automatic with an AMS)."""
    ps, layer, first = orca_settings()
    z = change_z(layer, first)
    bg, ink = tpl["colors"]["background"], tpl["colors"]["ink"]
    ps["filament_colour"] = [bg, ink]
    if "filament_multi_colour" in ps:
        ps["filament_multi_colour"] = [bg, ink]
    for key in ("wipe_tower_x", "wipe_tower_y"):          # per plate
        if isinstance(ps.get(key), list) and ps[key]:
            ps[key] = [ps[key][0]] * n_plates
    ns = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
          'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
          'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"')
    ncols = math.ceil(math.sqrt(n_plates))
    stride = ORCA_BED[0] * 1.2
    files, main_objs, build, cfg, asm = {}, [], [], [], []
    inst = {p: [] for p in range(n_plates)}
    sub = 1
    for k, (name, v, f, plate, x, y) in enumerate(items, 1):
        fname = f"/3D/Objects/{slug(name)}_{k}.model"
        h = float(v[:, 2].max())
        vc = v - np.array([0, 0, h / 2], dtype=np.float32)
        files[fname] = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {ns}>\n'
                        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n'
                        + mesh_xml(sub, vc, f, f' p:UUID="{k:08x}-81cb-4c03-9d28-80fed5dfa1dc"') +
                        ' </resources>\n <build/>\n</model>\n')
        oid = sub + 1
        main_objs.append(f'  <object id="{oid}" p:UUID="{k:08x}-61cb-4c03-9d28-80fed5dfa1dc" type="model">\n   <components>\n'
                         f'    <component p:path="{fname}" objectid="{sub}" p:UUID="{k:08x}-b206-40ff-9872-83e8017abed1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n'
                         '   </components>\n  </object>')
        gx = x + (plate % ncols) * stride
        gy = y - (plate // ncols) * stride
        tr = f"1 0 0 0 1 0 0 0 1 {gx:.4f} {gy:.4f} {h / 2:.4f}"
        build.append(f'  <item objectid="{oid}" p:UUID="{oid:08x}-b1ec-4553-aec9-835e5b724bb4" transform="{tr}" printable="1"/>')
        cfg.append(f'  <object id="{oid}">\n    <metadata key="name" value="{escape(name)}"/>\n    <metadata key="extruder" value="1"/>\n'
                   f'    <part id="{sub}" subtype="normal_part">\n      <metadata key="name" value="{escape(name)}"/>\n'
                   '      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                   '      <mesh_stat edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n'
                   '    </part>\n  </object>')
        inst[plate].append(f'    <model_instance>\n      <metadata key="object_id" value="{oid}"/>\n      <metadata key="instance_id" value="0"/>\n'
                           f'      <metadata key="identify_id" value="{100 + k}"/>\n    </model_instance>')
        asm.append(f'   <assemble_item object_id="{oid}" instance_id="0" transform="{tr}" offset="0 0 0" />')
        sub += 2
    root = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {ns}>\n'
            ' <metadata name="Application">BambuStudio-2.3.2</metadata>\n <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
            f' <metadata name="Title">{escape(title)}</metadata>\n <resources>\n' + "\n".join(main_objs) +
            '\n </resources>\n <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">\n' + "\n".join(build) + '\n </build>\n</model>\n')
    plates_xml = "".join(
        f'  <plate>\n    <metadata key="plater_id" value="{p + 1}"/>\n    <metadata key="plater_name" value="{escape(tpl["state"])} {p + 1}"/>\n'
        '    <metadata key="locked" value="false"/>\n    <metadata key="filament_map_mode" value="Auto For Flush"/>\n'
        '    <metadata key="filament_maps" value="1 1"/>\n' + "\n".join(inst[p]) + '\n  </plate>\n' for p in range(n_plates))
    conf = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(cfg) + "\n" + plates_xml +
            '  <assemble>\n' + "\n".join(asm) + '\n  </assemble>\n</config>\n')
    ctypes = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
              ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
              ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
              ' <Default Extension="png" ContentType="image/png"/>\n <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>')
    mrels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
             + "".join(f' <Relationship Target="{p}" Id="rel-{i}" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
                       for i, p in enumerate(files, start=1)) + '</Relationships>')
    slice_info = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <header>\n    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
                  '    <header_item key="X-BBL-Client-Version" value=""/>\n  </header>\n</config>\n')
    body = f'<layer top_z="{z}" type="2" extruder="2" color="{ink}" extra="" gcode="tool_change"/>\n<mode value="MultiAsSingle"/>\n'
    gcode = ('<?xml version="1.0" encoding="utf-8"?>\n<custom_gcodes_per_layer>\n' +
             "".join(f'<plate>\n<plate_info id="{p + 1}"/>\n{body}</plate>\n' for p in range(n_plates)) + '</custom_gcodes_per_layer>\n')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("[Content_Types].xml", ctypes)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("3D/3dmodel.model", root)
        zf.writestr("3D/_rels/3dmodel.model.rels", mrels)
        for p, txt in files.items():
            zf.writestr(p.lstrip("/"), txt)
        zf.writestr("Metadata/model_settings.config", conf)
        zf.writestr("Metadata/project_settings.config", json.dumps(ps, indent=4))
        zf.writestr("Metadata/slice_info.config", slice_info)
        zf.writestr("Metadata/custom_gcode_per_layer.xml", gcode)


# ---------------------------------------------------------------- main

def build_state(name, args, pool):
    tpl = json.loads((ROOT / "templates" / f"{name}.json").read_text())
    out = ROOT / "output" / "states" / name
    out.mkdir(parents=True, exist_ok=True)
    plates = plate_list(name, tpl)
    (out / "plates.json").write_text(json.dumps(plates, indent=1) + "\n")

    if not args.skip_previews:
        bg, ink = tpl["colors"]["background"], tpl["colors"]["ink"]
        for kind, series in (("vanity", ("sample", "custom", "vanity")), ("random", ("random",))):
            chosen = [p for p in plates if p["series"] in series]
            if not chosen:
                continue
            items = [(p["serial"] if p["series"] in ("vanity", "random") else f'{p["serial"]}  ({p["series"]})',
                      preview(plate_svg(name, tpl, p), bg, ink, width=300)) for p in chosen]
            sheet(items, f"{tpl['state']} {tpl['year']} - {kind} ({len(chosen)})", out / f"{name}-{kind}.jpg")

    if args.skip_stl and args.skip_3mf:
        return f"{name}: {len(plates)} plates, previews only"
    stl_dir = out / "stl"
    if not args.skip_stl:
        stl_dir.mkdir(exist_ok=True)
    jobs = [(name, p, None if args.skip_stl else str(stl_dir)) for p in plates]
    meshes = list(pool.map(work_plate, jobs, chunksize=4))

    if not args.skip_3mf:
        d_orca, d_prusa = ROOT / "output" / "OrcaSlicer", ROOT / "output" / "PrusaPrinter"
        d_orca.mkdir(parents=True, exist_ok=True)
        d_prusa.mkdir(parents=True, exist_ok=True)
        w = float(max(m[1][:, 0].max() - m[1][:, 0].min() for m in meshes))
        h = float(max(m[1][:, 1].max() - m[1][:, 1].min() for m in meshes))
        pos, per_bed = grid(len(meshes), PRUSA_AREA, w, h)
        beds = pos[-1][0] + 1
        write_prusa(d_prusa / f"{name.title()}-PrusaSlicer.3mf", f"{tpl['state']} {tpl['year']} plates", tpl,
                    [(m[0], m[1], m[2], bed, x, y) for m, (bed, x, y) in zip(meshes, pos)], beds)
        pos, per_plate = grid(len(meshes), ORCA_AREA, w, h)
        n_plates = pos[-1][0] + 1
        write_orca(d_orca / f"{name.title()}-OrcaSlicer.3mf", f"{tpl['state']} {tpl['year']} plates", tpl,
                   [(m[0], m[1], m[2], plate, x, y) for m, (plate, x, y) in zip(meshes, pos)], n_plates)
        return f"{name}: {len(plates)} plates, Prusa {beds} beds x {per_bed}, Bambu/Orca {n_plates} plates x {per_plate}"
    return f"{name}: {len(plates)} plates"


def zip_state(name):
    """Pack output/states/<name>/ into output/states/<Name>.zip (entries under <name>/).

    new-york -> New-York.zip
    """
    src = ROOT / "output" / "states" / name
    dst = src.parent / f"{'-'.join(w.capitalize() for w in name.split('-'))}.zip"
    tmp = dst.with_suffix(".zip.tmp")
    files = sorted(p for p in src.rglob("*") if p.is_file() and p.name != ".DS_Store")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in files:
            zf.write(p, Path(name) / p.relative_to(src))
    tmp.replace(dst)
    return f"{name}: zipped {len(files)} files -> {dst.relative_to(ROOT)} ({dst.stat().st_size / 1e6:.1f} MB)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", nargs="*")
    ap.add_argument("--skip-stl", action="store_true")
    ap.add_argument("--skip-3mf", action="store_true")
    ap.add_argument("--skip-previews", action="store_true")
    ap.add_argument("--skip-zip", action="store_true", help="don't pack output/states/<state>.zip")
    ap.add_argument("--zip-only", action="store_true", help="only re-zip existing state folders")
    ap.add_argument("--jobs", type=int, default=None)
    args = ap.parse_args()
    names = args.states or sorted(p.stem for p in (ROOT / "templates").glob("*.json"))
    if args.zip_only:
        for name in names:
            if (ROOT / "output" / "states" / name).is_dir():
                print(zip_state(name), flush=True)
        return
    with ProcessPoolExecutor(args.jobs) as pool:
        for name in names:
            print(build_state(name, args, pool), flush=True)
            if not args.skip_zip:
                print(zip_state(name), flush=True)


if __name__ == "__main__":
    main()
