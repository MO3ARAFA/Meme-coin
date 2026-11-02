#!/usr/bin/env python3
"""Hroofy print-ready interior PDF engine.

Builds the interior files for Lulu Direct / Amazon KDP style print-on-demand:

  * Trim 8.5 x 11 in, full-bleed page 8.75 x 11.25 in (0.125 in bleed per side).
    The pocket gift booklet uses Lulu's Pocket Book trim 4.25 x 6.875 in
    (page 4.5 x 7.125 in with bleed).
  * Vector output: every page is SVG with embedded OFL fonts (Baloo Bhaijaan 2,
    Cairo), printed to PDF by Chromium, so lines and text stay sharp at any DPI.
  * Single-sided rule: every coloring page is followed by a back page with a
    faint frame, a faint logo and a note that it is left blank on purpose, so
    markers never bleed onto the next drawing.
  * Safe margin 0.5 in inside the trim on every side, plus 0.25 in extra gutter
    on the binding edge. The gutter alternates per page: for an RTL (Arabic)
    book the binding is on the right of odd pages; for an LTR (English) book it
    is on the left of odd pages. Use --binding to override.

Usage:
    python3 generate_print_pdfs.py                   # all books
    python3 generate_print_pdfs.py arabic numbers    # some books
    python3 generate_print_pdfs.py --binding left    # force left binding everywhere

Requires Python 3.9+, Node 18+ and Playwright (Chromium). Output goes to
shopify-theme/print-files/.
"""

import argparse
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import drawings as D  # noqa: E402

FONTS = os.path.join(HERE, "fonts")
OUT_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "print-files"))
BUILD_DIR = os.path.join(OUT_DIR, "_build")

DPI = 96  # CSS px per inch (Chromium PDF output)
INK = "#111"
GREY = "#8A8A8A"

FONT_CSS = f"""
@font-face {{ font-family: 'Baloo'; src: url('file://{FONTS}/Baloo.ttf'); font-weight: 400 800; }}
@font-face {{ font-family: 'Cairo'; src: url('file://{FONTS}/Cairo.ttf'); font-weight: 200 1000; }}
.h {{ font-family: 'Baloo', 'Cairo', sans-serif; font-weight: 800; }}
.b {{ font-family: 'Cairo', sans-serif; font-weight: 700; }}
.r {{ font-family: 'Cairo', sans-serif; font-weight: 500; }}
.ar {{ font-family: 'Cairo', sans-serif; font-weight: 900; }}
.ghost * {{ fill: none !important; stroke: #9A9A9A !important; stroke-dasharray: 1 13; stroke-width: 10 !important; }}
"""


# ============================================================== geometry
class Geometry:
    """Page geometry in CSS px (96/in)."""

    def __init__(
        self, trim_w_in, trim_h_in, bleed_in=0.125, safe_in=0.5, gutter_in=0.25
    ):
        self.bleed = bleed_in * DPI
        self.w = (trim_w_in + 2 * bleed_in) * DPI
        self.h = (trim_h_in + 2 * bleed_in) * DPI
        self.safe = safe_in * DPI
        self.gutter = gutter_in * DPI
        self.content_w = self.w - 2 * self.bleed - 2 * self.safe - self.gutter
        self.content_h = self.h - 2 * self.bleed - 2 * self.safe
        self.page_w_in = trim_w_in + 2 * bleed_in
        self.page_h_in = trim_h_in + 2 * bleed_in

    def content_origin(self, page_no, binding):
        """Top-left of the safe content box for a 1-based page number.

        binding="symmetric" (default) splits the gutter evenly between both
        sides (0.5 + 0.125 = 0.625 in on letter books), so the same PDF works
        whether the printer binds on the left or on the right.
        """
        if binding == "symmetric":
            return self.bleed + self.safe + self.gutter / 2, self.bleed + self.safe
        odd = page_no % 2 == 1
        gutter_left = odd if binding == "left" else not odd
        x = self.bleed + self.safe + (self.gutter if gutter_left else 0)
        y = self.bleed + self.safe
        return x, y


LETTER = Geometry(8.5, 11)
POCKET = Geometry(4.25, 6.875, safe_in=0.375, gutter_in=0.125)
# Amazon KDP: exact trim size, no bleed (nothing in the books touches the edge)
KDP_GIFT = Geometry(6, 9, bleed_in=0, safe_in=0.5, gutter_in=0.25)


# ============================================================== text helpers
def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, t, size, cls="b", fill=INK, anchor="middle", rtl=False, extra=""):
    d = ' direction="rtl"' if rtl else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" font-size="{size}" text-anchor="{anchor}" fill="{fill}"{d} {extra}>{esc(t)}</text>'


