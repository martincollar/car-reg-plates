"""Layout engine for state plate templates.

A *template* (templates/<state>.json) describes one state's real plate design: colours,
and a list of elements placed on the face (the area inside the blank's raised rim).
A *plate* (plates/<name>.json) picks a template, sets the serial and may override any
element's text by id.

Coordinates in templates are fractions of the face: x of the width, y of the height,
measured from the top-left corner. Text sizes (`cap`) are cap heights as a fraction of
the face height.

Element types
  text    {"id", "text", "font", "cap", "baseline", "x", "anchor": start|middle|end,
           "width" (spread letters to this width; with "fit": "scale" stretch them instead; "fit": "max" only limits the width), "track" (em), "sx", "skew" (deg), "stem"}
  serial  {"font", "cap", "baseline", "x0", "x1", "sep": dot|rdot|dash|cross|none,
           "track", "skew", "stem", "min_sx", "max_sx"}
          The plate's serial string uses "-" for the state's separator and " " for a gap.
          A prefix written "1/A " is stacked (1 over A) in a column left of the serial, as on
          Idaho and Utah plates; place it with "stack": {"x", "cap", "baselines": [top, bottom],
          "font", "sx", "stem"} and give "x0_plain" for where the serial starts without one.
  box     {"x0", "y0", "x1", "y1", "stroke" (mm), "radius" (mm)}   raised outline (year tabs)
  shape   {"shape": "alaska_flag" | "pa_border" | "mt_border", ...} simplified state artwork

Every raised element is written as an SVG path with class="relief"; make_stl.py extrudes them.
"""
import json
import math
import re
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from shapely.geometry import Polygon

ROOT = Path(__file__).resolve().parent.parent

_fonts = {}


class Font:
    def __init__(self, name):
        self.f = TTFont(ROOT / "fonts" / name)
        self.gs = self.f.getGlyphSet()
        self.cmap = self.f.getBestCmap()
        self.upm = self.f["head"].unitsPerEm
        self.cap = self.bounds("H")[3]
        self.space = self.gs[self.glyph(" ")].width if ord(" ") in self.cmap else self.upm * 0.3

    @classmethod
    def get(cls, name):
        if name not in _fonts:
            _fonts[name] = cls(name)
        return _fonts[name]

    def glyph(self, ch):
        g = self.cmap.get(ord(ch))
        if g is None:
            raise ValueError(f"character {ch!r} missing in font")
        return g

    def bounds(self, ch):
        bp = BoundsPen(self.gs)
        self.gs[self.glyph(ch)].draw(bp)
        return bp.bounds

    def stem(self):
        b = self.bounds("I")
        w = b[2] - b[0]
        if ord("l") in self.cmap:  # a serifed I (Advent Pro) is much wider than its stem: use l instead
            bl = self.bounds("l")
            w = min(w, bl[2] - bl[0]) if w > 1.3 * (bl[2] - bl[0]) else w
        return w / self.cap


def run_layout(font, text, track_units):
    """Glyph origins and ink extents (font units). Spaces advance without ink."""
    pos, x, xmin, xmax = [], 0.0, None, None
    for ch in text:
        if ch == " ":
            x += font.space + track_units
            continue
        g = font.glyph(ch)
        bp = BoundsPen(font.gs)
        font.gs[g].draw(bp)
        if bp.bounds:
            a, b = x + bp.bounds[0], x + bp.bounds[2]
            xmin = a if xmin is None else min(xmin, a)
            xmax = b if xmax is None else max(xmax, b)
        pos.append((g, x))
        x += font.gs[g].width + track_units
    return pos, xmin or 0.0, xmax or 0.0


def draw_run(font, text, cap_mm, baseline, x_left, sx, track_units, skew_deg=0.0):
    """Path data for text whose ink starts at x_left. Returns (d, ink_width)."""
    s = cap_mm / font.cap
    pos, xmin, xmax = run_layout(font, text, track_units)
    shear = math.tan(math.radians(skew_deg)) * s
    pen = SVGPathPen(font.gs)
    for g, gx in pos:
        font.gs[g].draw(TransformPen(pen, (sx * s, 0, shear, -s, x_left + (gx - xmin) * sx * s, baseline)))
    return pen.getCommands(), (xmax - xmin) * sx * s


def ink_width(font, text, cap_mm, sx, track_units):
    s = cap_mm / font.cap
    _, xmin, xmax = run_layout(font, text, track_units)
    return (xmax - xmin) * sx * s


def emboldening(font, cap_mm, stem):
    """Outline stroke (mm) that brings the font's stem up to `stem` x cap height."""
    if not stem:
        return 0.0
    return max(0.0, (stem - font.stem()) * cap_mm)


