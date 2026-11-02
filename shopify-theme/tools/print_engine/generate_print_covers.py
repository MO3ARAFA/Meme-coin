#!/usr/bin/env python3
"""Hroofy full-wrap print covers for Lulu (back + spine + front, with bleed).

Dimensions (inches):
    spine  = pages / PAGES_PER_INCH + SPINE_EXTRA      (perfect bound)
           = 0                                         (saddle stitch, e.g. the pocket gift)
    width  = 2 * trim_w + spine + 2 * BLEED
    height = trim_h + 2 * BLEED

The page count is read from the matching interior PDF in print-files/, so the
cover always follows the real book. PAGES_PER_INCH and SPINE_EXTRA default to
the formula 444 / 0.06; Lulu's spine width depends on the paper you choose, so
compare with the cover template Lulu shows for your project and pass
--pages-per-inch / --spine-extra if they differ.

Layout is left-to-right (Lulu): [bleed | back | spine | front | bleed].
Spine text is only added when the spine is at least 0.25 in wide.

Each cover is also rendered in an "ink only" mode (backgrounds removed) and
rasterised to verify that no text or artwork falls closer than SAFE_IN to a
trim edge or to the spine folds. Results print as OK / FAIL.

Amazon KDP (--target kdp, files go to print-files/kdp/):
    spine  = pages * 0.002252  (white paper; no Lulu +0.06)
    width  = 2 * trim_w + spine + 0.25,  height = trim_h + 0.25
    spine text only when pages >= 79; barcode keep-out 2.0 x 1.2 in bottom-right
    of the back cover, >= 0.25 in from the trim edge and from the spine fold.
    --hardcover with --target kdp builds the Case Laminate cover (letters bundle
    only): wrap 0.591, spine 0.45, total hinge zone 0.8 (all adjustable).

Usage:
    python3 generate_print_covers.py                    # all covers
    python3 generate_print_covers.py arabic gift        # some covers
"""

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import generate_print_pdfs as G  # noqa: E402

PRINT_DIR = G.OUT_DIR
COVER_DIR = os.path.join(PRINT_DIR, "covers")
BUILD_DIR = os.path.join(COVER_DIR, "_build")
DPI = 96
BLEED = 0.125
SAFE_IN = 0.375  # inside the trim, i.e. 0.5 in from the bleed edge
HC_WRAP = 0.75  # casewrap: board wrap on every side
HC_SPINE = 0.25  # casewrap spine for 24-84 pages
HC_HINGE = 0.5  # keep content this far from the spine folds on casewrap
HC_COVER_DIR = os.path.join(PRINT_DIR, "covers-hardcover")
INK = "#2B2D42"
KDP_PPI = 1 / 0.002252  # KDP paperback, white paper: spine = pages * 0.002252 in
KDP_HC_WRAP = 0.591
KDP_HC_SPINE = 0.45  # spine proper (text area)
KDP_HC_ZONE = 0.8  # spine + both hinges: distance between the two boards
KDP_SPINE_TEXT_MIN_PAGES = 79
KDP_HC_MIN_PAGES = 75
TARGET = "lulu"
SPINE_TEXT_W = None  # hardcover: width available for spine text


def load_cover_art():
    """Import the store-cover artwork functions (make_product_images.py runs as a script)."""
    saved = sys.argv
    tmp = tempfile.mkdtemp()
    sys.argv = [saved[0], os.path.join(HERE, "fonts"), tmp]
    try:
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            return importlib.import_module("make_product_images")
    finally:
        sys.argv = saved


ART = load_cover_art()