def hollow(x, y, t, size, rtl=False, sw=6):
    """Outlined glyphs for coloring: white fill, black outline."""
    d = ' direction="rtl"' if rtl else ""
    cls = "ar" if rtl else "h"
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" font-size="{size}" text-anchor="middle"{d} '
        f'fill="#fff" stroke="{INK}" stroke-width="{sw}" stroke-linejoin="round">{esc(t)}</text>'
    )


def dotted(x, y, t, size, rtl=False):
    d = ' direction="rtl"' if rtl else ""
    cls = "ar" if rtl else "h"
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" font-size="{size}" text-anchor="middle"{d} '
        f'fill="none" stroke="#444" stroke-width="4" stroke-dasharray="0.1 9" stroke-linecap="round">{esc(t)}</text>'
    )


def model(x, y, t, size, rtl=False):
    d = ' direction="rtl"' if rtl else ""
    cls = "ar" if rtl else "h"
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" font-size="{size}" text-anchor="middle"{d} fill="#C9C9C9">{esc(t)}</text>'


def line(x1, y1, x2, y2, color="#CFCFCF", w=2, dash=None):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{w}"{da}/>'


def dotline(x1, x2, y):
    return line(x1, y, x2, y, "#555", 3, "0.1 10").replace(
        "/>", ' stroke-linecap="round"/>'
    )


# ============================================================== page wrappers
class Book:
    def __init__(self, slug, title, geometry, binding, lang):
        self.slug = slug
        self.title = title
        self.g = geometry
        self.binding = binding
        self.lang = lang  # "ar" or "en"
        self.pages = []  # list of (kind, inner_svg)

    def add(self, inner, kind="content"):
        self.pages.append((kind, inner))

    def add_with_back(self, inner):
        self.add(inner, "content")
        self.add(None, "back")

    # ---------------------------------------------------------- back page
    def back_page(self):
        g = self.g
        cw, ch = g.content_w, g.content_h
        msg_ar = "هذه الصفحة تُركت فارغة لحماية رسمتك التالية من تلطخ الألوان"
        scale = cw / 696
        out = (
            f'<rect x="0" y="0" width="{cw:.1f}" height="{ch:.1f}" rx="{24 * scale:.1f}" fill="none" stroke="#E4E4E4" stroke-width="2"/>'
            + text(cw / 2, ch * 0.47, "حروفي", 150 * scale, "h", "#F1F1F1", rtl=True)
            + text(cw / 2, ch * 0.47 + 60 * scale, "hroofy", 34 * scale, "h", "#F1F1F1")
        )
        out += text(
            cw / 2, ch - 70 * scale, msg_ar, 19 * scale, "r", "#BDBDBD", rtl=True
        )
        if self.lang == "en":
            out += text(
                cw / 2,
                ch - 40 * scale,
                "This page is left blank on purpose to protect your next drawing from bleed-through.",
                15 * scale,
                "r",
                "#C8C8C8",
            )
        return out

    # ---------------------------------------------------------- render
    def to_html(self):
        g = self.g
        body = []
        for i, (kind, inner) in enumerate(self.pages, start=1):
            x, y = g.content_origin(i, self.binding)
            content = self.back_page() if kind == "back" else inner
            num = ""
            if kind == "content" and i > 1:
                num = text(
                    g.content_w / 2,
                    g.content_h - 4,
                    str(i),
                    14 * g.content_w / 696,
                    "r",
                    "#9A9A9A",
                )
            body.append(
                f'<div class="p"><svg xmlns="http://www.w3.org/2000/svg" width="{g.w:.0f}" height="{g.h:.0f}" '
                f'viewBox="0 0 {g.w:.1f} {g.h:.1f}"><rect width="100%" height="100%" fill="#fff"/>'
                f'<g transform="translate({x:.1f} {y:.1f})">{content}{num}</g></svg></div>'
            )
        return f"""<!doctype html><html lang="{self.lang}"><head><meta charset="utf-8"><style>
{FONT_CSS}
@page {{ size: {g.page_w_in}in {g.page_h_in}in; margin: 0; }}
html, body {{ margin: 0; padding: 0; }}
.p {{ width: {g.w:.0f}px; height: {g.h:.0f}px; overflow: hidden; page-break-after: always; break-after: page; }}
.p:last-child {{ page-break-after: auto; break-after: auto; }}
svg {{ display: block; }}
</style></head><body>{''.join(body)}</body></html>"""