def rrect(x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    return (f"M{x+r:.3f},{y:.3f}H{x+w-r:.3f}A{r:.3f},{r:.3f} 0 0 1 {x+w:.3f},{y+r:.3f}"
            f"V{y+h-r:.3f}A{r:.3f},{r:.3f} 0 0 1 {x+w-r:.3f},{y+h:.3f}H{x+r:.3f}"
            f"A{r:.3f},{r:.3f} 0 0 1 {x:.3f},{y+h-r:.3f}V{y+r:.3f}A{r:.3f},{r:.3f} 0 0 1 {x+r:.3f},{y:.3f}Z")


def circle(cx, cy, r):
    return (f"M{cx-r:.3f},{cy:.3f}A{r:.3f},{r:.3f} 0 1 0 {cx+r:.3f},{cy:.3f}"
            f"A{r:.3f},{r:.3f} 0 1 0 {cx-r:.3f},{cy:.3f}Z")


def poly(points):
    return "M" + "L".join(f"{x:.3f},{y:.3f}" for x, y in points) + "Z"


# ---------------------------------------------------------------- separators

def separator(kind, cx, baseline, cap):
    """Path data for a serial separator centred at cx."""
    mid = baseline - 0.48 * cap
    if kind == "dot":
        w = 0.15 * cap
        return rrect(cx - w / 2, mid - w / 2, w, w, w * 0.25)
    if kind == "rdot":
        return circle(cx, mid, 0.085 * cap)
    if kind == "dash":
        w, h = 0.21 * cap, 0.14 * cap
        return rrect(cx - w / 2, mid - h / 2, w, h, h * 0.25)
    if kind == "cross":
        # Michigan: small cross with a dot either side
        arm, t = 0.11 * cap, 0.075 * cap
        d = rrect(cx - t / 2, mid - arm, t, 2 * arm, t * 0.45) + rrect(cx - arm, mid - t / 2, arm * 2, t, t * 0.45)
        r = 0.04 * cap
        d += circle(cx - 0.17 * cap, mid, r) + circle(cx + 0.17 * cap, mid, r)
        return d
    return ""


SEP_WIDTH = {"dot": 0.15, "rdot": 0.17, "dash": 0.21, "cross": 0.38, "none": 0.0}


# ---------------------------------------------------------------- elements

def render_text(el, W, H):
    font = Font.get(el["font"])
    cap = el["cap"] * H
    base = el["baseline"] * H
    track = el.get("track", 0.04) * font.upm
    sx = el.get("sx", 1.0)
    text = el["text"]
    if not text:
        return None
    stroke = emboldening(font, cap, el.get("stem"))
    glyph_cap = cap - stroke
    if "width" in el:
        target = el["width"] * W - stroke
        tight = ink_width(font, text, glyph_cap, sx, track)
        n = max(1, len(text) - 1)
        if el.get("fit") == "scale":
            sx *= target / tight
        elif el.get("fit") == "max" and tight <= target:
            pass  # short text keeps its natural spacing
        elif tight <= target:
            track += (target - tight) / n / (glyph_cap / font.cap * sx)
        else:
            sx *= target / tight
    w = ink_width(font, text, glyph_cap, sx, track) + stroke
    x = el["x"] * W
    anchor = el.get("anchor", "middle")
    left = x if anchor == "start" else x - w if anchor == "end" else x - w / 2
    d, _ = draw_run(font, text, glyph_cap, base - stroke / 2, left + stroke / 2, sx, track, el.get("skew", 0))
    return d, stroke


def split_stack(serial):
    """'1/A 28 588' -> (('1', 'A'), '28 588'); serials without '/' -> (None, serial)."""
    m = re.match(r"^([^ /-]+)/([^ -]+)[ -]?(.*)$", serial)
    if not m:
        return None, serial
    return (m.group(1), m.group(2)), m.group(3)


def render_stack(el, rows, W, H):
    """Small characters stacked in a column (county code / letter prefix)."""
    st = el["stack"]
    font = Font.get(st.get("font", el["font"]))
    cap = st["cap"] * H
    stroke = emboldening(font, cap, st.get("stem", el.get("stem")))
    glyph_cap = cap - stroke
    track = st.get("track", 0.03) * font.upm
    sx = st.get("sx", 1.0)
    widths = [ink_width(font, r, glyph_cap, sx, track) for r in rows]
    col = max(widths)
    d = ""
    for r, w, bl in zip(rows, widths, st["baselines"]):
        left = st["x"] * W + (col - w) / 2
        dd, _ = draw_run(font, r, glyph_cap, bl * H - stroke / 2, left + stroke / 2, sx, track, el.get("skew", 0))
        d += dd
    return d, stroke


def render_serial(el, serial, W, H):
    stack, serial = split_stack(serial)
    if not stack and "x0_plain" in el:
        el = dict(el, x0=el["x0_plain"])
    font = Font.get(el["font"])
    cap = el["cap"] * H
    base = el["baseline"] * H
    track = el.get("track", 0.03) * font.upm
    sep = el.get("sep", "none")
    skew = el.get("skew", 0)
    stroke = emboldening(font, cap, el.get("stem"))
    glyph_cap = cap - stroke

    # Split into glyph groups and the joints between them
    groups, joints, cur = [], [], ""
    for ch in serial:
        if ch in "- ":
            if cur:
                groups.append(cur)
                cur = ""
                joints.append("sep" if ch == "-" else "gap")
        else:
            cur += ch
    if cur:
        groups.append(cur)
    joints = joints[:len(groups) - 1]

    # Long serials: if even the narrowest allowed letters don't fit, shrink the whole serial
    for _ in range(2):
        sep_w = SEP_WIDTH.get(sep, 0) * cap
        sep_pad = el.get("sep_pad", 0.08) * cap
        gap_w = el.get("gap", 0.35) * cap
        joint_w = {"sep": gap_w, "gap": gap_w} if sep == "none" else {"sep": sep_w + 2 * sep_pad, "gap": gap_w}
        fixed = sum(joint_w[j] for j in joints) + stroke * len(groups)
        natural = sum(ink_width(font, g, glyph_cap, 1.0, track) for g in groups)
        avail = (el["x1"] - el["x0"]) * W - math.tan(math.radians(skew)) * cap
        needed = natural * el.get("min_sx", 0.6) + fixed
        if needed <= avail:
            break
        k = avail / needed
        cap, glyph_cap, stroke = cap * k, glyph_cap * k, stroke * k

    sep_w = SEP_WIDTH.get(sep, 0) * cap
    sep_pad = el.get("sep_pad", 0.08) * cap
    gap_w = el.get("gap", 0.35) * cap
    if sep == "none":
        joint_w = {"sep": gap_w, "gap": gap_w}
    else:
        joint_w = {"sep": sep_w + 2 * sep_pad, "gap": gap_w}
    fixed = sum(joint_w[j] for j in joints) + stroke * len(groups)
    natural = sum(ink_width(font, g, glyph_cap, 1.0, track) for g in groups)
    avail = (el["x1"] - el["x0"]) * W - math.tan(math.radians(skew)) * cap  # italic tops lean right
    sx = (avail - fixed) / natural
    sx = max(el.get("min_sx", 0.6), min(el.get("max_sx", 1.25), sx))
    total = natural * sx + fixed
    x = el["x0"] * W + (avail - total) / 2

    d_text, d_sep = "", ""
    for i, g in enumerate(groups):
        d, w = draw_run(font, g, glyph_cap, base - stroke / 2, x + stroke / 2, sx, track, skew)
        d_text += d
        x += w + stroke
        if i < len(joints):
            jw = joint_w[joints[i]]
            if joints[i] == "sep" and sep != "none":
                # separators lean with italic serials
                shift = math.tan(math.radians(skew)) * 0.48 * cap
                d_sep += separator(sep, x + jw / 2 + shift, base, cap)
            x += jw
    stacked = render_stack(el, stack, W, H) if stack and "stack" in el else None
    return d_text, stroke, d_sep, stacked


def render_box(el, W, H):
    x0, y0, x1, y1 = el["x0"] * W, el["y0"] * H, el["x1"] * W, el["y1"] * H
    t, r = el.get("stroke", 0.35), el.get("radius", 0.3)
    return rrect(x0, y0, x1 - x0, y1 - y0, r) + rrect(x0 + t, y0 + t, x1 - x0 - 2 * t, y1 - y0 - 2 * t, max(0.05, r - t))


def render_shape(el, W, H):
    kind = el["shape"]
    if kind == "alaska_flag":
        # Pole with a waving flag; Big Dipper and North Star as small holes
        x, y, h = el["x"] * W, el["y"] * H, el["h"] * H
        pole_w = 0.06 * h
        d = rrect(x, y, pole_w, h, pole_w / 2) + circle(x + pole_w / 2, y, pole_w * 0.9)
        fx0, fy0, fw, fh = x + pole_w * 0.6, y + 0.04 * h, el.get("flag_w", 0.68) * h, el.get("flag_h", 0.46) * h
        top = [(fx0 + fw * t, fy0 + 0.05 * h * math.sin(t * math.pi * 1.6)) for t in [i / 12 for i in range(13)]]
        bot = [(px, py + fh) for px, py in reversed(top)]
        d += poly(top + bot)
        if el.get("stars", True):
            r = el.get("star_r", 0.045) * h
            stars = [(0.14, 0.70), (0.30, 0.74), (0.44, 0.66), (0.56, 0.58), (0.60, 0.40), (0.76, 0.44), (0.74, 0.62), (0.86, 0.18)]
            for sxf, syf in stars:
                d += circle(fx0 + sxf * fw, fy0 + syf * fh, r)
        return d
    if kind == "pa_border":
        # Raised outline of Pennsylvania inside the rim: Erie panhandle top-left, Delaware River right
        inset, t = el.get("inset", 0.02), el.get("stroke", 0.4)

        def outline(off):
            x0, y0 = inset * W + off, inset * H + off
            x1, y1 = (1 - inset) * W - off, (1 - inset) * H - off
            notch_x, notch_y = x0 + 0.06 * W, y0 + 0.07 * H
            pts = [(x0, y0 + 0.07 * H), (notch_x, y0 + 0.07 * H), (notch_x + 0.02 * W, y0), (x1 - 0.06 * W, y0)]
            # wavy river edge down the right side
            for i in range(17):
                tt = i / 16
                yy = y0 + tt * (y1 - y0)
                xx = x1 - 0.06 * W + 0.035 * W * math.sin(tt * math.pi * 3) + 0.03 * W * tt
                pts.append((xx, yy))
            pts += [(x0, y1)]
            return pts

        return poly(outline(0)) + poly(outline(t))
    if kind == "mt_border":
        # Raised outline of Montana: straight north, east and south edges, the Idaho border
        # (Bitterroot Range) wiggling down the left side, traced from the 1955 plate
        t = el.get("stroke", 0.4)
        outer = Polygon([(x * W, y * H) for x, y in MT_OUTLINE]).buffer(-0.3).buffer(0.3)
        inner = outer.buffer(-t, join_style="mitre")
        return poly(outer.exterior.coords[:-1]) + poly(inner.exterior.coords[:-1])
    raise ValueError(f"unknown shape {kind}")


# Montana outline in face fractions, clockwise from the top-left corner
MT_OUTLINE = [
    (0.024, 0.0), (1.0, 0.0), (1.0, 0.900), (0.330, 0.900), (0.322, 0.915), (0.322, 0.964),
    (0.301, 0.968), (0.265, 0.964), (0.230, 0.956), (0.202, 0.940), (0.184, 0.916),
    (0.170, 0.884), (0.156, 0.851), (0.141, 0.827), (0.124, 0.819), (0.103, 0.827),
    (0.081, 0.819), (0.069, 0.787), (0.064, 0.747), (0.065, 0.707), (0.072, 0.675),
    (0.078, 0.643), (0.071, 0.610), (0.057, 0.586), (0.039, 0.554), (0.025, 0.506),
    (0.014, 0.466), (0.004, 0.426), (0.003, 0.378), (0.004, 0.305), (0.004, 0.217),
    (0.009, 0.153), (0.016, 0.080),
]


# ---------------------------------------------------------------- plate

def load_plate(plate_path):
    plate = json.loads(Path(plate_path).read_text())
    template = json.loads((ROOT / "templates" / f"{plate['template']}.json").read_text())
    return plate, template


def build_svg(plate, template, blank):
    W, H = blank["face_width"], blank["face_height"]
    M, RIM_OUT = blank["rim_margin"], blank["rim_outer"]
    bg, ink = template["colors"]["background"], template["colors"]["ink"]
    overrides = plate.get("text", {})
    serial = plate.get("serial") or template["serial_example"]

    parts = []
    for el in template["elements"]:
        el = dict(el)
        if el.get("id") in overrides:
            el["text"] = overrides[el["id"]]
        kind = el["type"]
        if kind == "text":
            r = render_text(el, W, H)
            if r:
                d, stroke = r
                parts.append((d, stroke))
        elif kind == "serial":
            d, stroke, d_sep, stacked = render_serial(el, serial, W, H)
            parts.append((d, stroke))
            if d_sep:
                parts.append((d_sep, 0))
            if stacked:
                parts.append(stacked)
        elif kind == "box":
            parts.append((render_box(el, W, H), 0))
        elif kind == "shape":
            parts.append((render_shape(el, W, H), 0))

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W+2*M:.3f}mm" height="{H+2*M:.3f}mm" '
           f'viewBox="{-M} {-M} {W+2*M:.3f} {H+2*M:.3f}">',
           f'<path id="face" d="{rrect(-M, -M, W+2*M, H+2*M, 1.0)}" fill="{bg}"/>',
           f'<path id="rim" d="{rrect(-M+RIM_OUT, -M+RIM_OUT, W+2*(M-RIM_OUT), H+2*(M-RIM_OUT), 0.7)}'
           f'{rrect(0, 0, W, H, 0.4)}" fill="{ink}" fill-rule="evenodd"/>']
    for d, stroke in parts:
        st = f' stroke="{ink}" stroke-width="{stroke:.3f}" stroke-linejoin="round"' if stroke > 0.001 else ""
        out.append(f'<path class="relief" d="{d}" fill="{ink}" fill-rule="evenodd"{st}/>')
    out.append("</svg>\n")
    return "\n".join(out)