# key: interior slug, trim, binding, title, subtitle, age, color, spine color, art, blurb, features, thumbs
BOOKS = {
    "arabic": dict(
        slug="arabic-alphabet-interior",
        trim=(8.5, 11),
        bind="perfect",
        title="الحروف العربية",
        subtitle="من أ إلى ي · تلوين وتتبع",
        age="3-6",
        color="#FF6B4A",
        spine="#E2553A",
        art=ART.art_arabic,
        blurb=[
            "كتاب حروفي للحروف العربية بياخد طفلك في رحلة ممتعة",
            "عبر 28 حرف: لكل حرف رسمة وكلمة مشكولة",
            "وسطور تتبع بتقوّي إيده الصغيرة قبل الكتابة.",
        ],
        thumbs=(3, 15, 59),
    ),
    "english": dict(
        slug="english-alphabet-interior",
        trim=(8.5, 11),
        bind="perfect",
        title="ABC Fun",
        subtitle="الحروف الإنجليزية A-Z",
        age="3-6",
        color="#2EC4B6",
        spine="#22A69A",
        art=ART.art_english,
        blurb=[
            "ABC Fun بيعرّف طفلك على الحروف الإنجليزية الـ26",
            "بالحرف الكبير والصغير، مع كلمة ورسمة لكل حرف",
            "وسطور كتابة حقيقية للتتبع.",
        ],
        thumbs=(3, 25, 55),
    ),
    "numbers": dict(
        slug="numbers-math-interior",
        trim=(8.5, 11),
        bind="perfect",
        title="الأرقام والحساب",
        subtitle="لوّن وعدّ من 1 إلى 20",
        age="5-8",
        color="#5B8DEF",
        spine="#4374D6",
        art=ART.art_numbers,
        blurb=[
            "الأرقام من 1 لـ 20 بالعربي والإنجليزي،",
            "عدّ وتلوين، وتمارين جمع وطرح وصِل وأكمل",
            "بتخلّي الحساب لعبة ممتعة.",
        ],
        thumbs=(5, 43, 47),
    ),
    "animals": dict(
        slug="animals-world-interior",
        trim=(8.5, 11),
        bind="perfect",
        title="عالم الحيوانات",
        subtitle="24 حيوان مرح للتلوين",
        age="3-6",
        color="#7BD389",
        spine="#5DB86C",
        art=ART.art_animals,
        blurb=[
            "24 حيوان من الغابة والمزرعة والبحر،",
            "لكل حيوان اسمه بالعربي والإنجليزي",
            "ومعلومة «هل تعرف؟» بتفتح فضول طفلك.",
        ],
        thumbs=(3, 19, 37),
    ),
    "space": dict(
        slug="space-adventures-interior",
        trim=(8.5, 11),
        bind="perfect",
        title="الفضاء والمغامرات",
        subtitle="رحلة رواد الفضاء الصغار",
        age="5-9",
        color="#3D3B8E",
        spine="#2E2C70",
        art=ART.art_space,
        blurb=[
            "رحلة بين الكواكب والنجوم والصواريخ!",
            "22 صفحة تلوين بأسمائها بالعربي والإنجليزي",
            "ومعلومة علمية مبسطة في كل صفحة.",
        ],
        thumbs=(9, 23, 43),
    ),
    "creative": dict(
        slug="draw-and-complete-interior",
        trim=(8.5, 11),
        bind="perfect",
        title="ارسم وأكمل",
        subtitle="الرسم الإبداعي للفنانين الصغار",
        age="5-10",
        color="#A66CFF",
        spine="#8B4FE8",
        art=ART.art_creative,
        blurb=[
            "نص الرسمة علينا.. والنص التاني من خيال طفلك!",
            "صفحات تماثل على شبكة مربعات، واتبع النقط،",
            "وصفحات رسم حر بتطلق إبداعه.",
        ],
        thumbs=(3, 37, 43),
    ),
    "gift": dict(
        slug="magic-pocket-gift-interior",
        trim=(4.25, 6.875),
        bind="saddle",
        title="كتيب الجيب السحري",
        subtitle="5 رسمات بحجم الجيب",
        age="3-9",
        color="#FF8FB1",
        spine="#F06D96",
        art=ART.art_gift,
        blurb=["كتيب تلوين صغير بحجم الجيب", "بيرافق طفلك في كل مكان."],
        thumbs=(3, 5, 7),
    ),
}


def _letters_bundle_book():
    ar = G.BUILDERS["arabic"](None)
    ar.pages = ar.pages + G.BUILDERS["english"](None).pages
    return ar


def _letters_bundle_art():
    left = f'<g transform="translate(105 364.5) scale(0.55)">{ART.art_arabic()}</g>'
    right = f'<g transform="translate(595 364.5) scale(0.55)">{ART.art_english()}</g>'
    return left + right


BOOKS["letters_bundle"] = dict(
    slug="letters-bundle-interior", trim=(8.5, 11), bind="perfect", title="باقة الحروف",
    subtitle="عربي + إنجليزي في مجلد واحد", age="3-6", color="#FF6B4A", spine="#E2553A",
    art=_letters_bundle_art, book=_letters_bundle_book,
    blurb=["الحروف العربية من أ إلى ي، والحروف الإنجليزية A-Z،", "في مجلد واحد فيه 116 صفحة.",
           "لكل حرف رسمة وكلمة وسطور تتبع."], thumbs=(3, 63, 115))

