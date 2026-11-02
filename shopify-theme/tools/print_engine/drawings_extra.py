"""Extra Hroofy line-art drawings: animals, space and free-drawing frames.

Same conventions as drawings.py: 600x600 canvas, parent <g> sets
fill="#fff" stroke="#111"; open lines use fill="none".
"""

import math

from drawings import INK, NF, eyes, smile, star_shape, heart


# ---------------------------------------------------------------- animals
def lion():
    mane = "".join(
        f'<circle cx="{300 + 175 * math.cos(math.radians(a)):.0f}" cy="{290 + 175 * math.sin(math.radians(a)):.0f}" r="70"/>'
        for a in range(0, 360, 30)
    )
    return (
        mane + '<circle cx="300" cy="290" r="175"/>'
        '<circle cx="190" cy="150" r="34"/><circle cx="410" cy="150" r="34"/>'
        '<circle cx="300" cy="300" r="150"/>'
        + eyes(245, 270, 355, 270, 15)
        + '<ellipse cx="300" cy="350" rx="60" ry="42"/>'
        + f'<path d="M280 330 h40 l-20 22 z" {INK}/>'
        + f'<path d="M300 352 v20 M300 372 q -25 22 -50 6 M300 372 q 25 22 50 6" {NF}/>'
    )


def elephant():
    return (
        '<rect x="200" y="400" width="60" height="130" rx="18"/><rect x="400" y="400" width="60" height="130" rx="18"/>'
        '<ellipse cx="340" cy="360" rx="190" ry="135"/>'
        f'<path d="M530 350 q 40 10 40 60" {NF}/>'
        '<circle cx="200" cy="250" r="110"/>'
        '<path d="M250 170 C 340 120, 390 230, 340 330 C 310 380, 260 340, 260 300 Z"/>'
        '<path d="M110 280 C 70 360, 70 470, 120 520 C 150 545, 185 520, 165 495 C 125 450, 140 360, 165 320 Z"/>'
        f'<circle cx="165" cy="230" r="14" {INK} stroke="none"/>'
        + smile(185, 290, 40, 14)
    )


def cow():
    spots = (
        f'<path d="M260 300 q 40 -20 60 20 q -10 40 -60 20 z" {INK}/>'
        f'<path d="M400 360 q 40 -10 40 30 q -30 30 -50 0 z" {INK}/>'
    )
    return (
        '<rect x="200" y="400" width="40" height="120" rx="12"/><rect x="260" y="410" width="40" height="110" rx="12"/>'
        '<rect x="380" y="410" width="40" height="110" rx="12"/><rect x="440" y="400" width="40" height="120" rx="12"/>'
        '<rect x="170" y="250" width="340" height="190" rx="80"/>'
        + spots
        + f'<path d="M510 300 q 40 30 30 110" {NF}/>'
        '<path d="M95 160 L 60 120 L 120 140 Z"/><path d="M225 160 L 260 120 L 200 140 Z"/>'
        '<ellipse cx="160" cy="250" rx="85" ry="100"/>'
        '<ellipse cx="160" cy="320" rx="70" ry="45"/>'
        + eyes(130, 220, 190, 220, 11)
        + f'<circle cx="140" cy="320" r="9" {INK} stroke="none"/><circle cx="180" cy="320" r="9" {INK} stroke="none"/>'
    )


def hen():
    return (
        '<path d="M420 260 Q 520 200 520 300 Q 500 360 430 360 Z"/>'
        '<ellipse cx="320" cy="350" rx="170" ry="140"/>'
        '<path d="M230 330 Q 320 280 400 350 Q 320 420 230 330 Z"/>'
        '<circle cx="190" cy="210" r="80"/>'
        '<path d="M160 135 Q 170 90 195 120 Q 210 80 230 125 Q 250 100 250 145 Z"/>'
        '<path d="M115 205 L 70 225 L 115 240 Z"/>'
        '<path d="M125 250 Q 120 290 145 290 Q 160 270 150 250 Z"/>'
        + f'<circle cx="175" cy="195" r="12" {INK} stroke="none"/>'
        + f'<path d="M280 485 L 270 540 M360 485 L 370 540 M245 540 h50 M345 540 h50" {NF}/>'
    )


