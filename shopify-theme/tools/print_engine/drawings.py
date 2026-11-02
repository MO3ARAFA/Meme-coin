"""Hroofy line-art drawing library for print coloring pages.

Every drawing is SVG markup on a 600x600 canvas. Shapes are drawn inside a
parent <g> that sets fill="#fff" stroke="#111" (see wrap()), so closed shapes
are white (they hide the lines behind them, keeping regions clean to color)
and open lines must set fill="none" themselves. Solid details use fill="#111".
"""

import math

NF = 'fill="none"'
INK = 'fill="#111"'


def eyes(x1, y1, x2, y2, r=13):
    return f'<circle cx="{x1}" cy="{y1}" r="{r}" {INK} stroke="none"/><circle cx="{x2}" cy="{y2}" r="{r}" {INK} stroke="none"/>'


def smile(cx, cy, w=50, d=28):
    return f'<path d="M{cx - w / 2} {cy} Q {cx} {cy + d} {cx + w / 2} {cy}" {NF}/>'


def star_points(cx, cy, r, inner=0.45, n=5, rot=-90):
    pts = []
    for i in range(n * 2):
        a = math.radians(rot + i * 180 / n)
        rr = r if i % 2 == 0 else r * inner
        pts.append(f"{cx + rr * math.cos(a):.1f},{cy + rr * math.sin(a):.1f}")
    return " ".join(pts)


def star_shape(cx, cy, r):
    return f'<polygon points="{star_points(cx, cy, r)}"/>'


def heart(cx, cy, s=1.0):
    """Heart path with coordinates scaled numerically, so the stroke width stays constant."""
    def p(x, y):
        return f"{cx + x * s:.1f} {cy + y * s:.1f}"
    return (f'<path d="M{p(0, 60)} C {p(-90, 0)}, {p(-70, -70)}, {p(0, -30)} '
            f'C {p(70, -70)}, {p(90, 0)}, {p(0, 60)} Z"/>')


# ---------------------------------------------------------------- drawings
def rabbit():
    return (
        '<ellipse cx="300" cy="470" rx="130" ry="100"/>'
        '<ellipse cx="240" cy="150" rx="42" ry="115"/><ellipse cx="360" cy="150" rx="42" ry="115"/>'
        f'<ellipse cx="240" cy="160" rx="16" ry="70" {NF}/><ellipse cx="360" cy="160" rx="16" ry="70" {NF}/>'
        '<circle cx="300" cy="300" r="110"/>'
        + eyes(260, 285, 340, 285)
        + f'<path d="M288 320 h24 l-12 14 z" {INK}/>'
        + smile(300, 345, 40, 16)
        + f'<path d="M200 330 h50 M200 350 h50 M350 330 h50 M350 350 h50" {NF}/>'
        f'<ellipse cx="300" cy="510" rx="50" ry="40" {NF}/>'
    )


def duck():
    return (
        '<path d="M470 360 Q 540 300 540 380 Q 520 420 480 420 Z"/>'
        '<ellipse cx="330" cy="390" rx="180" ry="115"/>'
        '<circle cx="200" cy="230" r="90"/>'
        '<path d="M120 225 Q 60 230 55 255 Q 90 275 125 262 Z"/>'
        + eyes(185, 205, 185, 205, 12)[:0]
        + f'<circle cx="190" cy="205" r="13" {INK} stroke="none"/>'
        f'<path d="M270 380 Q 340 330 410 390 Q 340 440 270 380 Z"/>'
        f'<path d="M100 520 Q 160 490 220 520 T 340 520 T 460 520 T 560 520" {NF}/>'
    )


def apple():
    return (
        '<path d="M300 200 C 200 140, 90 220, 110 360 C 130 480, 230 540, 300 500 C 370 540, 470 480, 490 360 C 510 220, 400 140, 300 200 Z"/>'
        f'<path d="M300 200 Q 300 140 330 105" {NF}/>'
        '<path d="M325 130 Q 400 80 450 120 Q 390 170 325 130 Z"/>'
        + eyes(250, 330, 350, 330)
        + smile(300, 380)
    )