# ============================================================== shared pages
def decor_frame(cw, ch):
    """Hollow stars + crayons frame to color on ownership/certificate pages."""
    out = f'<rect x="10" y="10" width="{cw - 20:.1f}" height="{ch - 60:.1f}" rx="36" fill="none" stroke="{INK}" stroke-width="6"/>'
    out += f'<rect x="28" y="28" width="{cw - 56:.1f}" height="{ch - 96:.1f}" rx="26" fill="none" stroke="{INK}" stroke-width="2" stroke-dasharray="2 12" stroke-linecap="round"/>'
    for sx, sy in ((60, 60), (cw - 60, 60), (60, ch - 100), (cw - 60, ch - 100)):
        out += f'<polygon points="{D.star_points(sx, sy, 46)}" fill="#fff" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
    return out


def ownership_page(book, cw, ch, title_line, rtl):
    out = decor_frame(cw, ch)
    if rtl:
        out += hollow(cw / 2, 230, "هذا الكتاب ملك", 84, rtl=True)
        out += text(cw / 2, 330, "المبدع/ة:", 40, "b", rtl=True)
        out += dotline(110, cw - 110, 420)
        out += text(cw - 120, 520, "عمري:", 34, "b", anchor="start", rtl=True) + dotline(
            260, cw - 240, 520
        )
        out += text(160, 520, "سنوات", 34, "b", rtl=True)
        out += D.wrap("star", cw / 2 - 130, 560, 260)
        out += text(cw / 2, 860, title_line, 30, "h", rtl=True)
    else:
        out += hollow(cw / 2, 220, "This book", 84) + hollow(
            cw / 2, 320, "belongs to", 84
        )
        out += dotline(110, cw - 110, 430)
        out += text(cw / 2, 480, "هذا الكتاب ملك المبدع/ة", 26, "r", GREY, rtl=True)
        out += text(130, 560, "Age:", 34, "b", anchor="start") + dotline(
            230, cw - 130, 560
        )
        out += D.wrap("star", cw / 2 - 130, 590, 260)
        out += text(cw / 2, 860, title_line, 30, "h")
    return out


def certificate_page(cw, ch, book_title, rtl):
    out = decor_frame(cw, ch)
    # medal to color
    out += f'<path d="M{cw / 2 - 70} 390 L {cw / 2 - 110} 520 L {cw / 2 - 60} 500 L {cw / 2 - 40} 545 L {cw / 2 - 5} 420 Z" fill="#fff" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
    out += f'<path d="M{cw / 2 + 70} 390 L {cw / 2 + 110} 520 L {cw / 2 + 60} 500 L {cw / 2 + 40} 545 L {cw / 2 + 5} 420 Z" fill="#fff" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
    out += f'<circle cx="{cw / 2}" cy="330" r="95" fill="#fff" stroke="{INK}" stroke-width="6"/>'
    out += f'<polygon points="{D.star_points(cw / 2, 335, 60)}" fill="#fff" stroke="{INK}" stroke-width="5" stroke-linejoin="round"/>'
    if rtl:
        out += hollow(cw / 2, 170, "شهادة بطل حروفي", 58, rtl=True)
        out += text(cw / 2, 600, "نشهد بأن البطل/ة", 34, "b", rtl=True) + dotline(
            120, cw - 120, 665
        )
        out += text(
            cw / 2, 725, f"أكمل/ت {book_title} بنجاح وتفوّق!", 30, "b", rtl=True
        )
        out += text(
            cw - 125, 785, "توقيع ماما / بابا:", 24, "b", anchor="start", rtl=True
        ) + dotline(125, cw / 2 - 20, 785)
        out += text(
            cw - 125, 835, "التاريخ:", 24, "b", anchor="start", rtl=True
        ) + dotline(125, cw / 2 - 20, 835)
    else:
        out += hollow(cw / 2, 165, "Hroofy Hero", 76)
        out += text(cw / 2, 220, "Certificate", 34, "h")
        out += text(cw / 2, 600, "This certifies that", 32, "b") + dotline(
            120, cw - 120, 665
        )
        out += text(cw / 2, 725, f"completed {book_title}!", 30, "b")
        out += text(125, 785, "Signed by Mom / Dad:", 24, "b", anchor="start") + dotline(
            cw / 2 + 20, cw - 125, 785
        )
        out += text(125, 835, "Date:", 24, "b", anchor="start") + dotline(
            cw / 2 + 20, cw - 125, 835
        )
    return out


