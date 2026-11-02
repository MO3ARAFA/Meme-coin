"""Generate Hroofy product cover + interior page SVGs (rendered to PNG by render.mjs)."""

import os, sys

FONTS = sys.argv[1]
OUT = sys.argv[2]
os.makedirs(OUT, exist_ok=True)

INK = "#2B2D42"
STYLE = f"""
<style>
@font-face {{ font-family: 'Baloo'; src: url('file://{FONTS}/Baloo.ttf'); font-weight: 400 800; }}
@font-face {{ font-family: 'Cairo'; src: url('file://{FONTS}/Cairo.ttf'); font-weight: 200 1000; }}
.h {{ font-family: 'Baloo', 'Cairo', sans-serif; font-weight: 800; }}
.b {{ font-family: 'Cairo', sans-serif; font-weight: 700; }}
</style>
"""


def star(cx, cy, r, fill, stroke=INK, sw=8):
    import math

    pts = []
    for i in range(10):
        a = math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append(f"{cx + rr * math.cos(a):.1f},{cy - rr * math.sin(a):.1f}")
    return f'<polygon points="{" ".join(pts)}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"/>'


def glyph(x, y, ch, size, fill, sw=14, stroke=INK, cls="h", rtl=False, extra=""):
    d = ' direction="rtl"' if rtl else ""
    return (
        f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}" text-anchor="middle"{d} '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}" paint-order="stroke" '
        f'stroke-linejoin="round" {extra}>{ch}</text>'
    )


# ---------------------------------------------------------------- illustrations
def art_arabic():
    return (
        star(560, 520, 60, "#FF8FB1")
        + star(1050, 600, 46, "#2EC4B6")
        + star(980, 1060, 38, "#A66CFF")
        + glyph(800, 990, "ح", 600, "#FFD23F", 22, rtl=True)
        + glyph(520, 1080, "ب", 150, "#FF6B4A", 12, rtl=True)
        + glyph(1080, 860, "ت", 140, "#5B8DEF", 12, rtl=True)
        + glyph(600, 760, "ث", 120, "#7BD389", 12, rtl=True)
    )


def art_english():
    return (
        glyph(560, 900, "A", 360, "#FF6B4A", 20)
        + glyph(800, 960, "B", 360, "#2EC4B6", 20)
        + glyph(1040, 900, "C", 360, "#FFD23F", 20)
        + '<circle cx="560" cy="1090" r="62" fill="#FF6B4A" stroke="#2B2D42" stroke-width="10"/>'
        '<path d="M560 1030 q10 -40 40 -46" fill="none" stroke="#2B2D42" stroke-width="10" stroke-linecap="round"/>'
        '<ellipse cx="610" cy="1000" rx="26" ry="14" fill="#7BD389" stroke="#2B2D42" stroke-width="8"/>'
        + star(1060, 1090, 50, "#A66CFF")
        + star(520, 560, 40, "#5B8DEF")
    )


def art_numbers():
    return (
        glyph(540, 960, "1", 380, "#5B8DEF", 20)
        + glyph(800, 1000, "2", 380, "#FF6B4A", 20)
        + glyph(1060, 960, "3", 380, "#7BD389", 20)
        + glyph(670, 640, "+", 160, "#FFD23F", 12)
        + glyph(930, 640, "=", 160, "#FF8FB1", 12)
        + star(1080, 560, 44, "#FFD23F")
        + star(520, 1090, 40, "#A66CFF")
    )


def art_animals():
    mane = "".join(
        f'<circle cx="{800 + 230 * __import__("math").cos(i * 0.5236):.0f}" cy="{790 + 230 * __import__("math").sin(i * 0.5236):.0f}" r="95" fill="#FF8F3F" stroke="#2B2D42" stroke-width="10"/>'
        for i in range(12)
    )
    return (
        "<g>"
        + mane
        + '<circle cx="800" cy="790" r="230" fill="#FFD23F" stroke="#2B2D42" stroke-width="12"/>'
        '<circle cx="720" cy="740" r="26" fill="#2B2D42"/><circle cx="880" cy="740" r="26" fill="#2B2D42"/>'
        '<circle cx="730" cy="730" r="8" fill="#fff"/><circle cx="890" cy="730" r="8" fill="#fff"/>'
        '<path d="M770 820 h60 l-30 36 z" fill="#FF6B4A" stroke="#2B2D42" stroke-width="8" stroke-linejoin="round"/>'
        '<path d="M740 880 q60 50 120 0" fill="none" stroke="#2B2D42" stroke-width="10" stroke-linecap="round"/>'
        '<circle cx="660" cy="830" r="26" fill="#FF8FB1" opacity="0.7"/><circle cx="940" cy="830" r="26" fill="#FF8FB1" opacity="0.7"/>'
        "</g>" + star(500, 520, 40, "#2EC4B6") + star(1100, 1080, 44, "#A66CFF")
    )


