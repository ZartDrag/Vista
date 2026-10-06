#!/usr/bin/env python3
"""Generate the battery aurora block in watchface.xml (WFF v2).

The aurora is a set of wavy ribbons across the sky. Each ribbon is an
"arc spline": a chain of circular Arc elements whose tangents match at every
junction, so the chain reads as one smooth wave. WFF v2 has no path element,
so this is the only way to draw a smooth curve with native primitives.

Battery fill: the ribbon is visible from the left edge (x = 0) to
E = 4.5 * clamp([BATTERY_PERCENT], 0, 100) (450 px = full sky width).
Every Arc keeps its left end fixed and moves its right end with a Transform:
  bump (centre below, drawn CLOCKWISE left->right):
      endAngle   = deg(asin((clamp(E, xL + 0.02, xR) - cx) / r))
  dip  (centre above, drawn CLOCKWISE right->left, i.e. start is the moving end):
      startAngle = 180 - deg(asin((clamp(E, xL + 0.02, xR) - cx) / r))
Arcs left of E are full, the arc containing E is cut exactly at x = E, and
arcs right of E collapse to a 0.02 px sliver (never a zero or negative sweep,
so there is no 0-vs-360 ambiguity).

The aurora is still: no time-driven motion. The only Transforms are the
battery-fill startAngle/endAngle ones above.

Colour: three Condition branches, <25 red, 25..80 blue, >80 green.
Run:  python3 tools/gen_aurora.py   (rewrites the block between the markers)
"""

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XML = ROOT / "watchface/src/main/res/raw/watchface.xml"

SKY_W = 450.0
E_EXPR = "clamp([BATTERY_PERCENT], 0, 100) * 4.5"

# Part box for every ribbon PartDraw (keeps the layer bitmaps small).
PART_Y = 70.0
PART_H = 210.0

COLORS = {"red": "FF3B30", "blue": "3D8BFF", "green": "34C759"}

# Ribbons, back to front. baseline: (y at x=0, y at x=225, y at x=450)
# spacings: horizontal distance between inflection points (half wavelengths)
# phi: tilt of the wave against the baseline at each inflection (degrees)
# layers: (stroke thickness, alpha 0-255), wide/faint glow first, core last
RIBBONS = [
    dict(name="upper", baseline=(176, 128, 132), spacings=[82, 66, 88, 72, 78, 68, 84],
         phi=15, up=False,
         curtain=(14, 30, 0x40),
         layers=[(22, 0x12), (12, 0x22), (5, 0x40), (1.6, 0x80)]),
    dict(name="main", baseline=(222, 186, 158), spacings=[62, 70, 56, 74, 60, 68, 64, 72],
         phi=23, up=True,
         curtain=(20, 42, 0x60),
         layers=[(30, 0x14), (18, 0x26), (9, 0x48), (2.6, 0xB8)]),
    dict(name="lower", baseline=(240, 232, 214), spacings=[54, 62, 50, 66, 56, 60, 52, 64, 58],
         phi=19, up=False,
         curtain=(10, 22, 0x34),
         layers=[(16, 0x10), (8, 0x22), (3, 0x40), (1.2, 0x70)]),
]


def baseline_fn(y0, ym, y1):
    # Quadratic through (0,y0), (225,ym), (450,y1).
    def f(x):
        t = x / SKY_W
        return y0 * (1 - t) * (1 - 2 * t) + ym * 4 * t * (1 - t) + y1 * t * (2 * t - 1)
    return f


def wff_angle(cx, cy, px, py):
    return math.degrees(math.atan2(px - cx, -(py - cy)))