def fox():
    return (
        '<path d="M300 490 L 135 250 L 165 100 L 255 195 L 345 195 L 435 100 L 465 250 Z"/>'
        f'<path d="M175 140 L 230 200 M425 140 L 370 200" {NF}/>'
        '<path d="M300 490 L 200 330 Q 300 375 400 330 Z"/>'
        + eyes(245, 290, 355, 290)
        + f'<circle cx="300" cy="470" r="18" {INK} stroke="none"/>'
    )


def camel():
    return (
        '<rect x="160" y="370" width="34" height="150" rx="12"/><rect x="230" y="370" width="34" height="150" rx="12"/>'
        '<rect x="340" y="370" width="34" height="150" rx="12"/><rect x="400" y="370" width="34" height="150" rx="12"/>'
        '<path d="M130 390 Q 140 230 230 260 Q 280 140 350 245 Q 420 225 450 300 L 450 390 Z"/>'
        '<path d="M420 330 L 480 175 L 525 185 L 470 345 Z"/>'
        '<ellipse cx="520" cy="165" rx="60" ry="34"/>'
        + f'<circle cx="525" cy="155" r="9" {INK} stroke="none"/>'
        f'<path d="M135 330 Q 100 340 95 380" {NF}/>'
    )


def whale():
    return (
        '<path d="M460 320 Q 530 260 570 225 Q 560 300 520 330 Q 560 360 570 440 Q 530 400 460 360 Z"/>'
        '<path d="M80 330 Q 90 180 300 180 Q 480 180 490 330 Q 480 430 300 430 Q 100 430 80 330 Z"/>'
        f'<path d="M110 360 Q 300 420 470 360" {NF}/>'
        + f'<circle cx="170" cy="290" r="14" {INK} stroke="none"/>'
        + smile(150, 340, 50, 18)
        + f'<path d="M290 180 Q 275 115 230 95 M300 180 L 300 70 M310 180 Q 325 115 370 95" {NF}/>'
    )


def sheep():
    parts = "".join(
        f'<circle cx="{x}" cy="{y}" r="72"/>'
        for x, y in (
            (230, 300),
            (310, 270),
            (390, 300),
            (420, 380),
            (340, 420),
            (250, 420),
            (190, 370),
        )
    )
    return '<rect x="220" y="430" width="30" height="100" rx="10"/><rect x="290" y="440" width="30" height="95" rx="10"/>' '<rect x="350" y="440" width="30" height="95" rx="10"/><rect x="400" y="430" width="30" height="100" rx="10"/>' + parts + '<ellipse cx="310" cy="350" rx="150" ry="100"/>' + '<ellipse cx="150" cy="320" rx="62" ry="78"/>' + eyes(
        130, 310, 170, 310, 9
    ) + smile(
        150, 350, 30, 12
    )


def bear():
    return (
        '<circle cx="190" cy="160" r="60"/><circle cx="410" cy="160" r="60"/>'
        f'<circle cx="190" cy="160" r="26" {NF}/><circle cx="410" cy="160" r="26" {NF}/>'
        '<circle cx="300" cy="310" r="170"/>'
        + eyes(240, 280, 360, 280)
        + '<ellipse cx="300" cy="380" rx="80" ry="58"/>'
        f'<ellipse cx="300" cy="355" rx="26" ry="16" {INK} stroke="none"/>'
        + smile(300, 395, 50, 20)
    )


def corn():
    kernels = "".join(
        f'<path d="M{x} 130 L {x} 450" {NF}/>' for x in (265, 300, 335)
    ) + "".join(
        f'<path d="M225 {y} Q 300 {y + 12} 375 {y}" {NF}/>' for y in range(170, 440, 45)
    )
    return (
        '<ellipse cx="300" cy="290" rx="90" ry="190"/>'
        + kernels
        + '<path d="M300 500 Q 160 420 170 200 Q 240 330 300 420 Z"/>'
        '<path d="M300 500 Q 440 420 430 200 Q 360 330 300 420 Z"/>'
    )


def pomegranate():
    return (
        '<path d="M245 165 L 255 105 L 280 140 L 300 95 L 320 140 L 345 105 L 355 165 Z"/>'
        '<circle cx="300" cy="340" r="180"/>'
        + eyes(250, 330, 350, 330)
        + smile(300, 385)
        + f'<path d="M150 300 Q 170 220 230 190" {NF}/>'
    )