def pig():
    return (
        '<rect x="180" y="420" width="40" height="90" rx="12"/><rect x="380" y="420" width="40" height="90" rx="12"/>'
        '<ellipse cx="320" cy="360" rx="200" ry="140"/>'
        f'<path d="M520 340 q 40 -20 30 20 q -10 30 20 30" {NF}/>'
        '<path d="M130 160 L 140 240 L 200 200 Z"/><path d="M290 160 L 280 240 L 220 200 Z"/>'
        '<circle cx="210" cy="280" r="110"/>'
        + eyes(175, 260, 245, 260, 12)
        + '<ellipse cx="210" cy="320" rx="50" ry="34"/>'
        + f'<circle cx="195" cy="320" r="9" {INK} stroke="none"/><circle cx="225" cy="320" r="9" {INK} stroke="none"/>'
    )


def turtle():
    plates = (
        f'<path d="M300 200 L 360 250 L 340 330 L 260 330 L 240 250 Z" {NF}/>'
        f'<path d="M240 250 L 160 260 M360 250 L 440 260 M260 330 L 210 390 M340 330 L 390 390 M300 200 L 300 130" {NF}/>'
    )
    return (
        '<ellipse cx="160" cy="420" rx="50" ry="30"/><ellipse cx="440" cy="420" rx="50" ry="30"/>'
        '<path d="M480 300 L 540 320 L 480 340 Z"/>'
        '<circle cx="120" cy="300" r="60"/>'
        + f'<circle cx="105" cy="285" r="10" {INK} stroke="none"/>'
        + smile(110, 320, 34, 14)
        + '<path d="M150 380 Q 150 120 300 120 Q 450 120 450 380 Z"/>'
        + plates
    )


def octopus():
    legs = "".join(
        f'<path d="M{x} 350 q {d} 60 0 110 q -{d} 40 {d // 2} 70" {NF}/>'
        for x, d in (
            (180, -40),
            (225, 30),
            (270, -30),
            (330, 30),
            (375, -30),
            (420, 40),
        )
    )
    return (
        legs
        + '<path d="M150 360 Q 140 120 300 110 Q 460 120 450 360 Q 300 400 150 360 Z"/>'
        + eyes(250, 260, 350, 260, 18)
        + smile(300, 310, 60, 26)
        + f'<circle cx="210" cy="190" r="16" {NF}/><circle cx="390" cy="180" r="12" {NF}/>'
    )


def crab():
    legs = "".join(
        f'<path d="M{x1} 360 L {x2} 440" {NF}/>'
        for x1, x2 in ((200, 140), (220, 170), (380, 430), (400, 460))
    )
    return (
        legs + '<path d="M170 260 L 120 180 M430 260 L 480 180" fill="none"/>'
        '<path d="M120 180 C 50 160, 60 80, 110 80 L 130 130 L 160 90 C 190 120, 170 180, 120 180 Z"/>'
        '<path d="M480 180 C 550 160, 540 80, 490 80 L 470 130 L 440 90 C 410 120, 430 180, 480 180 Z"/>'
        '<ellipse cx="300" cy="320" rx="170" ry="110"/>'
        f'<path d="M260 220 L 250 170 M340 220 L 350 170" {NF}/>'
        '<circle cx="250" cy="160" r="22"/><circle cx="350" cy="160" r="22"/>'
        + eyes(250, 160, 350, 160, 9)
        + smile(300, 330, 70, 30)
    )


def owl():
    return (
        '<path d="M190 120 L 220 200 L 160 190 Z"/><path d="M410 120 L 380 200 L 440 190 Z"/>'
        '<ellipse cx="300" cy="330" rx="170" ry="210"/>'
        '<ellipse cx="300" cy="400" rx="100" ry="120"/>'
        f'<path d="M240 380 q 15 15 30 0 M330 380 q 15 15 30 0 M260 430 q 15 15 30 0 M310 430 q 15 15 30 0" {NF}/>'
        '<circle cx="235" cy="240" r="58"/><circle cx="365" cy="240" r="58"/>'
        + eyes(235, 240, 365, 240, 22)
        + '<path d="M285 285 L 315 285 L 300 315 Z"/>'
        f'<path d="M260 540 v 30 M340 540 v 30" {NF}/>'
    )


def penguin():
    return (
        '<path d="M190 520 h 80 l -20 -30 z"/><path d="M330 520 h 80 l -20 -30 z"/>'
        '<path d="M140 300 Q 100 380 150 430 Z"/><path d="M460 300 Q 500 380 450 430 Z"/>'
        '<ellipse cx="300" cy="320" rx="160" ry="200"/>'
        '<ellipse cx="300" cy="360" rx="110" ry="150"/>'
        + eyes(255, 220, 345, 220, 14)
        + '<path d="M275 255 L 325 255 L 300 290 Z"/>'
    )