def art_space():
    return (
        '<circle cx="1060" cy="560" r="90" fill="#A66CFF" stroke="#2B2D42" stroke-width="10"/>'
        '<ellipse cx="1060" cy="560" rx="150" ry="34" fill="none" stroke="#2B2D42" stroke-width="10" transform="rotate(-18 1060 560)"/>'
        '<ellipse cx="1060" cy="560" rx="150" ry="34" fill="none" stroke="#FFD23F" stroke-width="5" transform="rotate(-18 1060 560)"/>'
        '<g transform="translate(800 820) rotate(-20) scale(1.7) translate(-200 -190)">'
        '<path d="M164 268 Q200 372 236 268 Z" fill="#FF6B4A" stroke="#2B2D42" stroke-width="6"/>'
        '<path d="M152 212 L104 296 L158 266 Z" fill="#2EC4B6" stroke="#2B2D42" stroke-width="6" stroke-linejoin="round"/>'
        '<path d="M248 212 L296 296 L242 266 Z" fill="#2EC4B6" stroke="#2B2D42" stroke-width="6" stroke-linejoin="round"/>'
        '<path d="M200 46 Q264 118 252 268 L148 268 Q136 118 200 46 Z" fill="#FFFFFF" stroke="#2B2D42" stroke-width="6"/>'
        '<path d="M200 46 Q226 72 238 104 L162 104 Q174 72 200 46 Z" fill="#FF6B4A" stroke="#2B2D42" stroke-width="6"/>'
        '<circle cx="200" cy="164" r="30" fill="#5B8DEF" stroke="#2B2D42" stroke-width="6"/>'
        "</g>"
        + star(500, 560, 40, "#FFD23F")
        + star(560, 1080, 30, "#FFD23F")
        + star(1120, 980, 34, "#FFD23F")
    )


def wing(fill, dashed=False):
    st = 'stroke-dasharray="4 26" stroke-linecap="round"' if dashed else ""
    f = "none" if dashed else fill
    return (
        f'<path d="M800 760 C 640 520, 420 560, 470 760 C 500 860, 640 860, 800 800 Z" fill="{f}" stroke="#2B2D42" stroke-width="12" {st}/>'
        f'<path d="M800 820 C 660 860, 520 960, 600 1050 C 670 1110, 770 1000, 800 880 Z" fill="{f}" stroke="#2B2D42" stroke-width="12" {st}/>'
    )


def art_creative():
    return (
        wing("#A66CFF")
        + '<g transform="translate(1600 0) scale(-1 1)">'
        + wing("none", True)
        + "</g>"
        + '<ellipse cx="800" cy="830" rx="26" ry="150" fill="#2B2D42"/>'
        '<path d="M790 690 q-30 -80 -70 -90 M810 690 q30 -80 70 -90" fill="none" stroke="#2B2D42" stroke-width="10" stroke-linecap="round"/>'
        '<circle cx="560" cy="700" r="34" fill="#FFD23F"/><circle cx="640" cy="960" r="26" fill="#FF8FB1"/>'
        '<g transform="translate(1050 1040) rotate(-40)"><rect x="-26" y="-130" width="52" height="210" rx="10" fill="#FF6B4A" stroke="#2B2D42" stroke-width="8"/>'
        '<path d="M-26 80 L0 140 L26 80 Z" fill="#FFC9B8" stroke="#2B2D42" stroke-width="8" stroke-linejoin="round"/></g>'
    )