def giraffe():
    spots = "".join(
        f'<circle cx="{x}" cy="{y}" r="{r}" {NF}/>'
        for x, y, r in (
            (180, 410, 22),
            (250, 450, 18),
            (300, 400, 16),
            (350, 330, 14),
            (380, 230, 12),
        )
    )
    return (
        '<rect x="130" y="440" width="30" height="110" rx="10"/><rect x="190" y="450" width="30" height="100" rx="10"/>'
        '<rect x="280" y="450" width="30" height="100" rx="10"/><rect x="330" y="440" width="30" height="110" rx="10"/>'
        '<ellipse cx="245" cy="430" rx="150" ry="75"/>'
        '<path d="M320 410 L 370 160 L 430 170 L 390 420 Z"/>'
        f'<path d="M395 95 L 390 60 M440 95 L 450 60" {NF}/>'
        f'<circle cx="390" cy="55" r="12" {INK} stroke="none"/><circle cx="452" cy="55" r="12" {INK} stroke="none"/>'
        '<ellipse cx="420" cy="130" rx="75" ry="45"/>'
        + f'<circle cx="430" cy="118" r="10" {INK} stroke="none"/>'
        + spots
    )


def fish():
    return (
        '<path d="M440 300 L 565 205 L 540 300 L 565 395 Z"/>'
        '<path d="M240 200 Q 290 130 350 205 Z"/>'
        '<ellipse cx="290" cy="300" rx="175" ry="112"/>'
        f'<path d="M330 195 Q 300 300 330 405 M380 210 Q 355 300 380 390" {NF}/>'
        + f'<circle cx="190" cy="280" r="16" {INK} stroke="none"/>'
        + smile(170, 335, 40, 16)
        + f'<circle cx="90" cy="170" r="22" {NF}/><circle cx="120" cy="110" r="14" {NF}/>'
    )


def sun():
    rays = "".join(
        f'<polygon points="{300 + 175 * math.cos(math.radians(a - 12)):.0f},{300 + 175 * math.sin(math.radians(a - 12)):.0f} '
        f"{300 + 270 * math.cos(math.radians(a)):.0f},{300 + 270 * math.sin(math.radians(a)):.0f} "
        f'{300 + 175 * math.cos(math.radians(a + 12)):.0f},{300 + 175 * math.sin(math.radians(a + 12)):.0f}"/>'
        for a in range(0, 360, 30)
    )
    return (
        rays
        + '<circle cx="300" cy="300" r="165"/>'
        + eyes(245, 270, 355, 270)
        + smile(300, 335, 90, 40)
    )


def rocket():
    return (
        '<g transform="translate(300 300) scale(1.45) translate(-200 -190)">'
        '<path d="M164 268 Q 200 372 236 268 Z"/><path d="M152 212 L 104 296 L 158 266 Z"/>'
        '<path d="M248 212 L 296 296 L 242 266 Z"/>'
        '<path d="M200 46 Q 264 118 252 268 L 148 268 Q 136 118 200 46 Z"/>'
        '<path d="M200 46 Q 226 72 238 104 L 162 104 Q 174 72 200 46 Z"/>'
        '<circle cx="200" cy="164" r="30"/></g>'
        + star_shape(80, 120, 34)
        + star_shape(520, 470, 28)
    )


def frog():
    return (
        '<path d="M120 470 Q 60 520 120 545 L 200 520 Z"/><path d="M480 470 Q 540 520 480 545 L 400 520 Z"/>'
        '<circle cx="205" cy="230" r="65"/><circle cx="395" cy="230" r="65"/>'
        '<ellipse cx="300" cy="400" rx="200" ry="135"/>'
        '<circle cx="205" cy="230" r="65"/><circle cx="395" cy="230" r="65"/>'
        + eyes(205, 235, 395, 235, 24)
        + f'<path d="M190 400 Q 300 480 410 400" {NF}/>'
        f'<circle cx="190" cy="350" r="18" {NF}/><circle cx="410" cy="350" r="18" {NF}/>'
    )