def ladybug():
    spots = "".join(
        f'<circle cx="{x}" cy="{y}" r="{r}" {INK} stroke="none"/>'
        for x, y, r in (
            (230, 300, 30),
            (370, 300, 30),
            (210, 410, 24),
            (390, 410, 24),
            (260, 490, 18),
            (340, 490, 18),
        )
    )
    return (
        f'<path d="M250 150 Q 220 80 180 70 M350 150 Q 380 80 420 70" {NF}/>'
        '<circle cx="180" cy="70" r="14"/><circle cx="420" cy="70" r="14"/>'
        '<ellipse cx="300" cy="370" rx="190" ry="200"/>'
        f'<path d="M300 200 L 300 570" {NF}/>'
        + spots
        + '<path d="M180 220 Q 300 90 420 220 Q 300 260 180 220 Z"/>'
        + eyes(260, 195, 340, 195, 10)
    )


# ---------------------------------------------------------------- space
def _planet(r=190, extra=""):
    return f'<circle cx="300" cy="300" r="{r}"/>' + extra


def sun_planet():
    from drawings import sun

    return sun()


def mercury():
    craters = "".join(
        f'<circle cx="{x}" cy="{y}" r="{r}" {NF}/>'
        for x, y, r in (
            (230, 230, 34),
            (370, 260, 24),
            (280, 380, 40),
            (390, 380, 18),
            (200, 340, 16),
        )
    )
    return _planet(170, craters) + star_shape(80, 90, 26) + star_shape(520, 510, 22)


def venus():
    bands = "".join(
        f'<path d="M{130 + i * 10} {200 + i * 60} Q 300 {170 + i * 60} {470 - i * 10} {200 + i * 60}" {NF}/>'
        for i in range(4)
    )
    return _planet(185, bands) + eyes(255, 290, 345, 290, 12)[:0]


def earth():
    land = (
        '<path d="M180 220 Q 230 170 290 200 Q 320 250 280 290 Q 230 300 210 350 Q 160 330 160 280 Z"/>'
        '<path d="M330 330 Q 390 300 420 340 Q 430 410 370 440 Q 320 420 330 330 Z"/>'
        '<path d="M350 170 Q 400 160 420 200 Q 390 230 350 210 Z"/>'
    )
    return _planet(195, land) + eyes(260, 250, 340, 250, 0)[:0]


def mars():
    return _planet(
        180,
        f'<path d="M230 140 Q 300 110 370 140 Q 300 170 230 140 Z"/>'
        + "".join(
            f'<circle cx="{x}" cy="{y}" r="{r}" {NF}/>'
            for x, y, r in ((240, 300, 30), (360, 340, 40), (300, 420, 20))
        ),
    ) + star_shape(520, 100, 26)


def jupiter():
    bands = "".join(
        f'<path d="M{110 + abs(i - 2) * 20} {200 + i * 50} Q 300 {215 + i * 50} {490 - abs(i - 2) * 20} {200 + i * 50}" {NF}/>'
        for i in range(5)
    )
    return _planet(210, bands + '<ellipse cx="370" cy="360" rx="50" ry="30"/>')


def saturn():
    return (
        f'<path d="M80 340 A 230 70 -15 0 1 520 260" {NF}/>'
        '<circle cx="300" cy="300" r="140"/>'
        f'<path d="M160 260 Q 300 290 440 250 M170 330 Q 300 360 430 320" {NF}/>'
        '<path d="M80 340 A 230 70 -15 0 0 520 260 L 500 250 A 205 55 -15 0 1 100 330 Z"/>'
    )


def uranus():
    return (
        '<ellipse cx="300" cy="300" rx="60" ry="260" fill="none"/>'
        '<circle cx="300" cy="300" r="170"/>'
        f'<path d="M300 130 Q 330 300 300 470" {NF}/>'
    )


def neptune():
    return _planet(
        190,
        f'<path d="M150 260 Q 300 230 450 260 M140 340 Q 300 370 460 340" {NF}/>'
        '<ellipse cx="240" cy="300" rx="45" ry="28"/>'
        f'<path d="M330 290 q 30 -20 60 0" {NF}/>',
    ) + star_shape(520, 90, 24)


