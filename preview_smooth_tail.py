#!/usr/bin/env python3
"""On-computer preview of watchface.xml at 14:30:00.

Draws the comet tail with the same arc radius, slice alphas, thicknesses, and
caps as watchface.xml (SRC_OVER, in document order), then mountains, the 14:30
sun, a full blue battery ring, and the digital time and date.
"""

import math
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
XML = ROOT / "watchface/src/main/res/raw/watchface.xml"
MOUNTAINS = ROOT / "watchface/src/main/res/drawable/mountains.png"
OUT = ROOT / "preview-smooth-tail.png"

# Gold is configuration option comet_tail_gold, the color in the reference shots.
# Default option remains cyan #00E5FF in watchface.xml.
COMET_COLOR = (0xFF, 0xD5, 0x4F)
SCALE = 4
SIZE = 450

INTER = "/usr/share/fonts/truetype/sand-box/google/Inter/Inter-VariableFont_opsz,wght.ttf"


def hex_rgb(value):
    value = value.strip().lstrip("#")
    if len(value) == 8:
        value = value[2:]
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def wff_point(angle_deg, radius, scale=SCALE):
    rad = math.radians(angle_deg)
    return (
        (225.0 + radius * math.sin(rad)) * scale,
        (225.0 - radius * math.cos(rad)) * scale,
    )


def parse_comet(xml_path):
    tree = ET.parse(xml_path)
    group = tree.find(".//Group[@name='comet']")
    parts = []
    for part in list(group):
        if part.tag != "PartDraw":
            continue
        alpha = int(part.get("alpha", "255"))
        px = float(part.get("x", "0"))
        py = float(part.get("y", "0"))
        shapes = []
        for child in list(part):
            if child.tag == "Arc":
                stroke = child.find("Stroke")
                shapes.append(
                    {
                        "kind": "arc",
                        "cx": float(child.get("centerX")),
                        "cy": float(child.get("centerY")),
                        "width": float(child.get("width")),
                        "height": float(child.get("height")),
                        "start": float(child.get("startAngle")),
                        "end": float(child.get("endAngle")),
                        "thickness": float(stroke.get("thickness")),
                        "cap": stroke.get("cap", "BUTT"),
                        "color": stroke.get("color"),
                    }
                )
            elif child.tag == "Ellipse":
                fill = child.find("Fill")
                shapes.append(
                    {
                        "kind": "ellipse",
                        "x": px + float(child.get("x", "0")),
                        "y": py + float(child.get("y", "0")),
                        "w": float(child.get("width")),
                        "h": float(child.get("height")),
                        "color": fill.get("color") if fill is not None else "#FFFFFF",
                    }
                )
        parts.append({"name": part.get("name"), "alpha": alpha, "shapes": shapes})
    return parts


def color_of(token):
    if token.startswith("[CONFIGURATION"):
        return COMET_COLOR
    return hex_rgb(token)


def draw_arc_mask(mask, shape):
    draw = ImageDraw.Draw(mask)
    radius = shape["width"] / 2.0
    span = shape["end"] - shape["start"]
    steps = max(16, int(abs(span) / 0.25))
    pts = []
    for i in range(steps + 1):
        pts.append(wff_point(shape["start"] + span * i / steps, radius))
    width = max(1, int(round(shape["thickness"] * SCALE)))
    draw.line(pts, fill=255, width=width, joint="curve")
    if shape["cap"] == "ROUND":
        r = width / 2.0
        for pt in (pts[0], pts[-1]):
            draw.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=255)
    elif shape["cap"] == "SQUARE":
        # Extend half a thickness along the tangent. Not used by the tail.
        pass


def stamp_part(canvas, part):
    dim = SIZE * SCALE
    if all(s["kind"] == "arc" for s in part["shapes"]):
        for shape in part["shapes"]:
            mask = Image.new("L", (dim, dim), 0)
            draw_arc_mask(mask, shape)
            layer = Image.new("RGBA", (dim, dim), color_of(shape["color"]) + (0,))
            layer.putalpha(mask.point(lambda p, a=part["alpha"]: (p * a) // 255))
            canvas.alpha_composite(layer)
        return
    layer = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for shape in part["shapes"]:
        if shape["kind"] != "ellipse":
            continue
        x = shape["x"] * SCALE
        y = shape["y"] * SCALE
        w = shape["w"] * SCALE
        h = shape["h"] * SCALE
        draw.ellipse([x, y, x + w, y + h], fill=color_of(shape["color"]) + (255,))
    if part["alpha"] != 255:
        layer.putalpha(layer.getchannel("A").point(lambda p, a=part["alpha"]: (p * a) // 255))
    canvas.alpha_composite(layer)


def draw_sun(layer):
    # 14:30:00. Same expression as the sun PartDraw transforms.
    seconds = 14 * 3600 + 30 * 60
    ang = -90.0 + 180.0 * ((seconds - 21600) / 43200.0)
    x = 208.0 + 130.0 * math.sin(math.radians(ang))
    y = 233.0 - 130.0 * math.cos(math.radians(ang))
    draw = ImageDraw.Draw(layer)
    box = [x * SCALE, y * SCALE, (x + 34) * SCALE, (y + 34) * SCALE]
    draw.ellipse(box, fill=(0xE6, 0xC3, 0x6A, 255))


def draw_battery(layer):
    # 100%: start -90, end -90+360, thickness 6, radius 212, color #3D8BFF.
    draw = ImageDraw.Draw(layer)
    r = 212.0
    width = max(1, int(round(6 * SCALE)))
    box = [(225 - r) * SCALE, (225 - r) * SCALE, (225 + r) * SCALE, (225 + r) * SCALE]
    draw.ellipse(box, outline=(0x3D, 0x8B, 0xFF, 255), width=width)


def font_at(size, weight):
    font = ImageFont.truetype(INTER, size)
    opsz = max(14, min(32, size))
    font.set_variation_by_axes([opsz, weight])
    return font


def draw_text(image):
    draw = ImageDraw.Draw(image)
    time_font = font_at(84, 300)
    # TimeText box x=40 y=162 w=370 h=92, align CENTER, weight LIGHT.
    time = "2:30"
    tb = draw.textbbox((0, 0), time, font=time_font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    tx = 40 + (370 - tw) / 2 - tb[0]
    ty = 162 + (92 - th) / 2 - tb[1]
    draw.text((tx, ty), time, font=time_font, fill=(0xF4, 0xF4, 0xF4, 255))

    date_font = font_at(26, 400)
    date = "Sun 4"
    db = draw.textbbox((0, 0), date, font=date_font)
    dw, dh = db[2] - db[0], db[3] - db[1]
    dx = 40 + (370 - dw) / 2 - db[0]
    dy = 252 + (36 - dh) / 2 - db[1]
    draw.text((dx, dy), date, font=date_font, fill=(0xA3, 0xA3, 0xA3, 255))


def main():
    dim = SIZE * SCALE
    canvas = Image.new("RGBA", (dim, dim), (0, 0, 0, 255))
    for part in parse_comet(XML):
        stamp_part(canvas, part)

    overlay = Image.new("RGBA", (dim, dim), (0, 0, 0, 0))
    draw_sun(overlay)
    draw_battery(overlay)

    face = canvas.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    mountains = Image.open(MOUNTAINS).convert("RGBA")
    face.alpha_composite(mountains)
    face.alpha_composite(overlay.resize((SIZE, SIZE), Image.Resampling.LANCZOS))
    draw_text(face)

    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, SIZE - 1, SIZE - 1], fill=255)
    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
    out.paste(face, (0, 0), mask)
    out.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