def airplane():
    return (
        '<path d="M260 270 L 340 110 L 395 110 L 345 270 Z"/><path d="M260 330 L 340 490 L 395 490 L 345 330 Z"/>'
        '<path d="M110 268 L 70 170 L 125 170 L 185 262 Z"/>'
        '<path d="M75 300 Q 75 258 140 258 L 470 258 Q 545 268 565 300 Q 545 332 470 342 L 140 342 Q 75 342 75 300 Z"/>'
        + "".join(f'<circle cx="{x}" cy="298" r="16"/>' for x in (230, 290, 350, 410))
        + f'<path d="M500 275 Q 530 285 540 300" {NF}/>'
    )


def envelope():
    return (
        '<rect x="90" y="160" width="420" height="290" rx="22"/>'
        f'<path d="M95 175 L 300 330 L 505 175" {NF}/><path d="M95 440 L 240 290 M505 440 L 360 290" {NF}/>'
        + heart(300, 395, 0.45)
        + '<rect x="420" y="185" width="60" height="70" rx="6"/>'
    )


def bird():
    return (
        '<path d="M180 330 L 70 280 L 90 360 Z"/>'
        '<ellipse cx="290" cy="340" rx="150" ry="115"/><circle cx="410" cy="235" r="80"/>'
        '<path d="M480 225 L 545 245 L 480 265 Z"/>'
        + f'<circle cx="430" cy="220" r="13" {INK} stroke="none"/>'
        '<path d="M220 320 Q 300 260 360 340 Q 290 390 220 320 Z"/>'
        f'<path d="M270 450 L 260 520 M320 450 L 330 520 M240 520 h40 M310 520 h40" {NF}/>'
    )


def cloud():
    drops = "".join(
        f'<path d="M{x} {y} q-22 36 0 52 q22 -16 0 -52 z"/>'
        for x, y in ((200, 440), (300, 470), (400, 440))
    )
    return (
        drops
        + '<path d="M150 400 Q 75 400 85 325 Q 100 255 180 268 Q 200 165 300 178 Q 385 140 432 228 Q 525 220 522 310 Q 530 400 440 400 Z"/>'
        + eyes(250, 300, 350, 300)
        + smile(300, 340, 60, 26)
    )


def butterfly():
    return (
        '<path d="M300 280 C 210 120, 60 140, 90 290 C 110 360, 210 360, 300 320 Z"/>'
        '<path d="M300 280 C 390 120, 540 140, 510 290 C 490 360, 390 360, 300 320 Z"/>'
        '<path d="M300 320 C 210 340, 120 420, 170 490 C 220 540, 290 450, 300 360 Z"/>'
        '<path d="M300 320 C 390 340, 480 420, 430 490 C 380 540, 310 450, 300 360 Z"/>'
        f'<circle cx="180" cy="250" r="34" {NF}/><circle cx="420" cy="250" r="34" {NF}/>'
        f'<circle cx="210" cy="440" r="22" {NF}/><circle cx="390" cy="440" r="22" {NF}/>'
        '<ellipse cx="300" cy="340" rx="24" ry="140"/>'
        f'<path d="M290 205 Q 260 120 220 105 M310 205 Q 340 120 380 105" {NF}/>'
    )


def moon():
    return (
        '<path d="M390 100 A 210 210 0 1 0 390 500 A 165 165 0 1 1 390 100 Z"/>'
        f'<path d="M215 270 q 22 18 44 0" {NF}/>'
        + smile(250, 360, 60, 26)
        + star_shape(470, 200, 40)
        + star_shape(500, 380, 28)
    )


def ball():
    return (
        '<circle cx="300" cy="300" r="200"/>'
        f'<path d="M300 100 Q 190 300 300 500 M300 100 Q 410 300 300 500 M100 300 Q 300 390 500 300" {NF}/>'
    )


def lemon():
    return '<path d="M115 320 Q 100 285 135 278 Q 200 165 330 175 Q 465 185 485 285 Q 515 298 492 332 Q 425 445 300 435 Q 165 425 115 320 Z"/>' '<path d="M360 178 Q 400 110 470 120 Q 440 185 360 178 Z"/>' + eyes(
        250, 300, 350, 300
    ) + smile(
        300, 350, 60, 24
    )


def banana():
    return (
        '<path d="M140 175 Q 150 430 430 470 Q 485 475 495 445 Q 300 405 215 175 Q 205 140 172 145 Q 140 150 140 175 Z"/>'
        f'<path d="M175 200 Q 210 380 400 440" {NF}/>'
        '<path d="M150 150 L 145 110 L 185 115 L 180 150 Z"/>'
    )