def astronaut():
    return (
        '<rect x="390" y="230" width="90" height="170" rx="20"/>'
        '<rect x="200" y="420" width="70" height="120" rx="20"/><rect x="330" y="420" width="70" height="120" rx="20"/>'
        '<rect x="170" y="260" width="260" height="210" rx="70"/>'
        '<rect x="250" y="320" width="100" height="70" rx="12"/>'
        f'<circle cx="275" cy="355" r="10" {NF}/><circle cx="325" cy="355" r="10" {NF}/>'
        '<path d="M170 300 Q 110 320 100 390 Q 120 410 150 390 Q 160 350 200 340 Z"/>'
        '<path d="M430 300 Q 490 260 520 200 Q 500 180 480 195 Q 460 240 410 260 Z"/>'
        '<circle cx="300" cy="170" r="125"/>'
        '<path d="M215 170 Q 215 95 300 95 Q 385 95 385 170 Q 385 230 300 230 Q 215 230 215 170 Z"/>'
        + f'<path d="M240 130 q 20 -20 50 -20" {NF}/>'
        + eyes(270, 165, 330, 165, 12)
        + smile(300, 195, 40, 14)
    )


def alien():
    return (
        f'<path d="M230 140 L 190 60 M370 140 L 410 60" {NF}/>'
        '<circle cx="190" cy="55" r="20"/><circle cx="410" cy="55" r="20"/>'
        '<path d="M230 540 L 230 470 M370 540 L 370 470" fill="none"/>'
        '<path d="M200 470 Q 200 380 300 380 Q 400 380 400 470 Z"/>'
        '<ellipse cx="300" cy="250" rx="170" ry="140"/>'
        '<ellipse cx="300" cy="230" rx="60" ry="70"/>'
        + f'<circle cx="300" cy="235" r="28" {INK} stroke="none"/>'
        + smile(300, 330, 70, 26)
        + f'<path d="M190 540 h80 M330 540 h80" {NF}/>'
    )


def ufo():
    beam = f'<path d="M230 360 L 150 560 M370 360 L 450 560" {NF} stroke-dasharray="4 18"/>'
    return (
        beam + '<path d="M200 260 Q 200 140 300 140 Q 400 140 400 260 Z"/>'
        '<ellipse cx="300" cy="300" rx="230" ry="70"/>'
        + "".join(
            f'<circle cx="{x}" cy="300" r="16"/>' for x in (170, 235, 300, 365, 430)
        )
        + eyes(270, 210, 330, 210, 12)
        + smile(300, 235, 34, 12)
    )


def satellite():
    panel = lambda x: (
        f'<rect x="{x}" y="240" width="160" height="120" rx="6"/>'
        f'<path d="M{x + 53} 240 v120 M{x + 107} 240 v120 M{x} 300 h160" {NF}/>'
    )
    return (
        f'<path d="M210 300 h -10 M390 300 h 10" {NF}/>'
        + panel(40)
        + panel(400)
        + '<rect x="210" y="220" width="180" height="160" rx="16"/>'
        f'<path d="M300 220 L 300 150" {NF}/>'
        + '<path d="M240 150 Q 300 70 360 150 Z"/>'
        f'<circle cx="300" cy="300" r="34" {NF}/>'
        + star_shape(520, 500, 24)
        + star_shape(90, 470, 20)
    )


def station():
    return (
        f'<path d="M60 300 H 540" {NF}/>'
        '<rect x="40" y="170" width="120" height="70" rx="6"/><rect x="40" y="360" width="120" height="70" rx="6"/>'
        '<rect x="440" y="170" width="120" height="70" rx="6"/><rect x="440" y="360" width="120" height="70" rx="6"/>'
        f'<path d="M100 240 V 360 M500 240 V 360" {NF}/>'
        '<rect x="200" y="250" width="200" height="100" rx="30"/>'
        '<circle cx="300" cy="300" r="70"/>'
        + "".join(f'<circle cx="{x}" cy="300" r="14"/>' for x in (265, 300, 335))
    )


def telescope():
    return (
        f'<path d="M300 330 L 200 540 M300 330 L 300 540 M300 330 L 400 540" {NF}/>'
        '<g transform="rotate(-30 300 300)"><rect x="140" y="260" width="300" height="80" rx="16"/>'
        '<rect x="430" y="245" width="70" height="110" rx="12"/><rect x="100" y="275" width="50" height="50" rx="8"/></g>'
        + star_shape(470, 90, 34)
        + star_shape(540, 200, 20)
    )


def comet():
    tail = "".join(
        f'<path d="M{320 + i * 22} {270 - i * 22} Q {430 + i * 30} {170 - i * 40} 570 {40 + i * 30}" {NF}/>'
        for i in range(4)
    )
    return (
        tail
        + '<circle cx="250" cy="340" r="120"/>'
        + eyes(215, 330, 285, 330, 12)
        + smile(250, 370, 50, 20)
        + star_shape(90, 120, 24)
        + star_shape(120, 520, 20)
    )