# ============================================================== Arabic book
AR_LETTERS = [
    ("أ", "الألف", "أَرْنَب", "rabbit"),
    ("ب", "الباء", "بَطَّة", "duck"),
    ("ت", "التاء", "تُفَّاحَة", "apple"),
    ("ث", "الثاء", "ثَعْلَب", "fox"),
    ("ج", "الجيم", "جَمَل", "camel"),
    ("ح", "الحاء", "حُوت", "whale"),
    ("خ", "الخاء", "خَرُوف", "sheep"),
    ("د", "الدال", "دُبّ", "bear"),
    ("ذ", "الذال", "ذُرَة", "corn"),
    ("ر", "الراء", "رُمَّانَة", "pomegranate"),
    ("ز", "الزاي", "زَرَافَة", "giraffe"),
    ("س", "السين", "سَمَكَة", "fish"),
    ("ش", "الشين", "شَمْس", "sun"),
    ("ص", "الصاد", "صَارُوخ", "rocket"),
    ("ض", "الضاد", "ضِفْدَع", "frog"),
    ("ط", "الطاء", "طَائِرَة", "airplane"),
    ("ظ", "الظاء", "ظَرْف", "envelope"),
    ("ع", "العين", "عُصْفُور", "bird"),
    ("غ", "الغين", "غَيْمَة", "cloud"),
    ("ف", "الفاء", "فَرَاشَة", "butterfly"),
    ("ق", "القاف", "قَمَر", "moon"),
    ("ك", "الكاف", "كُرَة", "ball"),
    ("ل", "اللام", "لَيْمُونَة", "lemon"),
    ("م", "الميم", "مَوْزَة", "banana"),
    ("ن", "النون", "نَجْمَة", "star"),
    ("ه", "الهاء", "هَدِيَّة", "gift"),
    ("و", "الواو", "وَرْدَة", "flower"),
    ("ي", "الياء", "يَد", "hand"),
]
NON_CONNECTING = set("اأإآدذرزوؤ")
AR_WIDE = set("سشصضغعقيى")  # glyphs that need a smaller display size
EN_WIDE = set("MWmw")


def ar_forms(c):
    if c in NON_CONNECTING:
        return [c, "ـ" + c]
    return [c + "ـ", "ـ" + c + "ـ", "ـ" + c]


def arabic_letter_page(letter, name, word, drawing, cw, ch):
    out = text(cw / 2, 34, f"حرف {name}", 26, "b", GREY, rtl=True)
    # big hollow letter (right) + drawing (left)
    big = 200 if letter in AR_WIDE else 255
    out += hollow(cw * 0.75, 285, letter, big, rtl=True, sw=7)
    out += D.wrap(drawing, 30, 70, 300)
    out += text(180, 430, word, 52, "h", rtl=True)
    forms = "   ".join(ar_forms(letter))
    out += text(cw * 0.75, 468, forms, 34, "b", "#666", rtl=True)
    out += line(20, 490, cw - 20, 490, "#D6D6D6", 2, "8 8")
    out += text(cw / 2, 535, "اتبع النقط واكتب الحرف بنفسك", 26, "b", "#555", rtl=True)
    for row, base in enumerate((690, 880)):
        out += line(20, base, cw - 20, base, "#BDBDBD", 2)
        out += line(20, base - 125, cw - 20, base - 125, "#E2E2E2", 2, "6 8")
        slots = (cw - 85, cw - 260, cw - 435, cw - 610) if letter in AR_WIDE else (cw - 70, cw - 205, cw - 340, cw - 475, cw - 610)
        for i, x in enumerate(slots):
            out += (model if (row == 0 and i == 0) else dotted)(x, base, letter, 105 if letter in AR_WIDE else 130, rtl=True)
    return out


def build_arabic(binding):
    b = Book(
        "arabic-alphabet-interior",
        "كتاب تلوين الحروف العربية",
        LETTER,
        binding or "symmetric",
        "ar",
    )
    cw, ch = b.g.content_w, b.g.content_h
    b.add_with_back(ownership_page(b, cw, ch, "كتاب الحروف العربية من أ إلى ي", True))
    for letter, name, word, drawing in AR_LETTERS:
        b.add_with_back(arabic_letter_page(letter, name, word, drawing, cw, ch))
    b.add_with_back(certificate_page(cw, ch, "كتاب الحروف العربية", True))
    return b