def star():
    return (
        star_shape(300, 310, 250) + eyes(250, 300, 350, 300) + smile(300, 350, 60, 26)
    )


def gift():
    return (
        '<rect x="130" y="270" width="340" height="260" rx="18"/>'
        '<rect x="105" y="200" width="390" height="90" rx="16"/>'
        '<rect x="275" y="200" width="50" height="330"/>'
        '<path d="M300 200 C 220 100, 140 150, 210 200 Z"/><path d="M300 200 C 380 100, 460 150, 390 200 Z"/>'
    )


def flower():
    petals = "".join(
        f'<circle cx="{300 + 95 * math.cos(math.radians(a)):.0f}" cy="{230 + 95 * math.sin(math.radians(a)):.0f}" r="70"/>'
        for a in range(0, 360, 60)
    )
    return f'<path d="M300 300 L 300 560" {NF}/>' '<path d="M300 450 Q 200 390 170 450 Q 240 490 300 450 Z"/><path d="M300 500 Q 400 440 430 500 Q 360 540 300 500 Z"/>' + petals + '<circle cx="300" cy="230" r="65"/>' + eyes(
        275, 220, 325, 220, 9
    ) + smile(
        300, 250, 34, 14
    )


def hand():
    return (
        '<path d="M215 540 L 200 330 Q 140 270 120 300 Q 100 330 160 400 L 205 450 '
        "L 205 210 Q 205 175 235 175 Q 262 175 264 210 L 266 300 L 270 145 Q 272 112 302 112 Q 330 114 331 146 "
        "L 333 300 L 340 165 Q 342 133 371 134 Q 398 136 398 168 L 398 310 L 412 210 Q 416 182 442 186 Q 466 190 463 220 "
        'L 445 420 Q 430 520 360 545 Z"/>'
        f'<path d="M264 300 L 266 330 M333 300 L 333 330 M398 310 L 398 335" {NF}/>'
        + heart(330, 420, 0.4)
    )


def cat():
    return (
        '<path d="M170 240 L 150 90 L 270 170 Z"/><path d="M430 240 L 450 90 L 330 170 Z"/>'
        '<circle cx="300" cy="320" r="175"/>'
        + eyes(240, 300, 360, 300, 16)
        + f'<path d="M285 345 h30 l-15 16 z" {INK}/>'
        + f'<path d="M300 361 q -25 28 -50 10 M300 361 q 25 28 50 10" {NF}/>'
        f'<path d="M140 340 h90 M140 375 l90 -15 M460 340 h-90 M460 375 l-90 -15" {NF}/>'
    )


def egg():
    return (
        '<path d="M300 90 C 175 90, 125 300, 135 385 C 145 485, 225 535, 300 535 C 375 535, 455 485, 465 385 C 475 300, 425 90, 300 90 Z"/>'
        f'<path d="M140 320 L 180 290 L 220 320 L 260 290 L 300 320 L 340 290 L 380 320 L 420 290 L 460 320" {NF}/>'
        + "".join(
            f'<circle cx="{x}" cy="{y}" r="14" {NF}/>'
            for x, y in (
                (240, 200),
                (330, 170),
                (360, 230),
                (230, 430),
                (300, 460),
                (380, 420),
            )
        )
    )


def house():
    return (
        '<rect x="380" y="140" width="50" height="100"/>'
        '<path d="M110 300 L 300 130 L 490 300 Z"/><rect x="150" y="290" width="300" height="240"/>'
        '<rect x="260" y="400" width="80" height="130" rx="8"/>'
        '<rect x="180" y="330" width="60" height="60"/><rect x="360" y="330" width="60" height="60"/>'
        f'<path d="M210 330 v60 M180 360 h60 M390 330 v60 M360 360 h60" {NF}/>'
        + f'<circle cx="320" cy="470" r="7" {INK} stroke="none"/>'
    )