def art_gift():
    return (
        '<rect x="560" y="620" width="480" height="420" rx="30" fill="#FF6B4A" stroke="#2B2D42" stroke-width="12"/>'
        '<rect x="530" y="540" width="540" height="120" rx="24" fill="#FF8F73" stroke="#2B2D42" stroke-width="12"/>'
        '<rect x="770" y="540" width="60" height="500" fill="#FFD23F" stroke="#2B2D42" stroke-width="10"/>'
        '<path d="M800 540 C 700 420, 600 480, 680 540 Z M800 540 C 900 420, 1000 480, 920 540 Z" fill="#FFD23F" stroke="#2B2D42" stroke-width="10" stroke-linejoin="round"/>'
        + star(560, 500, 44, "#2EC4B6")
        + star(1080, 520, 38, "#A66CFF")
        + star(1060, 1080, 30, "#FFD23F")
    )


# ---------------------------------------------------------------- cover template
def cover(
    name,
    color,
    spine,
    title,
    subtitle,
    age,
    art,
    ribbon="كتاب تلوين تعليمي",
    title_size=104,
):
    confetti = "".join(
        f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}" opacity="0.55"/>'
        for x, y, r, c in [
            (120, 160, 18, "#FF8FB1"),
            (1480, 240, 14, "#2EC4B6"),
            (150, 1820, 16, "#FFD23F"),
            (1460, 1840, 20, "#A66CFF"),
            (90, 980, 12, "#5B8DEF"),
            (1520, 1100, 12, "#7BD389"),
        ]
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="2000" viewBox="0 0 1600 2000">{STYLE}
<defs>
  <filter id="sh" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="40" stdDeviation="40" flood-color="#2B2D42" flood-opacity="0.28"/></filter>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFF6E2"/><stop offset="1" stop-color="#FFE3EC"/></linearGradient>
  <linearGradient id="gl" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff" stop-opacity="0.28"/><stop offset="0.5" stop-color="#ffffff" stop-opacity="0"/></linearGradient>
</defs>
<rect width="1600" height="2000" fill="url(#bg)"/>{confetti}
<ellipse cx="800" cy="1790" rx="560" ry="46" fill="#2B2D42" opacity="0.12"/>
<g filter="url(#sh)">
  <rect x="250" y="200" width="1140" height="1540" rx="36" fill="#F4EFE6"/>
  <rect x="236" y="190" width="1140" height="1540" rx="36" fill="#FFFFFF" stroke="#E7DED0" stroke-width="4"/>
  <rect x="220" y="180" width="1140" height="1540" rx="36" fill="{color}"/>
</g>
<rect x="1280" y="180" width="80" height="1540" rx="20" fill="{spine}"/>
<rect x="220" y="180" width="1140" height="1540" rx="36" fill="url(#gl)"/>
<rect x="300" y="250" width="300" height="96" rx="48" fill="#FFFFFF"/>
<text x="450" y="318" class="h" font-size="58" text-anchor="middle" direction="rtl" fill="{INK}">حروفي 🖍️</text>
<g><circle cx="1150" cy="300" r="96" fill="#FFD23F" stroke="{INK}" stroke-width="8"/>
<text x="1150" y="292" class="h" font-size="44" text-anchor="middle" direction="rtl" fill="{INK}">{age}</text>
<text x="1150" y="340" class="b" font-size="30" text-anchor="middle" direction="rtl" fill="{INK}">سنوات</text></g>
<rect x="300" y="400" width="980" height="820" rx="56" fill="#FFFFFF" stroke="{INK}" stroke-width="10"/>
<g transform="translate(-10 0)">{art}</g>
{glyph(790, 1390, title, title_size, "#FFFFFF", 18, rtl=True)}
<text x="790" y="1490" class="b" font-size="54" text-anchor="middle" direction="rtl" fill="#FFFFFF">{subtitle}</text>
<rect x="470" y="1560" width="640" height="96" rx="48" fill="{INK}"/>
<text x="790" y="1625" class="b" font-size="44" text-anchor="middle" direction="rtl" fill="#FFFFFF">{ribbon}</text>
</svg>"""
    open(os.path.join(OUT, f"{name}-cover.svg"), "w").write(svg)


# ---------------------------------------------------------------- interior pages (line art)
def page(name, header, body, tip):
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="2000" viewBox="0 0 1500 2000">{STYLE}
<rect width="1500" height="2000" fill="#F2EEE8"/>
<g><rect x="80" y="70" width="1340" height="1860" rx="24" fill="#FFFFFF" stroke="#D9D2C7" stroke-width="4"/></g>
<text x="750" y="230" class="h" font-size="96" text-anchor="middle" direction="rtl" fill="{INK}">{header}</text>
<g fill="none" stroke="#111" stroke-width="12" stroke-linejoin="round" stroke-linecap="round">{body}</g>
<text x="750" y="1800" class="b" font-size="40" text-anchor="middle" direction="rtl" fill="#555">{tip}</text>
<text x="750" y="1870" class="b" font-size="30" text-anchor="middle" fill="#999">hroofy · حروفي</text>
</svg>"""
    open(os.path.join(OUT, f"{name}-page.svg"), "w").write(svg)