# ============================================================== English book
EN_LETTERS = [
    ("Apple", "apple"),
    ("Ball", "ball"),
    ("Cat", "cat"),
    ("Duck", "duck"),
    ("Egg", "egg"),
    ("Fish", "fish"),
    ("Gift", "gift"),
    ("House", "house"),
    ("Ice cream", "icecream"),
    ("Jellyfish", "jellyfish"),
    ("Kite", "kite"),
    ("Lemon", "lemon"),
    ("Moon", "moon"),
    ("Nest", "nest"),
    ("Orange", "orange"),
    ("Pizza", "pizza"),
    ("Quilt", "quilt"),
    ("Rocket", "rocket"),
    ("Sun", "sun"),
    ("Tree", "tree"),
    ("Umbrella", "umbrella"),
    ("Vase", "vase"),
    ("Whale", "whale"),
    ("Xylophone", "xylophone"),
    ("Yo-yo", "yoyo"),
    ("Zebra", "zebra"),
]


def english_letter_page(word, drawing, cw, ch):
    L = word[0]
    out = text(cw / 2, 34, f"Letter {L}", 26, "b", GREY)
    wide = L in EN_WIDE
    out += hollow(cw * 0.15, 330, L, 215 if wide else 280, sw=7) + hollow(cw * 0.37, 330, L.lower(), 175 if wide else 220, sw=7)
    out += D.wrap(drawing, cw - 330, 70, 300)
    word_size = 52 if len(word) <= 7 else 40
    out += text(cw - 180, 430, word, word_size, "h")
    out += text(cw * 0.26, 430, f"{L} is for {word}", 30, "b", "#666")
    out += line(20, 475, cw - 20, 475, "#D6D6D6", 2, "8 8")
    out += text(cw / 2, 525, "Trace the dots and write the letter", 26, "b", "#555")
    for row, (base, ch_) in enumerate(((690, L), (880, L.lower()))):
        out += line(20, base, cw - 20, base, "#BDBDBD", 2)  # baseline
        out += line(20, base - 92, cw - 20, base - 92, "#BDBDBD", 2)  # cap line
        out += line(20, base - 46, cw - 20, base - 46, "#E0E0E0", 2, "6 8")  # mid line
        slots = (85, 260, 435, 610) if L in EN_WIDE else (70, 205, 340, 475, 610)
        for i, x in enumerate(slots):
            out += (model if i == 0 else dotted)(x, base, ch_, 105 if ch_ in EN_WIDE else 130)
    return out


def build_english(binding):
    b = Book("english-alphabet-interior", "ABC Fun", LETTER, binding or "symmetric", "en")
    cw, ch = b.g.content_w, b.g.content_h
    b.add_with_back(ownership_page(b, cw, ch, "ABC Fun - Letters A to Z", False))
    for word, drawing in EN_LETTERS:
        b.add_with_back(english_letter_page(word, drawing, cw, ch))
    b.add_with_back(certificate_page(cw, ch, "ABC Fun", False))
    return b


# ============================================================== Numbers book
AR_NUM_WORDS = [
    "واحد",
    "اثنان",
    "ثلاثة",
    "أربعة",
    "خمسة",
    "ستة",
    "سبعة",
    "ثمانية",
    "تسعة",
    "عشرة",
    "أحد عشر",
    "اثنا عشر",
    "ثلاثة عشر",
    "أربعة عشر",
    "خمسة عشر",
    "ستة عشر",
    "سبعة عشر",
    "ثمانية عشر",
    "تسعة عشر",
    "عشرون",
]
EN_NUM_WORDS = [
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
    "Twenty",
]
COUNT_ICONS = [
    ("star", "نجوم", "نجمة"),
    ("apple", "تفاحات", "تفاحة"),
    ("fish", "سمكات", "سمكة"),
    ("ball", "كرات", "كرة"),
    ("flower", "وردات", "وردة"),
    ("heart", "قلوب", "قلب"),
]
INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def icon_grid(n, icon, x, y, size):
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    cell = size / max(cols, rows)
    out = ""
    for k in range(n):
        r, c = divmod(k, cols)
        ox = x + (size - cols * cell) / 2 + c * cell
        oy = y + (size - rows * cell) / 2 + r * cell
        out += D.wrap(
            icon,
            ox + cell * 0.08,
            oy + cell * 0.08,
            cell * 0.84,
            stroke=4.5 / (cell * 0.84 / 600),
        )
    return out