def build_arcs(rib):
    f = baseline_fn(*rib["baseline"])
    xs = [0.0]
    i = 0
    while xs[-1] < SKY_W:
        xs.append(xs[-1] + rib["spacings"][i % len(rib["spacings"])])
        i += 1
    pts = [(x, f(x)) for x in xs]
    c0 = math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0])
    phi = math.radians(rib["phi"])
    h = c0 - phi if rib["up"] else c0 + phi  # y-down: negative heading = going up
    arcs = []
    for (px, py), (qx, qy) in zip(pts, pts[1:]):
        c = math.atan2(qy - py, qx - px)
        d = math.hypot(qx - px, qy - py)
        half = c - h
        r = d / (2 * abs(math.sin(half)))
        s = 1 if half > 0 else -1  # +1 bump (centre below), -1 dip (centre above)
        cx = px + s * r * (-math.sin(h))
        cy = py + s * r * math.cos(h)
        aL = wff_angle(cx, cy, px, py)
        aR = wff_angle(cx, cy, qx, qy)
        if s < 0:
            aL %= 360.0
            aR %= 360.0
            assert 90 < aR < aL < 270, (aL, aR)
        else:
            assert -90 < aL < aR < 90, (aL, aR)
        arcs.append(dict(kind="bump" if s > 0 else "dip", cx=cx, cy=cy, r=r,
                         xL=px, xR=qx, aL=aL, aR=aR))
        h = 2 * c - h
        assert abs(math.degrees(h)) < 70, math.degrees(h)
    return arcs


def fmt(v):
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def arc_xml(a, thickness, color, indent, lift=0.0, gradient=None):
    cy = a["cy"] - PART_Y - lift
    x_expr = f"clamp({E_EXPR}, {fmt(a['xL'] + 0.02)}, {fmt(a['xR'])})"
    asin = f"deg(asin(({x_expr} - {fmt(a['cx'])}) / {fmt(a['r'])}))"
    if a["kind"] == "bump":
        start, end = fmt(a["aL"]), fmt(a["aL"] + 0.01)
        tr = f'<Transform target="endAngle" value="{asin}"/>'
    else:
        start, end = fmt(a["aL"] - 0.01), fmt(a["aL"])
        tr = f'<Transform target="startAngle" value="180 - {asin}"/>'
    p = " " * indent
    head = (f'{p}<Arc centerX="{fmt(a["cx"])}" centerY="{fmt(cy)}" width="{fmt(2 * a["r"])}" '
            f'height="{fmt(2 * a["r"])}" startAngle="{start}" endAngle="{end}" direction="CLOCKWISE">\n')
    if gradient is None:
        stroke = f'{p}  <Stroke color="{color}" thickness="{fmt(thickness)}" cap="BUTT"/>\n'
    else:
        stroke = (f'{p}  <Stroke color="{color}" thickness="{fmt(thickness)}" cap="BUTT">\n'
                  f'{p}    {gradient}\n'
                  f'{p}  </Stroke>\n')
    return head + stroke + f'{p}  {tr}\n' + f'{p}</Arc>\n'


def curtain_gradient(rib, lift, cth, calpha, hexrgb):
    # Gradient axis: perpendicular to the ribbon's end-to-end chord, from the ribbon
    # centre line (opaque end) up to the top edge of the lifted curtain stroke (clear).
    y0, _, y1 = rib["baseline"]
    ang = math.atan2(y1 - y0, SKY_W)
    nx, ny = math.sin(ang), -math.cos(ang)  # unit normal pointing up
    mx, my = SKY_W / 2, (y0 + y1) / 2 - PART_Y
    reach = lift + cth / 2
    sx, sy = mx + nx * reach, my + ny * reach  # top: clear
    return (f'<LinearGradient startX="{fmt(sx)}" startY="{fmt(sy)}" endX="{fmt(mx)}" endY="{fmt(my)}" '
            f'colors="#00{hexrgb} #{calpha // 3:02X}{hexrgb} #{calpha:02X}{hexrgb}" positions="0 0.55 1"/>')