def icecream():
    return (
        '<path d="M190 300 L 300 560 L 410 300 Z"/>'
        f'<path d="M215 360 L 375 330 M235 410 L 360 385 M255 460 L 340 440 M380 360 L 225 330 M365 410 L 240 385" {NF}/>'
        '<circle cx="240" cy="280" r="80"/><circle cx="360" cy="280" r="80"/><circle cx="300" cy="200" r="90"/>'
        '<circle cx="310" cy="95" r="26"/>'
        + f'<path d="M315 70 Q 330 40 355 40" {NF}/>'
    )


def jellyfish():
    tent = "".join(
        f'<path d="M{x} 300 q -25 40 0 80 t 0 80 t 0 80" {NF}/>'
        for x in (190, 245, 300, 355, 410)
    )
    return (
        tent
        + '<path d="M135 300 Q 135 125 300 125 Q 465 125 465 300 Q 425 322 383 300 Q 341 322 300 300 Q 259 322 217 300 Q 176 322 135 300 Z"/>'
        + eyes(250, 230, 350, 230)
        + smile(300, 260, 50, 20)
    )


def kite():
    bows = "".join(
        f'<path d="M{x - 18} {y - 14} L {x + 18} {y + 14} L {x + 18} {y - 14} L {x - 18} {y + 14} Z"/>'
        for x, y in ((250, 520), (200, 470))
    )
    return (
        f'<path d="M300 470 Q 270 520 250 520 Q 220 520 200 470 Q 180 430 140 440" {NF}/>'
        + bows
        + '<path d="M300 70 L 455 255 L 300 470 L 145 255 Z"/>'
        f'<path d="M300 70 L 300 470 M145 255 L 455 255" {NF}/>'
    )


def nest():
    return (
        '<ellipse cx="230" cy="300" rx="60" ry="80"/><ellipse cx="320" cy="290" rx="60" ry="85"/><ellipse cx="400" cy="305" rx="55" ry="75"/>'
        '<path d="M95 330 Q 300 560 505 330 Z"/>'
        f'<path d="M130 360 Q 300 420 470 360 M160 410 Q 300 470 440 410 M80 330 l 50 -20 M520 330 l -50 -20" {NF}/>'
    )


def orange():
    return '<circle cx="300" cy="330" r="185"/>' f'<path d="M300 145 L 300 110" {NF}/><path d="M300 125 Q 380 70 430 110 Q 370 160 300 125 Z"/>' + eyes(
        250, 320, 350, 320
    ) + smile(
        300, 370
    ) + "".join(
        f'<circle cx="{x}" cy="{y}" r="6" {INK} stroke="none"/>'
        for x, y in ((190, 260), (410, 270), (200, 420), (400, 430), (300, 470))
    )


def pizza():
    return (
        '<path d="M300 540 L 110 170 Q 300 90 490 170 Z"/>'
        f'<path d="M130 210 Q 300 140 470 210" {NF}/>'
        + "".join(
            f'<circle cx="{x}" cy="{y}" r="{r}"/>'
            for x, y, r in (
                (300, 260, 34),
                (230, 320, 28),
                (360, 340, 28),
                (300, 430, 24),
            )
        )
    )


def quilt():
    cells = ""
    for i, (x, y) in enumerate(
        (x, y) for y in (110, 243, 376) for x in (110, 243, 376)
    ):
        cells += f'<rect x="{x}" y="{y}" width="133" height="133"/>'
        cx, cy = x + 66, y + 66
        cells += [
            star_shape(cx, cy, 45),
            heart(cx, cy, 0.5),
            f'<circle cx="{cx}" cy="{cy}" r="40"/>',
        ][i % 3]
    return cells


def tree():
    return (
        '<rect x="260" y="360" width="80" height="190" rx="10"/>'
        + "".join(
            f'<circle cx="{x}" cy="{y}" r="{r}"/>'
            for x, y, r in (
                (200, 300, 110),
                (400, 300, 110),
                (300, 220, 140),
                (300, 340, 120),
            )
        )
        + '<path d="M150 300 Q 300 180 450 300 Q 300 420 150 300 Z" stroke="none"/>'
        + "".join(
            f'<circle cx="{x}" cy="{y}" r="22"/>'
            for x, y in ((240, 240), (360, 210), (380, 330), (220, 350))
        )
    )