def number_page(n, cw, ch):
    icon, plural, single = COUNT_ICONS[(n - 1) % len(COUNT_ICONS)]
    out = text(cw / 2, 34, f"الرقم {n}", 26, "b", GREY, rtl=True)
    out += hollow(cw * 0.75, 320, str(n), 300 if n < 10 else 230, sw=7)
    out += text(
        cw * 0.75,
        410,
        f"{str(n).translate(INDIC)}  ·  {AR_NUM_WORDS[n - 1]}  ·  {EN_NUM_WORDS[n - 1]}",
        30,
        "b",
        "#555",
        rtl=True,
    )
    out += f'<rect x="30" y="70" width="300" height="300" rx="24" fill="none" stroke="#BDBDBD" stroke-width="3"/>'
    out += icon_grid(n, icon, 40, 80, 280)
    dual = {"star": "نجمتين", "apple": "تفاحتين", "fish": "سمكتين", "ball": "كرتين", "flower": "وردتين", "heart": "قلبين"}
    if n == 2:
        instr = f"عُدّ ولوّن {dual[icon]}"
    elif 3 <= n <= 10:
        instr = f"عُدّ ولوّن {n} {plural}"
    else:
        instr = f"عُدّ ولوّن {n} {single}"
    out += text(180, 420, instr, 30, "h", rtl=True)
    out += line(20, 475, cw - 20, 475, "#D6D6D6", 2, "8 8")
    out += text(cw / 2, 525, "اتبع النقط واكتب الرقم", 26, "b", "#555", rtl=True)
    s = str(n)
    xs = (70, 205, 340, 475, 610) if n < 10 else (90, 260, 430, 600)
    for row, base in enumerate((690, 880)):
        out += line(20, base, cw - 20, base, "#BDBDBD", 2)
        for i, x in enumerate(xs):
            out += (model if (row == 0 and i == 0) else dotted)(
                x, base, s, 130 if n < 10 else 115
            )
    return out


def answer_box(x, y, w=90, h=90):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h}" rx="14" fill="#fff" stroke="{INK}" stroke-width="4"/>'


def count_exercise(cw, ch, rows, title):
    out = hollow(cw / 2, 90, title, 60, rtl=True, sw=5)
    out += text(
        cw / 2,
        145,
        "عُدّ الأشكال ولوّنها.. واكتب العدد في المربع",
        24,
        "b",
        "#555",
        rtl=True,
    )
    for r, (icon, k) in enumerate(rows):
        y = 190 + r * 185
        out += f'<rect x="10" y="{y}" width="{cw - 20}" height="165" rx="22" fill="none" stroke="#D0D0D0" stroke-width="3"/>'
        for j in range(k):
            out += D.wrap(icon, cw - 150 - j * 92, y + 37, 90, stroke=4.5 / (90 / 600))
        out += answer_box(40, y + 37)
    return out


def add_exercise(cw, ch, rows, title, op="+"):
    out = hollow(cw / 2, 90, title, 60, rtl=True, sw=5)
    sub = (
        "اجمع الأشكال واكتب الناتج"
        if op == "+"
        else "اطرح الأشكال المشطوبة واكتب الباقي"
    )
    out += text(cw / 2, 145, sub, 24, "b", "#555", rtl=True)
    for r, (icon, a, b) in enumerate(rows):
        y = 190 + r * 185
        out += f'<rect x="10" y="{y}" width="{cw - 20}" height="165" rx="22" fill="none" stroke="#D0D0D0" stroke-width="3"/>'
        x = cw - 110
        for j in range(a):
            out += D.wrap(icon, x - j * 64, y + 54, 58, stroke=4.5 / (58 / 600))
            if op == "-" and j >= a - b:
                xx = x - j * 64
                out += f'<path d="M{xx + 4} {y + 54} L {xx + 54} {y + 108}" stroke="{INK}" stroke-width="5" stroke-linecap="round"/>'
        x -= a * 64 + 10
        if op == "+":
            out += text(x - 10, y + 100, "+", 56, "h", anchor="middle")
            x -= 60
            for j in range(b):
                out += D.wrap(
                    icon, x - j * 64 - 40, y + 54, 58, stroke=4.5 / (58 / 600)
                )
            x -= b * 64 + 40
        out += text(155, y + 100, "=", 56, "h")
        out += answer_box(40, y + 37)
        eq = f"{a} {op} {b} = ؟" if op == "+" else f"{a} - {b} = ؟"
        out += text(cw - 30, y + 155, eq, 22, "b", "#777", anchor="end")
    return out