def bigdipper():
    pts = [
        (90, 210),
        (190, 170),
        (290, 200),
        (370, 260),
        (380, 380),
        (510, 400),
        (520, 280),
    ]
    path = (
        "M"
        + " L ".join(f"{x} {y}" for x, y in pts[:5])
        + f" L {pts[5][0]} {pts[5][1]} L {pts[6][0]} {pts[6][1]} L {pts[3][0]} {pts[3][1]}"
    )
    return f'<path d="{path}" {NF} stroke-dasharray="2 16"/>' + "".join(
        star_shape(x, y, 36) for x, y in pts
    )


def rover():
    return (
        '<path d="M60 500 Q 300 450 540 500" fill="none"/>'
        + "".join(
            f'<circle cx="{x}" cy="430" r="45"/><circle cx="{x}" cy="430" r="14"/>'
            for x in (160, 300, 440)
        )
        + '<rect x="120" y="300" width="360" height="90" rx="14"/>'
        f'<path d="M380 300 L 380 200 L 460 180" {NF}/>'
        '<rect x="430" y="150" width="80" height="55" rx="10"/>'
        + f'<circle cx="470" cy="177" r="14" {NF}/>'
        '<rect x="160" y="250" width="160" height="50" rx="6"/>'
        f'<path d="M213 250 v50 M267 250 v50" {NF}/>'
    )


def asteroid():
    return (
        '<path d="M150 260 Q 140 160 250 140 Q 360 100 430 180 Q 500 250 460 360 Q 420 470 300 460 Q 170 450 150 360 Z"/>'
        + "".join(
            f'<circle cx="{x}" cy="{y}" r="{r}" {NF}/>'
            for x, y, r in (
                (240, 230, 30),
                (370, 260, 22),
                (300, 370, 40),
                (400, 380, 16),
            )
        )
        + star_shape(80, 90, 22)
        + star_shape(530, 520, 24)
        + star_shape(540, 120, 16)
    )


# ---------------------------------------------------------------- free-drawing frames
def fishbowl():
    return (
        '<rect x="200" y="510" width="200" height="40" rx="10"/>'
        '<path d="M190 120 L 410 120 L 400 150 Q 540 260 480 420 Q 430 520 300 520 Q 170 520 120 420 Q 60 260 200 150 Z"/>'
        f'<path d="M110 300 Q 300 280 490 300" {NF} stroke-dasharray="6 14"/>'
        f'<path d="M230 500 q -20 -60 10 -110 M370 500 q 20 -60 -10 -110" {NF}/>'
    )


def cake():
    return (
        f'<path d="M230 170 v -60 M300 170 v -70 M370 170 v -60" {NF}/>'
        '<path d="M230 110 q -15 -30 0 -50 q 15 20 0 50 z"/><path d="M300 100 q -15 -30 0 -50 q 15 20 0 50 z"/>'
        '<path d="M370 110 q -15 -30 0 -50 q 15 20 0 50 z"/>'
        '<rect x="90" y="400" width="420" height="140" rx="18"/>'
        '<rect x="150" y="280" width="300" height="130" rx="18"/>'
        '<rect x="200" y="170" width="200" height="115" rx="18"/>'
        '<ellipse cx="300" cy="555" rx="260" ry="25"/>'
    )


def helmet():
    return (
        '<rect x="150" y="470" width="300" height="90" rx="30"/>'
        '<circle cx="300" cy="290" r="230"/>'
        '<path d="M130 290 Q 130 140 300 140 Q 470 140 470 290 Q 470 440 300 440 Q 130 440 130 290 Z"/>'
        f'<path d="M180 220 q 30 -40 80 -50" {NF}/>'
    )


def box_open():
    return (
        '<path d="M120 260 L 60 170 L 260 150 L 300 230 Z"/><path d="M480 260 L 540 170 L 340 150 L 300 230 Z"/>'
        '<path d="M120 260 L 480 260 L 480 540 L 120 540 Z"/>'
        '<path d="M120 260 L 300 230 L 480 260" fill="none"/>'
    )


EXTRA = {
    fn.__name__: fn
    for fn in (
        lion,
        elephant,
        cow,
        hen,
        pig,
        turtle,
        octopus,
        crab,
        owl,
        penguin,
        ladybug,
        mercury,
        venus,
        earth,
        mars,
        jupiter,
        saturn,
        uranus,
        neptune,
        astronaut,
        alien,
        ufo,
        satellite,
        station,
        telescope,
        comet,
        bigdipper,
        rover,
        asteroid,
        fishbowl,
        cake,
        helmet,
        box_open,
    )
}