FEATURES = "رسومات على وجه واحد · خطوط عريضة للإيد الصغيرة · شهادة إنجاز في الآخر"
FEATURES_GIFT = "رسومات على وجه واحد · هدية من حروفي"


def kdp_book(key):
    """KDP variant of a BOOKS entry (the pocket gift becomes a 6 x 9 perfect-bound book)."""
    b = dict(BOOKS[key])
    if key == "gift":
        b.update(trim=(6, 9), bind="perfect", subtitle="10 رسمات + شهادة", thumbs=(3, 5, 7),
                 blurb=["كتيب تلوين صغير لطفلك", "10 رسمات وشهادة إنجاز."])
    return b


def pdf_pages(path):
    out = subprocess.run(
        ["pdfinfo", path], capture_output=True, text=True, check=True
    ).stdout
    return int(re.search(r"Pages:\s+(\d+)", out).group(1))


def tint(hex_color, amount=0.82):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    mix = lambda c: round(c + (255 - c) * amount)  # noqa: E731
    return f"#{mix(r):02X}{mix(g):02X}{mix(b):02X}"


def design_transform(pw, ph):
    """Map the 816x1056 design (content kept inside 48..768 x 48..1008) into a panel."""
    margin = 0.42 * DPI
    s = min(1.0, (pw - 2 * margin) / 720, (ph - 2 * margin) / 960)
    ox = pw / 2 - 408 * s
    oy = ph / 2 - 528 * s
    return f"translate({ox:.2f} {oy:.2f}) scale({s:.4f})"


def t(x, y, s, size, cls="b", fill=INK, rtl=True, anchor="middle", extra=""):
    d = ' direction="rtl"' if rtl else ""
    return f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}" text-anchor="{anchor}" fill="{fill}"{d} {extra}>{G.esc(s)}</text>'


def front_design(b):
    s = (
        640 / 980
    )  # store-cover art card (300..1280 x 400..1220) -> (88..728 x 170..705)
    art = f'<g transform="translate({88 - 300 * s:.2f} {170 - 400 * s:.2f}) scale({s:.4f})">{b["art"]()}</g>'
    title_size = 92 if len(b["title"]) <= 12 else 78
    return (
        f'<rect x="88" y="66" width="230" height="74" rx="37" fill="#fff"/>'
        + t(203, 118, "حروفي", 46, "h")
        + f'<circle cx="680" cy="104" r="62" fill="#FFD23F" stroke="{INK}" stroke-width="5"/>'
        + t(680, 102, b["age"], 32, "h", rtl=False)
        + t(680, 136, "سنوات", 22, "b")
        + f'<rect x="88" y="170" width="640" height="535" rx="40" fill="#fff" stroke="{INK}" stroke-width="7"/>'
        + f'<clipPath id="artclip"><rect x="88" y="170" width="640" height="535" rx="40"/></clipPath>'
        + f'<g clip-path="url(#artclip)">{art}</g>'
        + t(
            408,
            815,
            b["title"],
            title_size,
            "h",
            "#fff",
            extra=f'stroke="{INK}" stroke-width="12" paint-order="stroke" stroke-linejoin="round"',
        )
        + t(408, 885, b["subtitle"], 36, "b", "#fff")
        + f'<rect x="188" y="925" width="440" height="68" rx="34" fill="{INK}"/>'
        + t(408, 970, "كتاب تلوين تعليمي", 30, "b", "#fff")
    )