def match_exercise(cw, ch):
    out = hollow(cw / 2, 90, "صِل الرقم بمجموعته", 60, rtl=True, sw=5)
    out += text(
        cw / 2,
        145,
        "ارسم خط من كل رقم للمجموعة اللي فيها نفس العدد",
        24,
        "b",
        "#555",
        rtl=True,
    )
    nums = [1, 2, 3, 4, 5]
    groups = [(3, "apple"), (5, "star"), (1, "fish"), (4, "heart"), (2, "ball")]
    for i, n in enumerate(nums):
        y = 200 + i * 150
        out += hollow(cw - 80, y + 95, str(n), 110, sw=5)
        out += f'<circle cx="{cw - 160}" cy="{y + 60}" r="10" fill="{INK}"/>'
        k, icon = groups[i]
        out += f'<circle cx="300" cy="{y + 60}" r="10" fill="{INK}"/>'
        for j in range(k):
            out += D.wrap(
                icon,
                250 - (j % 3) * 82 - 70,
                y + (j // 3) * 62 + 6,
                60 if k > 3 else 76,
                stroke=4.5 / ((60 if k > 3 else 76) / 600),
            )
    return out


def sequence_exercise(cw, ch):
    out = hollow(cw / 2, 90, "أكمل الأرقام الناقصة", 60, rtl=True, sw=5)
    out += text(cw / 2, 145, "اكتب الرقم الناقص في كل مربع", 24, "b", "#555", rtl=True)
    seqs = [
        [1, 2, None, 4, None],
        [None, 7, 8, None, 10],
        [11, None, 13, 14, None],
        [None, 17, None, 19, 20],
    ]
    for r, seq in enumerate(seqs):
        y = 220 + r * 180
        for i, v in enumerate(seq):
            x = 40 + i * 128
            if v is None:
                out += answer_box(x, y, 104, 104)
            else:
                out += hollow(x + 52, y + 90, str(v), 96 if v < 10 else 80, sw=5)
            if i < 4:
                out += f'<path d="M{x + 110} {y + 52} l 14 0" stroke="#999" stroke-width="4" stroke-linecap="round"/>'
    return out


def build_numbers(binding):
    b = Book(
        "numbers-math-interior",
        "كتاب الأرقام والحساب",
        LETTER,
        binding or "symmetric",
        "ar",
    )
    cw, ch = b.g.content_w, b.g.content_h
    b.add_with_back(ownership_page(b, cw, ch, "كتاب الأرقام والحساب من 1 إلى 20", True))
    for n in range(1, 21):
        b.add_with_back(number_page(n, cw, ch))
    b.add_with_back(
        count_exercise(
            cw, ch, [("star", 3), ("apple", 5), ("fish", 2), ("ball", 4)], "عُدّ واكتب"
        )
    )
    b.add_with_back(
        count_exercise(
            cw,
            ch,
            [("flower", 6), ("heart", 4), ("star", 5), ("apple", 3)],
            "عُدّ واكتب",
        )
    )
    b.add_with_back(
        add_exercise(
            cw,
            ch,
            [("apple", 2, 1), ("star", 3, 2), ("fish", 1, 3), ("ball", 2, 2)],
            "نجمع مع بعض",
        )
    )
    b.add_with_back(
        add_exercise(
            cw,
            ch,
            [("heart", 4, 1), ("star", 5, 2), ("apple", 3, 1), ("fish", 6, 3)],
            "نطرح ونشطب",
            "-",
        )
    )
    b.add_with_back(match_exercise(cw, ch))
    b.add_with_back(sequence_exercise(cw, ch))
    b.add_with_back(certificate_page(cw, ch, "كتاب الأرقام والحساب", True))
    return b


# ============================================================== Pocket gift booklet
GIFT_DRAWINGS = [
    ("نَجْمَة", "star"),
    ("سَمَكَة", "fish"),
    ("صَارُوخ", "rocket"),
    ("فَرَاشَة", "butterfly"),
    ("وَرْدَة", "flower"),
]


KDP_GIFT_DRAWINGS = GIFT_DRAWINGS + [
    ("قَمَر", "moon"),
    ("شَمْس", "sun"),
    ("بَيْت", "house"),
    ("قِطَّة", "cat"),
    ("تُفَّاحَة", "apple"),
]


def build_gift(binding):
    b = Book(
        "magic-pocket-gift-interior",
        "كتيب تلوين الجيب السحري",
        POCKET,
        binding or "symmetric",
        "ar",
    )
    cw, ch = b.g.content_w, b.g.content_h  # ~324 x 588
    title = (
        f'<rect x="4" y="4" width="{cw - 8:.1f}" height="{ch - 30:.1f}" rx="22" fill="none" stroke="{INK}" stroke-width="4"/>'
        + hollow(cw / 2, 110, "كتيب الجيب", 46, rtl=True, sw=4)
        + hollow(cw / 2, 170, "السحري", 52, rtl=True, sw=4)
        + D.wrap("gift", cw / 2 - 90, 190, 180, stroke=4 * 600 / 180)
        + text(cw / 2, 420, "هذا الكتيب ملك:", 22, "b", rtl=True)
        + dotline(30, cw - 30, 470)
        + text(cw / 2, 530, "هدية من حروفي", 18, "b", GREY, rtl=True)
    )
    b.add_with_back(title)
    for word, drawing in GIFT_DRAWINGS:
        page = (
            D.wrap(drawing, 12, 40, cw - 24, stroke=7 * 600 / (cw - 24))
            + text(cw / 2, cw + 80, word, 40, "h", rtl=True)
            + text(
                cw / 2, cw + 125, "لوّنها بألوانك المفضلة", 18, "b", "#666", rtl=True
            )
        )
        b.add_with_back(page)
    return b


def build_gift_kdp(binding):
    """KDP version of the pocket gift booklet: 6 x 9 in, 24 pages.

    ownership + 10 drawings + certificate, every sheet followed by a protected
    blank back (12 sheets x 2 = 24 pages, KDP's minimum for paperbacks).
    """
    b = Book(
        "magic-pocket-gift-interior",
        "كتيب تلوين الجيب السحري",
        KDP_GIFT,
        binding or "symmetric",
        "ar",
    )
    cw, ch = b.g.content_w, b.g.content_h  # 456 x 768 px
    base_w, base_h = 696.0, 960.0
    s = min(cw / base_w, ch / base_h)
    dy = (ch - base_h * s) / 2

    def scaled(inner):
        return f'<g transform="translate(0 {dy:.1f}) scale({s:.4f})">{inner}</g>'

    b.add_with_back(
        scaled(ownership_page(b, base_w, base_h, "هدية من حروفي", True))
    )
    for word, drawing in KDP_GIFT_DRAWINGS:
        page = (
            D.wrap(drawing, 12, 20, cw - 24, stroke=7 * 600 / (cw - 24))
            + text(cw / 2, cw + 90, word, 52, "h", rtl=True)
            + text(cw / 2, cw + 150, "لوّنها بألوانك المفضلة", 22, "b", "#666", rtl=True)
        )
        b.add_with_back(page)
    b.add_with_back(scaled(certificate_page(base_w, base_h, "كتيب الجيب السحري", True)))
    return b


# ============================================================== main
BUILDERS = {
    "arabic": build_arabic,
    "english": build_english,
    "numbers": build_numbers,
    "gift": build_gift,
}

import books_more  # noqa: E402

BUILDERS.update(books_more.build_extra(sys.modules[__name__]))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("books", nargs="*", help="arabic english numbers gift (default: all)")
    ap.add_argument(
        "--binding",
        choices=["symmetric", "left", "right"],
        help="gutter placement: symmetric (default, works for any binding), left or right",
    )
    ap.add_argument(
        "--target",
        choices=["lulu", "kdp"],
        default="lulu",
        help="kdp: exact-trim no-bleed 8.5x11 interiors + 6x9 gift into print-files/kdp/",
    )
    args = ap.parse_args()
    global OUT_DIR, BUILD_DIR, LETTER
    bleed = 0.125
    if args.target == "kdp":
        bleed = 0.0
        OUT_DIR = os.path.join(OUT_DIR, "kdp")
        BUILD_DIR = os.path.join(OUT_DIR, "_build")
        LETTER = Geometry(8.5, 11, bleed_in=0)
        BUILDERS["gift"] = build_gift_kdp
    unknown = [k for k in args.books if k not in BUILDERS]
    if unknown:
        ap.error(f"unknown book(s): {unknown}; choose from {list(BUILDERS)}")
    os.makedirs(BUILD_DIR, exist_ok=True)
    jobs = []
    for key in args.books or list(BUILDERS):
        book = BUILDERS[key](args.binding)
        html = os.path.join(BUILD_DIR, f"{book.slug}.html")
        with open(html, "w", encoding="utf-8") as f:
            f.write(book.to_html())
        jobs.append(
            {
                "html": html,
                "pdf": os.path.join(OUT_DIR, f"{book.slug}.pdf"),
                "width": f"{book.g.page_w_in}in",
                "height": f"{book.g.page_h_in}in",
                "pages": len(book.pages),
            }
        )
        print(
            f"built {book.slug}: {len(book.pages)} pages, {book.g.page_w_in} x {book.g.page_h_in} in, binding {book.binding}"
        )
    subprocess.run(
        ["node", os.path.join(HERE, "render_pdf.mjs"), json.dumps(jobs)], check=True
    )
    import pdf_boxes

    for job in jobs:
        pdf_boxes.normalise(job["pdf"], float(job["width"][:-2]), float(job["height"][:-2]), bleed)


if __name__ == "__main__":
    main()