def outline_glyph(x, y, ch, size, rtl=False, dashed=False, sw=12):
    d = ' direction="rtl"' if rtl else ""
    dash = ' stroke-dasharray="2 22"' if dashed else ""
    return f'<text x="{x}" y="{y}" class="h" font-size="{size}" text-anchor="middle"{d} fill="none" stroke="#111" stroke-width="{sw}"{dash}>{ch}</text>'


def ostar(cx, cy, r):
    return star(cx, cy, r, "none", "#111", 10)


# Arabic letter page: big ب + duck + tracing row
duck = (
    '<ellipse cx="1050" cy="1060" rx="200" ry="140"/><circle cx="930" cy="880" r="100"/>'
    '<path d="M850 880 q-70 10 -90 40 q60 20 110 -5"/><circle cx="905" cy="860" r="14" fill="#111"/>'
    '<path d="M1180 990 q70 -60 60 40"/><path d="M1000 1200 v60 h-40 M1100 1200 v60 h-40"/>'
    '<path d="M960 820 q20 -50 60 -30 q-10 40 -40 50"/>'
)
page(
    "arabic-alphabet",
    "ب  بَطّة",
    outline_glyph(470, 1150, "ب", 620, True, sw=14)
    + duck
    + "".join(
        outline_glyph(x, 1560, "ب", 230, True, True, 10) for x in (330, 620, 910, 1200)
    ),
    "لوّن البطة والحرف.. وبعدين اتبع النقط واكتب حرف الباء",
)
# English page: Aa + apple + tracing
apple = (
    '<path d="M1050 820 C 900 760, 820 900, 860 1050 C 900 1200, 1000 1240, 1050 1200 C 1100 1240, 1200 1200, 1240 1050 C 1280 900, 1200 760, 1050 820 Z"/>'
    '<path d="M1050 820 q10 -80 60 -110"/><path d="M1060 760 q80 -60 130 -20 q-60 50 -130 20"/>'
    '<circle cx="1000" cy="960" r="12" fill="#111"/><circle cx="1110" cy="960" r="12" fill="#111"/><path d="M1010 1030 q45 40 90 0"/>'
)
page(
    "english-alphabet",
    "A a  ·  Apple",
    outline_glyph(330, 1150, "A", 560)
    + outline_glyph(640, 1150, "a", 460)
    + apple
    + "".join(
        outline_glyph(x, 1560, t, 230, False, True, 10)
        for x, t in ((300, "A"), (530, "A"), (760, "A"), (990, "A"), (1220, "A"))
    ),
    "Color the apple, then trace the letters A a",
)
# Numbers page: color by number balloon
balloon = (
    '<path d="M750 420 C 480 420, 400 700, 520 900 C 600 1030, 690 1090, 750 1120 C 810 1090, 900 1030, 980 900 C 1100 700, 1020 420, 750 420 Z"/>'
    '<path d="M750 420 C 640 600, 640 900, 750 1120 M750 420 C 860 600, 860 900, 750 1120 M470 760 C 650 800, 850 800, 1030 760"/>'
    '<path d="M690 1150 h120 l-20 120 h-80 z"/><path d="M710 1120 l-10 30 M790 1120 l10 30"/>'
)
nums = "".join(
    f'<text x="{x}" y="{y}" class="h" font-size="70" text-anchor="middle" fill="#111" stroke="none">{n}</text>'
    for x, y, n in (
        (580, 640, 1),
        (750, 600, 2),
        (920, 640, 3),
        (600, 900, 4),
        (750, 960, 5),
        (900, 900, 1),
    )
)
key = "".join(
    f'<circle cx="{x}" cy="1520" r="60"/><text x="{x}" y="1650" class="h" font-size="60" text-anchor="middle" fill="#111" stroke="none">{n}</text>'
    for x, n in ((350, 1), (550, 2), (750, 3), (950, 4), (1150, 5))
)
page(
    "numbers-math",
    "لوّن حسب الرقم",
    balloon + nums + key + ostar(300, 520, 60) + ostar(1200, 560, 50),
    "اختار لون لكل رقم من 1 لـ 5 ولوّن المنطاد",
)
# Animals page: elephant
eleph = (
    '<path d="M560 1200 v130 h100 v-110 M880 1200 v130 h100 v-130"/>'
    '<ellipse cx="760" cy="980" rx="330" ry="250" fill="#fff"/>'
    '<path d="M330 880 C 260 1000, 300 1150, 380 1160 C 440 1160, 430 1090, 390 1080"/>'
    '<circle cx="480" cy="800" r="190" fill="#fff"/>'
    '<ellipse cx="640" cy="780" rx="130" ry="160" fill="#fff"/><circle cx="430" cy="760" r="18" fill="#111"/>'
    '<path d="M1090 960 q60 -10 70 60"/>'
)
drops = "".join(
    f'<path d="M{x} {y} q-30 50 0 70 q30 -20 0 -70 z"/>'
    for x, y in ((300, 560), (230, 480), (360, 440), (180, 600))
)
page(
    "animals-world",
    "الفيل الصغير 🐘",
    eleph + drops + '<path d="M140 1440 q200 -60 400 0 t400 0 t420 0"/>',
    "لوّن الفيل والمية اللي بيرشها بخرطومه",
)
# Space page: rocket + planet
page(
    "space-adventures",
    "رحلة إلى الفضاء 🚀",
    '<g transform="translate(560 1050) rotate(-15) scale(2.4) translate(-200 -190)" stroke-width="5">'
    '<path d="M164 268 Q200 372 236 268 Z"/><path d="M152 212 L104 296 L158 266 Z"/><path d="M248 212 L296 296 L242 266 Z"/>'
    '<path d="M200 46 Q264 118 252 268 L148 268 Q136 118 200 46 Z"/><path d="M162 104 L238 104"/><circle cx="200" cy="164" r="30"/></g>'
    '<circle cx="1130" cy="640" r="150"/><ellipse cx="1130" cy="640" rx="260" ry="60" transform="rotate(-18 1130 640)"/>'
    + ostar(1100, 1150, 70)
    + ostar(1250, 1400, 50)
    + ostar(300, 520, 50)
    + ostar(980, 1450, 40),
    "لوّن الصاروخ وزحل والنجوم بألوانك المفضلة",
)
# Creative page: half butterfly
page(
    "draw-and-complete",
    "أكمل الفراشة 🦋",
    '<g transform="translate(-50 120)"><path d="M800 760 C 640 520, 420 560, 470 760 C 500 860, 640 860, 800 800 Z"/>'
    '<path d="M800 820 C 660 860, 520 960, 600 1050 C 670 1110, 770 1000, 800 880 Z"/>'
    '<circle cx="610" cy="720" r="50"/><circle cx="670" cy="960" r="36"/>'
    '<g transform="translate(1600 0) scale(-1 1)" stroke-dasharray="2 26"><path d="M800 760 C 640 520, 420 560, 470 760 C 500 860, 640 860, 800 800 Z"/>'
    '<path d="M800 820 C 660 860, 520 960, 600 1050 C 670 1110, 770 1000, 800 880 Z"/></g>'
    '<ellipse cx="800" cy="830" rx="26" ry="150"/><path d="M790 690 q-30 -80 -70 -90 M810 690 q30 -80 70 -90"/></g>',
    "ارسم النص التاني من الفراشة بنفس الشكل.. وبعدين لوّنها",
)