def back_design(b, book):
    cw, ch = book.g.content_w, book.g.content_h
    thumbs = ""
    tw = min(200, 300 * cw / ch)
    th = tw * ch / cw
    for i, (pno, rot) in enumerate(zip(b["thumbs"], (-4, 0, 4))):
        kind, inner = book.pages[pno - 1]
        x = 88 + i * 220
        thumbs += (
            f'<g transform="rotate({rot} {x + tw / 2} {400 + th / 2})">'
            f'<rect x="{x - 8}" y="392" width="{tw + 16}" height="{th + 16}" rx="10" fill="#fff" stroke="{INK}" stroke-width="3"/>'
            f'<svg x="{x}" y="400" width="{tw}" height="{th:.1f}" viewBox="0 0 {cw:.1f} {ch:.1f}">'
            f'<rect width="100%" height="100%" fill="#fff"/>{inner}</svg></g>'
        )
    blurb = "".join(
        t(408, 260 + i * 44, ln, 26, "b") for i, ln in enumerate(b["blurb"])
    )
    feats = FEATURES_GIFT if b["slug"].startswith("magic-pocket") else FEATURES
    return (
        t(408, 120, "حروفي", 70, "h")
        + t(408, 175, "لوّن.. تعلّم.. ابدع", 30, "b", "#5B5F7A")
        + blurb
        + thumbs
        + t(408, 740, feats, 22, "b")
        + t(408, 785, f"مناسب للأطفال من {b['age'].split('-')[0]} إلى {b['age'].split('-')[1]} سنوات", 24, "h")
        + t(60, 1000, "hroofy", 22, "h", "#5B5F7A", rtl=False, anchor="start")
        + t(60, 970, "يُطبع عند الطلب", 18, "b", "#5B5F7A", anchor="end")
    )


def hardcover_spine(pages, override=None):
    """Lulu casewrap spine: fixed 0.25 in for 24-84 pages unless overridden.

    KDP case laminate: returns the whole spine+hinge zone (0.8 in by default)."""
    if TARGET == "kdp":
        if pages < KDP_HC_MIN_PAGES:
            raise ValueError(f"{pages} pages: KDP hardcover needs at least {KDP_HC_MIN_PAGES}")
        return override if override is not None else KDP_HC_ZONE
    if override is not None:
        return override
    if 24 <= pages <= 84:
        return HC_SPINE
    raise ValueError(f"{pages} pages is outside the 24-84 range of the fixed 0.25 in casewrap spine; "
                     "pass --hardcover-spine with the width Lulu shows for this book")


