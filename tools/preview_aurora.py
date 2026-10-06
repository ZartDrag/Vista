#!/usr/bin/env python3
"""Offline preview of watchface.xml with the battery aurora.

Evaluates the aurora Condition and every Arc Transform in watchface.xml for a
given battery percent (same expressions the runtime evaluates), then draws
aurora -> comet -> mountains -> sun -> time/date in document order.
Usage: python3 tools/preview_aurora.py PERCENT OUT.png [--complications]
"""

import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import preview_smooth_tail as base  # noqa: E402

XML = ROOT / "watchface/src/main/res/raw/watchface.xml"
S = base.SCALE
base.COMET_COLOR = (0x00, 0xE5, 0xFF)  # default comet_tail option (cyan)
SIZE = base.SIZE


def argb(token):
    v = token.lstrip("#")
    if len(v) == 6:
        v = "FF" + v
    return int(v[0:2], 16), tuple(int(v[i:i + 2], 16) for i in (2, 4, 6))


def ev(expr, pct, second_ms=0.0):
    e = expr.replace("[BATTERY_PERCENT]", str(pct))
    e = e.replace("[SECOND_MILLISECOND]", str(second_ms))
    e = e.replace("&&", " and ").replace("||", " or ")
    env = dict(clamp=lambda v, lo, hi: max(lo, min(hi, v)), asin=math.asin,
               deg=math.degrees, rad=math.radians, sin=math.sin, cos=math.cos)
    return eval(e, {"__builtins__": {}}, env)


def aurora_parts(pct):
    root = ET.parse(XML).getroot()
    scene = root.find("Scene")
    cond = None
    for c in scene.findall("Condition"):
        if c.find("Expressions/Expression[@name='aurora_low']") is not None:
            cond = c
    exprs = {e.get("name"): e.text for e in cond.find("Expressions")}
    chosen = cond.find("Default")
    for cmp in cond.findall("Compare"):
        if ev(exprs[cmp.get("expression")], pct):
            chosen = cmp
            break
    group = chosen.find("Group")
    return group.get("name"), group.findall("PartDraw")


def gradient_layer(g, ox, oy):
    """RGBA image of a WFF LinearGradient (coords relative to the PartDraw)."""
    dim = SIZE * S
    sx, sy = float(g.get("startX")) + ox, float(g.get("startY")) + oy
    ex, ey = float(g.get("endX")) + ox, float(g.get("endY")) + oy
    cols = [argb(c) for c in g.get("colors").split()]
    pos = [float(v) for v in g.get("positions").split()]
    yy, xx = np.mgrid[0:dim, 0:dim].astype(np.float32) / S
    dx, dy = ex - sx, ey - sy
    t = np.clip(((xx - sx) * dx + (yy - sy) * dy) / (dx * dx + dy * dy), 0, 1)
    out = np.zeros((dim, dim, 4), np.float32)
    for ch in range(4):
        vals = [c[0] if ch == 3 else c[1][ch] for c in cols]
        out[..., ch] = np.interp(t, pos, vals)
    return Image.fromarray(out.round().astype(np.uint8), "RGBA")


def draw_aurora(canvas, pct):
    name, parts = aurora_parts(pct)
    dim = SIZE * S
    grad_cache = {}
    for part in parts:
        oy = float(part.get("y"))
        ox = float(part.get("x"))
        for arc in part.findall("Arc"):
            vals = {k: float(arc.get(k)) for k in ("centerX", "centerY", "width", "startAngle", "endAngle")}
            for tr in arc.findall("Transform"):
                v = ev(tr.get("value"), pct)
                tgt = tr.get("target")
                if tr.get("mode") == "BY":
                    vals[tgt] = vals[tgt] + v
                else:
                    vals[tgt] = v
            st = arc.find("Stroke")
            a, rgb = argb(st.get("color"))
            sweep = vals["endAngle"] - vals["startAngle"]
            assert sweep > 0, sweep
            r = vals["width"] / 2
            if math.radians(sweep) * r < 0.1:
                continue  # 0.02 px sliver of an unreached arc: sub-pixel, PIL cannot draw it
            cx, cy = vals["centerX"] + ox, vals["centerY"] + oy
            # Thick BUTT-capped arc as an exact annular-sector polygon.
            n = max(8, int(sweep / 0.2))
            half = float(st.get("thickness")) / 2
            outer, inner = [], []
            for i in range(n + 1):
                t = math.radians(vals["startAngle"] + sweep * i / n)
                for rr, lst in ((r + half, outer), (r - half, inner)):
                    lst.append(((cx + rr * math.sin(t)) * S, (cy - rr * math.cos(t)) * S))
            mask = Image.new("L", (dim, dim), 0)
            ImageDraw.Draw(mask).polygon(outer + inner[::-1], fill=255)
            g = st.find("LinearGradient")
            if g is not None:
                key = ET.tostring(g)
                if key not in grad_cache:
                    grad_cache[key] = gradient_layer(g, ox, oy)
                layer = grad_cache[key].copy()
                ga = np.asarray(layer.getchannel("A"), np.uint16)
                m = np.asarray(mask, np.uint16)
                layer.putalpha(Image.fromarray((ga * m // 255 * a // 255).astype(np.uint8)))
            else:
                layer = Image.new("RGBA", (dim, dim), rgb + (0,))
                layer.putalpha(mask.point(lambda p, a=a: p * a // 255))
            canvas.alpha_composite(layer)
    return name


def main():
    pct = int(sys.argv[1])
    out = Path(sys.argv[2])
    comps = "--complications" in sys.argv
    dim = SIZE * S
    canvas = Image.new("RGBA", (dim, dim), (0, 0, 0, 255))
    name = draw_aurora(canvas, pct)
    for part in base.parse_comet(XML):
        base.stamp_part(canvas, part)
    face = canvas.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    face.alpha_composite(Image.open(base.MOUNTAINS).convert("RGBA"))
    overlay = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    base.draw_sun(overlay)
    face.alpha_composite(overlay.resize((SIZE, SIZE), Image.Resampling.LANCZOS))
    base.draw_text(face)
    if comps:
        d = ImageDraw.Draw(face)
        f = base.font_at(20, 400)
        for txt, cy in (("72", 60), ("8420", 390)):
            b = d.textbbox((0, 0), txt, font=f)
            d.text((225 - (b[2] - b[0]) / 2 - b[0], cy - (b[3] - b[1]) / 2 - b[1]), txt, font=f, fill=(0xE6, 0xE6, 0xE6, 255))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, SIZE - 1, SIZE - 1], fill=255)
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
    img.paste(face, (0, 0), mask)
    img.convert("RGB").save(out)
    print(out, name)


if __name__ == "__main__":
    main()