# ---------------------------------------------------------------- covers
cover(
    "arabic-alphabet",
    "#FF6B4A",
    "#E2553A",
    "الحروف العربية",
    "من أ إلى ي · تلوين وتتبع",
    "3-6",
    art_arabic(),
)
cover(
    "english-alphabet",
    "#2EC4B6",
    "#22A69A",
    "ABC Fun",
    "الحروف الإنجليزية A-Z",
    "3-6",
    art_english(),
    title_size=130,
)
cover(
    "numbers-math",
    "#5B8DEF",
    "#4374D6",
    "الأرقام والحساب",
    "لوّن وعدّ من 1 إلى 20",
    "5-8",
    art_numbers(),
)
cover(
    "animals-world",
    "#7BD389",
    "#5DB86C",
    "عالم الحيوانات",
    "40 حيوان مرح للتلوين",
    "3-6",
    art_animals(),
)
cover(
    "space-adventures",
    "#3D3B8E",
    "#2E2C70",
    "الفضاء والمغامرات",
    "رحلة رواد الفضاء الصغار",
    "5-9",
    art_space(),
    title_size=96,
)
cover(
    "draw-and-complete",
    "#A66CFF",
    "#8B4FE8",
    "ارسم وأكمل",
    "الرسم الإبداعي للفنانين الصغار",
    "5-10",
    art_creative(),
)
cover(
    "magic-pocket-gift",
    "#FF8FB1",
    "#F06D96",
    "كتيب الجيب السحري",
    "20 رسمة بحجم الجيب A6",
    "3-9",
    art_gift(),
    ribbon="🎁 هدية مجانية فوق 1500 ج.م",
    title_size=96,
)