def build_cover(key, ppi, extra, ink_only=False, hardcover=False, hc_spine=None):
    b = kdp_book(key) if TARGET == "kdp" else BOOKS[key]
    pages = pdf_pages(os.path.join(PRINT_DIR, f"{b['slug']}.pdf"))
    tw_in, th_in = b["trim"]
    if hardcover:
        margin = KDP_HC_WRAP if TARGET == "kdp" else HC_WRAP
        spine_in = hardcover_spine(pages, hc_spine)
    else:
        margin = BLEED
        spine_in = 0.0 if b["bind"] == "saddle" else pages / ppi + extra
    W_in = 2 * tw_in + spine_in + 2 * margin
    H_in = th_in + 2 * margin
    W, H = W_in * DPI, H_in * DPI
    bl, pw, ph, sp = margin * DPI, tw_in * DPI, th_in * DPI, spine_in * DPI
    back_x, spine_x, front_x = bl, bl + pw, bl + pw + sp

    book = b["book"]() if "book" in b else G.BUILDERS[key](None)
    bg = "#FFFFFF" if ink_only else None
    back_bg = bg or tint(b["color"])
    front_bg = bg or b["color"]
    spine_bg = bg or b["spine"]

    # barcode keep-out: 2 x 1.2 in, bottom-right of the back panel, inside the safe area
    bw, bh = 2.0 * DPI, 1.2 * DPI
    bx = back_x + pw - SAFE_IN * DPI - bw
    by = bl + ph - SAFE_IN * DPI - bh
    if b["bind"] == "saddle":
        bw, bh = 1.6 * DPI, 1.0 * DPI
        bx = back_x + pw - SAFE_IN * DPI - bw
        by = bl + ph - SAFE_IN * DPI - bh

    spine_text = ""
    if TARGET == "kdp":
        show_text = pages >= KDP_SPINE_TEXT_MIN_PAGES and not ink_only
        text_w = (KDP_HC_SPINE if hardcover else spine_in) * DPI
    else:
        show_text = spine_in >= 0.25 and not ink_only
        text_w = sp
    if show_text:
        spine_text = (
            f'<g transform="translate({spine_x + sp / 2:.1f} {H / 2:.1f}) rotate(90)">'
            + t(0, text_w * 0.18, f"حروفي · {b['title']}", min(24, text_w * 0.45), "h", "#fff")
            + "</g>"
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.1f}" height="{H:.1f}" viewBox="0 0 {W:.1f} {H:.1f}">'
        f'<rect class="bgfill" x="0" y="0" width="{spine_x:.1f}" height="{H:.1f}" fill="{back_bg}"/>'
        f'<rect class="bgfill" x="{spine_x:.1f}" y="0" width="{sp + 0.5:.1f}" height="{H:.1f}" fill="{spine_bg}"/>'
        f'<rect class="bgfill" x="{front_x:.1f}" y="0" width="{W - front_x:.1f}" height="{H:.1f}" fill="{front_bg}"/>'
        f'<g transform="translate({back_x:.1f} {bl:.1f})"><g transform="{design_transform(pw, ph)}">{back_design(b, book)}</g></g>'
        f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="#FFFFFF"/>'
        f'<g transform="translate({front_x:.1f} {bl:.1f})"><g transform="{design_transform(pw, ph)}">{front_design(b)}</g></g>'
        f"{spine_text}</svg>"
    )
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
{G.FONT_CSS}
@page {{ size: {W_in:.4f}in {H_in:.4f}in; margin: 0; }}
html, body {{ margin: 0; padding: 0; }}
svg {{ display: block; }}
{"text { fill: #000 !important; }" if ink_only else ""}
</style></head><body>{svg}</body></html>"""
    info = dict(
        key=key,
        pages=pages,
        spine_in=round(spine_in, 4),
        width_in=round(W_in, 4),
        height_in=round(H_in, 4),
        trim=(tw_in, th_in),
        bind="casewrap" if hardcover else b["bind"],
        margin=margin,
        hinge=HC_HINGE if hardcover else SAFE_IN,
        spine_text=(pages >= KDP_SPINE_TEXT_MIN_PAGES) if TARGET == "kdp" else spine_in >= 0.25,
        barcode=(bx, by, bw, bh),
    )
    return html, info


def render(jobs):
    subprocess.run(
        ["node", os.path.join(HERE, "render_pdf.mjs"), json.dumps(jobs)],
        check=True,
        capture_output=True,
    )


def check_ink(pdf, info, tmp):
    """Rasterise the ink-only cover; every panel's ink must stay inside its safe box."""
    dpi = 48
    prefix = os.path.join(tmp, info["key"] + "-ink")
    subprocess.run(
        ["pdftoppm", "-r", str(dpi), "-png", "-singlefile", pdf, prefix],
        check=True,
        capture_output=True,
    )
    im = ImageOps.invert(Image.open(prefix + ".png").convert("L")).point(
        lambda v: 255 if v > 25 else 0
    )
    tw, th = info["trim"]
    sp = info["spine_in"]
    safe = SAFE_IN
    m = info["margin"]
    hinge = info["hinge"]
    panels = {"back": m, "front": m + tw + sp}
    errors = []
    for name, x_in in panels.items():
        box = (round(x_in * dpi), 0, round((x_in + tw) * dpi), im.size[1])
        crop = im.crop(box)
        bb = crop.getbbox()
        if not bb:
            errors.append(f"{name}: empty panel")
            continue
        left_safe, right_safe = (safe, hinge) if name == "back" else (hinge, safe)
        lim = (
            left_safe * dpi,
            (m + safe) * dpi,
            (tw - right_safe) * dpi,
            (m + th - safe) * dpi,
        )
        if (
            bb[0] < lim[0] - 2
            or bb[1] < lim[1] - 2
            or bb[2] > lim[2] + 2
            or bb[3] > lim[3] + 2
        ):
            errors.append(
                f"{name}: ink {bb} outside safe box {tuple(round(v) for v in lim)}"
            )
    return errors


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "books", nargs="*", help=f"one or more of {list(BOOKS)} (default: all)"
    )
    ap.add_argument("--target", choices=["lulu", "kdp"], default="lulu")
    ap.add_argument("--pages-per-inch", type=float, default=None)
    ap.add_argument("--spine-extra", type=float, default=None)
    ap.add_argument("--hardcover", action="store_true", help="Lulu casewrap covers (0.75 in wrap, fixed spine) into covers-hardcover/")
    ap.add_argument("--hardcover-spine", type=float, default=None, help="casewrap spine width in inches (default: 0.25 for 24-84 pages)")
    args = ap.parse_args()
    global TARGET, PRINT_DIR, COVER_DIR, HC_COVER_DIR, HC_WRAP, HC_HINGE
    if args.target == "kdp":
        TARGET = "kdp"
        PRINT_DIR = os.path.join(G.OUT_DIR, "kdp")
        COVER_DIR = os.path.join(PRINT_DIR, "covers")
        HC_COVER_DIR = os.path.join(PRINT_DIR, "covers-hardcover")
        G.LETTER = G.Geometry(8.5, 11, bleed_in=0)
        G.BUILDERS["gift"] = G.build_gift_kdp
        if args.pages_per_inch is None:
            args.pages_per_inch = KDP_PPI
        if args.spine_extra is None:
            args.spine_extra = 0.0
        if args.hardcover and not args.books:
            args.books = ["letters_bundle"]  # KDP hardcover min 75 pages: only the 116-page bundle
        if args.hardcover and any(k != "letters_bundle" for k in args.books):
            ap.error("KDP hardcover is only offered for letters_bundle (min 75 pages)")
    if args.pages_per_inch is None:
        args.pages_per_inch = 444.0
    if args.spine_extra is None:
        args.spine_extra = 0.06
    keys = args.books or [k for k in BOOKS if not (args.hardcover and BOOKS[k]["bind"] == "saddle")]
    out_dir = HC_COVER_DIR if args.hardcover else COVER_DIR
    build_dir = os.path.join(out_dir, "_build")
    bad = [k for k in keys if k not in BOOKS]
    if bad:
        ap.error(f"unknown: {bad}")
    os.makedirs(build_dir, exist_ok=True)
    jobs, ink_jobs, infos = [], [], {}
    for key in list(keys):
        if args.hardcover and TARGET != "kdp" and BOOKS[key]["bind"] == "saddle":
            print(f"[SKIP] {key}: saddle-stitch books have no casewrap edition")
            keys.remove(key)
            continue
        if args.hardcover:
            try:
                hardcover_spine(pdf_pages(os.path.join(PRINT_DIR, BOOKS[key]["slug"] + ".pdf")), args.hardcover_spine)
            except ValueError as e:
                print(f"[SKIP] {key}: {e}")
                keys.remove(key)
                continue
        slug = BOOKS[key]["slug"].replace("-interior", "-hardcover" if args.hardcover else "-cover")
        for ink in (False, True):
            html, info = build_cover(
                key, args.pages_per_inch, args.spine_extra, ink_only=ink,
                hardcover=args.hardcover, hc_spine=args.hardcover_spine,
            )
            hp = os.path.join(build_dir, f"{slug}{'-ink' if ink else ''}.html")
            with open(hp, "w", encoding="utf-8") as f:
                f.write(html)
            pdf = os.path.join(
                build_dir if ink else out_dir, f"{slug}{'-ink' if ink else ''}.pdf"
            )
            job = {
                "html": hp,
                "pdf": pdf,
                "width": f"{info['width_in']}in",
                "height": f"{info['height_in']}in",
                "pages": 1,
            }
            (ink_jobs if ink else jobs).append(job)
            infos[key] = info
    render(jobs + ink_jobs)
    import pdf_boxes

    for job in jobs:
        pdf_boxes.normalise(job["pdf"], float(job["width"][:-2]), float(job["height"][:-2]),
                            bleed_in=(KDP_HC_WRAP if TARGET == "kdp" else HC_WRAP) if args.hardcover else BLEED)

    failed = False
    with tempfile.TemporaryDirectory() as tmp:
        for key, job in zip(keys, ink_jobs):
            info = infos[key]
            errors = check_ink(job["pdf"], info, tmp)
            failed |= bool(errors)
            print(
                f"[{'OK ' if not errors else 'FAIL'}] {key}: {info['pages']} pages, {info['bind']}, "
                f"spine {info['spine_in']:.4f} in, cover {info['width_in']:.4f} x {info['height_in']:.4f} in"
            )
            for e in errors:
                print("       -", e)
    preview_dir = os.path.join(out_dir, "_preview")
    os.makedirs(preview_dir, exist_ok=True)
    for job in jobs:
        out = os.path.join(
            preview_dir, os.path.basename(job["pdf"]).replace(".pdf", "")
        )
        subprocess.run(
            ["pdftoppm", "-r", "40", "-png", "-singlefile", job["pdf"], out],
            check=True,
            capture_output=True,
        )
    specs_path = os.path.join(out_dir, "cover-specs.json")
    specs = {}
    if os.path.exists(specs_path):  # merge, so building one book keeps the others' entries
        with open(specs_path) as f:
            specs = json.load(f)
    specs.update({k: {kk: v for kk, v in i.items() if kk != "barcode"} for k, i in infos.items()})
    with open(specs_path, "w") as f:
        json.dump(specs, f, indent=2)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