def umbrella():
    return (
        f'<path d="M300 300 L 300 470 Q 300 515 258 515 Q 228 510 228 482" {NF}/>'
        '<path d="M100 300 Q 300 75 500 300 Q 466 278 433 300 Q 400 278 366 300 Q 333 278 300 300 Q 266 278 233 300 Q 200 278 166 300 Q 133 278 100 300 Z"/>'
        f'<path d="M300 110 Q 230 200 233 300 M300 110 Q 370 200 366 300" {NF}/>'
        + "".join(
            f'<path d="M{x} {y} q-15 26 0 38 q15 -12 0 -38 z"/>'
            for x, y in ((120, 420), (480, 400), (440, 500))
        )
    )


def vase():
    return (
        f'<path d="M300 250 L 300 120 M260 250 Q 240 160 190 130 M340 250 Q 360 160 410 130" {NF}/>'
        + "".join(
            f'<circle cx="{x}" cy="{y}" r="38"/>'
            for x, y in ((300, 105), (185, 125), (415, 125))
        )
        + '<path d="M225 260 Q 160 390 215 525 L 385 525 Q 440 390 375 260 Z"/><rect x="235" y="230" width="130" height="40" rx="12"/>'
        + f'<path d="M200 400 Q 300 440 400 400" {NF}/>'
    )


def xylophone():
    bars = "".join(
        f'<rect x="{100 + i * 70}" y="{170 + i * 18}" width="55" height="{300 - i * 36}" rx="10"/>'
        for i in range(6)
    )
    return (
        f'<path d="M80 220 L 520 300 M80 420 L 520 380" {NF}/>'
        + bars
        + f'<path d="M180 120 L 300 60 M420 140 L 510 60" {NF}/>'
        '<circle cx="300" cy="60" r="22"/><circle cx="510" cy="60" r="22"/>'
    )


def yoyo():
    return (
        f'<path d="M300 300 L 300 60 Q 300 30 330 40 Q 350 60 320 70" {NF}/>'
        '<circle cx="300" cy="330" r="190"/><circle cx="300" cy="330" r="120"/><circle cx="300" cy="330" r="35"/>'
    )


def zebra():
    stripes = "".join(
        f'<path d="M{x} 270 Q {x + 15} 330 {x} 390" {NF}/>'
        for x in (180, 230, 280, 330, 380)
    )
    return (
        '<rect x="160" y="380" width="32" height="140" rx="10"/><rect x="215" y="390" width="32" height="130" rx="10"/>'
        '<rect x="350" y="390" width="32" height="130" rx="10"/><rect x="405" y="380" width="32" height="140" rx="10"/>'
        '<path d="M150 330 Q 120 300 110 360" fill="none"/>'
        '<ellipse cx="300" cy="330" rx="170" ry="85"/>'
        + stripes
        + '<path d="M410 300 L 450 150 L 510 160 L 470 330 Z"/>'
        '<path d="M450 140 L 455 100 L 475 140 L 490 100 L 500 145 Z"/>'
        '<ellipse cx="505" cy="190" rx="42" ry="78" transform="rotate(-35 505 190)"/>'
        f'<circle cx="488" cy="165" r="10" {INK} stroke="none"/>'
        f'<path d="M520 225 Q 535 235 545 225" {NF}/>'
    )


def heart_drawing():
    return heart(300, 300, 3.2) + eyes(250, 260, 350, 260) + smile(300, 320, 60, 26)


LIBRARY = {
    name: fn
    for name, fn in globals().items()
    if callable(fn)
    and fn.__module__ == __name__
    and name
    not in (
        "eyes",
        "smile",
        "star_points",
        "star_shape",
        "heart",
        "wrap",
        "heart_drawing",
    )
}
LIBRARY["heart"] = heart_drawing


def wrap(name, x, y, size, stroke=12):
    """Place a drawing in a size x size box at (x, y). stroke is in canvas units."""
    s = size / 600
    return (
        f'<g transform="translate({x} {y}) scale({s:.4f})" fill="#fff" stroke="#111" '
        f'stroke-width="{stroke}" stroke-linejoin="round" stroke-linecap="round">{LIBRARY[name]()}</g>'
    )


# Extra drawings (animals, space, free-drawing frames) live in drawings_extra.py.
from drawings_extra import EXTRA  # noqa: E402

LIBRARY.update(EXTRA)