# ---------------------------------------------------------------- bundle composites (embed rendered covers)
def bundle(name, covers, title, subtitle, badge):
    n = len(covers)
    imgs = ""
    if n == 2:
        place = [(150, 430, -6, 640), (810, 430, 6, 640)]
    else:
        place = [
            (110 + i * 200, 470 + (abs(i - 2.5) * 36), (i - 2.5) * 5, 400)
            for i in range(n)
        ]
    for (x, y, rot, w), c in zip(place, covers):
        h = w / 0.747
        imgs += (
            f'<g transform="rotate({rot} {x + w / 2} {y + h / 2})">'
            f'<svg x="{x}" y="{y}" width="{w}" height="{h}" viewBox="214 174 1152 1552">'
            f'<image href="file://{OUT}/{c}-cover.png" x="0" y="0" width="1600" height="2000"/></svg></g>'
        )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="2000" viewBox="0 0 1600 2000">{STYLE}
<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFF6E2"/><stop offset="1" stop-color="#FFE3EC"/></linearGradient></defs>
<rect width="1600" height="2000" fill="url(#bg)"/>
<text x="800" y="200" class="h" font-size="110" text-anchor="middle" direction="rtl" fill="{INK}">{title}</text>
<text x="800" y="300" class="b" font-size="56" text-anchor="middle" direction="rtl" fill="#5B5F7A">{subtitle}</text>
{imgs}
<path d="M0 1560 q400 -60 800 0 t800 0 v440 h-1600 z" fill="#FFD23F" opacity="0.5"/>
<g transform="rotate(-10 1300 1640)"><circle cx="1300" cy="1640" r="170" fill="#FF6B4A" stroke="{INK}" stroke-width="10"/>
<text x="1300" y="1630" class="h" font-size="84" text-anchor="middle" direction="rtl" fill="{INK}">{badge}</text>
<text x="1300" y="1700" class="b" font-size="40" text-anchor="middle" direction="rtl" fill="{INK}">توفير</text></g>
<rect x="200" y="1760" width="760" height="100" rx="50" fill="{INK}"/>
<text x="580" y="1828" class="h" font-size="54" text-anchor="middle" direction="rtl" fill="#FFFFFF">حروفي 🖍️ لوّن.. تعلّم.. ابدع</text>
</svg>"""
    open(os.path.join(OUT, f"{name}-cover.svg"), "w").write(svg)


open(os.path.join(OUT, "_bundles.flag"), "w").write("1")
bundle(
    "arabic-english-letters-bundle",
    ["arabic-alphabet", "english-alphabet"],
    "باقة الحروف المزدوجة",
    "عربي + إنجليزي · كتابين",
    "40%",
)
bundle(
    "genius-complete-bundle",
    [
        "arabic-alphabet",
        "english-alphabet",
        "numbers-math",
        "animals-world",
        "space-adventures",
        "draw-and-complete",
    ],
    "باقة العباقرة الشاملة",
    "6 كتب تلوين · 344 صفحة",
    "40%",
)
print("svgs:", sorted(f for f in os.listdir(OUT) if f.endswith(".svg")))