def branch_xml(cname, hexrgb, ribbons, indent):
    p = " " * indent
    out = f'{p}<Group name="aurora_{cname}" x="0" y="0" width="450" height="450">\n'
    for rib, arcs in ribbons:
        out += (f'{p}  <PartDraw x="0" y="{fmt(PART_Y)}" width="450" height="{fmt(PART_H)}" '
                f'name="aurora_{cname}_{rib["name"]}">\n')
        lift, cth, calpha = rib["curtain"]
        gradient = curtain_gradient(rib, lift, cth, calpha, hexrgb)
        for a in arcs:
            out += arc_xml(a, cth, f"#FF{hexrgb}", indent + 4, lift=lift, gradient=gradient)
        for thickness, alpha in rib["layers"]:
            color = f"#{alpha:02X}{hexrgb}"
            for a in arcs:
                out += arc_xml(a, thickness, color, indent + 4)
        out += f"{p}  </PartDraw>\n"
    out += f"{p}</Group>\n"
    return out


def block_xml():
    ribbons = [(rib, build_arcs(rib)) for rib in RIBBONS]
    for rib, arcs in ribbons:
        lift, cth, _ = rib["curtain"]
        half = max([t for t, _ in rib["layers"]]) / 2
        for a in arcs:
            for i in range(41):
                t = math.radians(a["aL"] + (a["aR"] - a["aL"]) * i / 40)
                y = a["cy"] - a["r"] * math.cos(t)
                assert PART_Y <= y - lift - cth / 2 and y + half <= PART_Y + PART_H, (
                    rib["name"], y)
    out = []
    out.append("    <!-- AURORA:BEGIN (generated by tools/gen_aurora.py; edit that, not this) -->\n")
    out.append(
        "    <!-- Battery aurora. Wavy translucent ribbons across the sky, behind the comet,\n"
        "         mountains, sun/moon and time. Visible from the left edge (x=0) to\n"
        "         x = 4.5 * [BATTERY_PERCENT] (450 = full sky width). Each ribbon is a chain of\n"
        "         tangent-continuous Arcs (an arc spline, WFF has no path element); every Arc\n"
        "         keeps its left end fixed and a Transform moves its right end to the fill edge.\n"
        "         Colour: under 25% red, 25-80% blue, over 80% green. -->\n")
    out.append("    <Condition>\n")
    out.append("      <Expressions>\n")
    out.append('        <Expression name="aurora_low"><![CDATA[[BATTERY_PERCENT] < 25]]></Expression>\n')
    out.append('        <Expression name="aurora_high"><![CDATA[[BATTERY_PERCENT] > 80]]></Expression>\n')
    out.append("      </Expressions>\n")
    out.append('      <Compare expression="aurora_low">\n')
    out.append(branch_xml("red", COLORS["red"], ribbons, 8))
    out.append("      </Compare>\n")
    out.append('      <Compare expression="aurora_high">\n')
    out.append(branch_xml("green", COLORS["green"], ribbons, 8))
    out.append("      </Compare>\n")
    out.append("      <Default>\n")
    out.append(branch_xml("blue", COLORS["blue"], ribbons, 8))
    out.append("      </Default>\n")
    out.append("    </Condition>\n")
    out.append("    <!-- AURORA:END -->\n")
    return "".join(out), ribbons


def main():
    text = XML.read_text()
    block, ribbons = block_xml()
    if "<!-- AURORA:BEGIN" in text:
        text = re.sub(r"    <!-- AURORA:BEGIN.*?<!-- AURORA:END -->\n", lambda m: block, text, flags=re.S)
    else:
        # First run: drop the rim battery Arc condition, insert aurora as the first scene layer.
        text, n = re.subn(
            r'    <Condition>\n      <Expressions>\n        <Expression name="battery_ok">.*?</Condition>\n',
            "", text, count=1, flags=re.S)
        assert n == 1, "battery Condition not found"
        marker = '  <Scene backgroundColor="#ff000000">\n'
        assert marker in text
        text = text.replace(marker, marker + block, 1)
    XML.write_text(text)
    for rib, arcs in ribbons:
        print(rib["name"], len(arcs), "arcs; radii",
              fmt(min(a["r"] for a in arcs)), "-", fmt(max(a["r"] for a in arcs)))


if __name__ == "__main__":
    main()
