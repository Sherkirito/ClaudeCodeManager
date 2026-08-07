import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
PNG = ASSETS / "app-icon.png"
ICO = ASSETS / "app-icon.ico"
SVG = ASSETS / "app-icon.svg"


def rr(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def line(draw, xy, fill, width=1):
    draw.line(xy, fill=fill, width=width, joint="curve")


def glow(base, mask, color, blur):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer.putalpha(mask.filter(ImageFilter.GaussianBlur(blur)))
    color_layer = Image.new("RGBA", base.size, color)
    layer = Image.composite(color_layer, Image.new("RGBA", base.size, (0, 0, 0, 0)), layer.split()[-1])
    base.alpha_composite(layer)


def make_icon(size=1024):
    scale = size / 1024
    def s(v):
        return int(round(v * scale))

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background plate.
    rr(draw, (s(64), s(64), s(960), s(960)), s(190), (17, 24, 39, 255))
    rr(draw, (s(88), s(88), s(936), s(936)), s(168), (28, 39, 62, 255), (94, 234, 212, 46), s(4))

    # Subtle diagonal color panels.
    draw.polygon([(s(105), s(720)), (s(800), s(90)), (s(936), s(90)), (s(936), s(240)), (s(260), s(936)), (s(105), s(936))], fill=(30, 64, 91, 120))
    draw.polygon([(s(64), s(64)), (s(450), s(64)), (s(64), s(440))], fill=(45, 212, 191, 38))

    # Storage stack.
    storage = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(storage)
    stack_colors = [(38, 92, 116, 255), (34, 79, 106, 255), (31, 68, 96, 255)]
    y_positions = [610, 686, 762]
    for idx, y in enumerate(y_positions):
        fill = stack_colors[idx]
        sd.ellipse((s(250), s(y - 54), s(774), s(y + 58)), fill=(55, 148, 167, 255))
        sd.rectangle((s(250), s(y), s(774), s(y + 86)), fill=fill)
        sd.ellipse((s(250), s(y + 32), s(774), s(y + 144)), fill=(24, 54, 82, 255))
        sd.arc((s(250), s(y - 54), s(774), s(y + 58)), 0, 180, fill=(143, 245, 230, 220), width=s(8))
        sd.arc((s(250), s(y + 32), s(774), s(y + 144)), 0, 180, fill=(90, 185, 205, 150), width=s(5))
    img.alpha_composite(storage)

    # Agent head.
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((s(298), s(180), s(726), s(608)), fill=255)
    glow(img, mask, (45, 212, 191, 95), s(34))
    draw.ellipse((s(298), s(180), s(726), s(608)), fill=(245, 248, 252, 255), outline=(125, 244, 230, 255), width=s(10))
    draw.ellipse((s(340), s(222), s(684), s(566)), fill=(229, 238, 247, 255))
    draw.ellipse((s(387), s(337), s(455), s(405)), fill=(15, 23, 42, 255))
    draw.ellipse((s(569), s(337), s(637), s(405)), fill=(15, 23, 42, 255))
    draw.ellipse((s(404), s(352), s(428), s(376)), fill=(94, 234, 212, 255))
    draw.ellipse((s(586), s(352), s(610), s(376)), fill=(94, 234, 212, 255))
    line(draw, [(s(446), s(477)), (s(512), s(505)), (s(578), s(477))], fill=(34, 79, 106, 255), width=s(14))

    # Antenna and agent nodes.
    line(draw, [(s(512), s(180)), (s(512), s(120))], fill=(125, 244, 230, 255), width=s(14))
    draw.ellipse((s(482), s(70), s(542), s(130)), fill=(94, 234, 212, 255), outline=(236, 253, 245, 255), width=s(6))
    for angle, cx, cy in [(0, 774, 340), (120, 216, 390), (240, 792, 520)]:
        line(draw, [(s(680 if cx > 512 else 324), s(390 if cy < 450 else 510)), (s(cx), s(cy))], fill=(94, 234, 212, 180), width=s(9))
        draw.ellipse((s(cx - 42), s(cy - 42), s(cx + 42), s(cy + 42)), fill=(22, 163, 184, 255), outline=(204, 251, 241, 255), width=s(6))
        draw.ellipse((s(cx - 15), s(cy - 15), s(cx + 15), s(cy + 15)), fill=(236, 253, 245, 255))

    # Archive cards behind the database hint at saved records.
    for offset, alpha in [(0, 210), (34, 155), (68, 105)]:
        rr(draw, (s(302 + offset), s(690 + offset // 3), s(724 + offset), s(746 + offset // 3)), s(22),
           (226, 246, 255, alpha), (125, 244, 230, alpha), s(4))
        line(draw, [(s(348 + offset), s(718 + offset // 3)), (s(620 + offset), s(718 + offset // 3))],
             fill=(20, 83, 105, alpha), width=s(7))

    # Final crisp border and small shadow.
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shd = ImageDraw.Draw(shadow)
    rr(shd, (s(64), s(64), s(960), s(960)), s(190), (0, 0, 0, 115))
    shadow = shadow.filter(ImageFilter.GaussianBlur(s(20)))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.alpha_composite(shadow, (0, s(18)))
    out.alpha_composite(img)
    ImageDraw.Draw(out).rounded_rectangle((s(64), s(64), s(960), s(960)), radius=s(190), outline=(148, 246, 231, 135), width=s(5))
    return out


def write_svg():
    SVG.write_text(
        """<svg width="1024" height="1024" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
  <rect x="64" y="64" width="896" height="896" rx="190" fill="#111827"/>
  <rect x="88" y="88" width="848" height="848" rx="168" fill="#1c273e" stroke="#5eead4" stroke-opacity=".22" stroke-width="4"/>
  <path d="M105 720 800 90h136v150L260 936H105z" fill="#1e405b" opacity=".55"/>
  <g opacity=".95">
    <ellipse cx="512" cy="556" rx="262" ry="56" fill="#3794a7"/>
    <rect x="250" y="610" width="524" height="86" fill="#265c74"/>
    <ellipse cx="512" cy="696" rx="262" ry="56" fill="#183652"/>
    <ellipse cx="512" cy="632" rx="262" ry="56" fill="#3794a7"/>
    <rect x="250" y="686" width="524" height="86" fill="#224f6a"/>
    <ellipse cx="512" cy="772" rx="262" ry="56" fill="#183652"/>
    <ellipse cx="512" cy="708" rx="262" ry="56" fill="#3794a7"/>
    <rect x="250" y="762" width="524" height="86" fill="#1f4460"/>
    <ellipse cx="512" cy="848" rx="262" ry="56" fill="#183652"/>
  </g>
  <line x1="512" y1="180" x2="512" y2="120" stroke="#7df4e6" stroke-width="14" stroke-linecap="round"/>
  <circle cx="512" cy="100" r="30" fill="#5eead4" stroke="#ecfdf5" stroke-width="6"/>
  <circle cx="512" cy="394" r="214" fill="#f5f8fc" stroke="#7df4e6" stroke-width="10"/>
  <circle cx="512" cy="394" r="172" fill="#e5eef7"/>
  <circle cx="421" cy="371" r="34" fill="#0f172a"/><circle cx="603" cy="371" r="34" fill="#0f172a"/>
  <circle cx="416" cy="364" r="12" fill="#5eead4"/><circle cx="598" cy="364" r="12" fill="#5eead4"/>
  <path d="M446 477 512 505l66-28" fill="none" stroke="#224f6a" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>
  <g stroke="#5eead4" stroke-width="9" stroke-linecap="round" opacity=".78">
    <line x1="680" y1="390" x2="774" y2="340"/><line x1="324" y1="390" x2="216" y2="390"/><line x1="680" y1="510" x2="792" y2="520"/>
  </g>
  <g fill="#16a3b8" stroke="#ccfbf1" stroke-width="6"><circle cx="774" cy="340" r="42"/><circle cx="216" cy="390" r="42"/><circle cx="792" cy="520" r="42"/></g>
  <g fill="#ecfdf5"><circle cx="774" cy="340" r="15"/><circle cx="216" cy="390" r="15"/><circle cx="792" cy="520" r="15"/></g>
</svg>
""",
        encoding="utf-8",
    )


def main():
    ASSETS.mkdir(exist_ok=True)
    icon = make_icon()
    icon.save(PNG)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon.save(ICO, sizes=sizes)
    write_svg()
    print(f"Wrote {ICO}")
    print(f"Wrote {PNG}")
    print(f"Wrote {SVG}")


if __name__ == "__main__":
    main()
