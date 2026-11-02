#!/usr/bin/env python3
"""Pre-flight check for the Amazon KDP files in print-files/kdp/.

Interiors  : exact trim size (no bleed), >= 24 pages (>= 75 for hardcover), fonts
             embedded, ink >= 0.25 in from top/bottom/outside and >= 0.375 in from
             the gutter (KDP minimum for 24-150 pages; we test both sides because
             the files use symmetric margins).
Covers     : size = 2*trim + pages*0.002252 + 0.25 wide, trim + 0.25 high; spine
             text only when pages >= 79; barcode keep-out (2.0 x 1.2 in, bottom-right
             of the back panel, >= 0.25 in from trim and spine fold) is pure white.
Hardcover  : 2*trim + 0.8 hinge zone + 2*0.591 wrap; >= 75 pages.
Exit code 1 on any failure.
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
KDP = os.path.abspath(os.path.join(HERE, "..", "..", "print-files", "kdp"))
DPI = 48
PPI = 0.002252
MIN_OUTSIDE, MIN_GUTTER = 0.25, 0.375
TRIM = {"magic-pocket-gift-interior": (6, 9)}
FAILS = []


def info(path):
    out = subprocess.run(["pdfinfo", path], capture_output=True, text=True, check=True).stdout
    pages = int(re.search(r"Pages:\s+(\d+)", out).group(1))
    w, h = map(float, re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts", out).groups())
    return pages, w / 72, h / 72


def fonts_ok(path):
    rows = subprocess.run(["pdffonts", path], capture_output=True, text=True, check=True).stdout.splitlines()[2:]
    return all(r.split()[-5] == "yes" for r in rows if r.strip())


def report(name, errs, note):
    print(f"[{'OK ' if not errs else 'FAIL'}] {name}: {note}")
    for e in errs:
        print("       -", e)
    if errs:
        FAILS.append(name)


def check_interior(path, tmp, hardcover=False):
    slug = os.path.basename(path)[:-4]
    tw, th = TRIM.get(slug, (8.5, 11))
    pages, w, h = info(path)
    errs = []
    if abs(w - tw) > 0.005 or abs(h - th) > 0.005:
        errs.append(f"size {w:.3f}x{h:.3f} != trim {tw}x{th} (no-bleed)")
    if pages < 24:
        errs.append(f"{pages} pages < KDP minimum 24")
    if not fonts_ok(path):
        errs.append("fonts not embedded")
    prefix = os.path.join(tmp, slug)
    subprocess.run(["pdftoppm", "-r", str(DPI), "-png", path, prefix], check=True)
    worst = [9e9] * 4  # left, right, top, bottom in inches
    for png in sorted(glob.glob(prefix + "-*.png")):
        im = ImageOps.invert(Image.open(png).convert("L")).point(lambda v: 255 if v > 25 else 0)
        bb = im.getbbox()
        if not bb:
            continue
        W, H = im.size
        for i, v in enumerate((bb[0], W - bb[2], bb[1], H - bb[3])):
            worst[i] = min(worst[i], v / DPI)
    for name, v, need in (("left", worst[0], MIN_GUTTER), ("right", worst[1], MIN_GUTTER),
                          ("top", worst[2], MIN_OUTSIDE), ("bottom", worst[3], MIN_OUTSIDE)):
        if v + 1 / DPI < need:
            errs.append(f"ink {v:.3f} in from {name} edge < {need}")
    report(slug, errs, f"{pages} pages, {w:.3f} x {h:.3f} in, min ink margins L{worst[0]:.2f} R{worst[1]:.2f} T{worst[2]:.2f} B{worst[3]:.2f} in")


def check_covers(tmp):
    specs = json.load(open(os.path.join(KDP, "covers", "cover-specs.json")))
    for key, sp in specs.items():
        slug = {"arabic": "arabic-alphabet", "english": "english-alphabet", "numbers": "numbers-math",
                "animals": "animals-world", "space": "space-adventures", "creative": "draw-and-complete",
                "gift": "magic-pocket-gift", "letters_bundle": "letters-bundle"}[key]
        path = os.path.join(KDP, "covers", f"{slug}-cover.pdf")
        pages, w, h = info(path)
        tw, th = sp["trim"]
        spine = round(sp["pages"] * PPI, 4)
        errs = []
        if abs(w - (2 * tw + spine + 0.25)) > 0.01 or abs(h - (th + 0.25)) > 0.01:
            errs.append(f"size {w:.4f}x{h:.4f} != expected {2 * tw + spine + 0.25:.4f}x{th + 0.25:.4f}")
        if abs(sp["spine_in"] - spine) > 0.0005:
            errs.append(f"spine {sp['spine_in']} != pages*0.002252 = {spine}")
        if sp["spine_text"] != (sp["pages"] >= 79):
            errs.append("spine text rule violated (text only when pages >= 79)")
        # barcode zone: pure white in the real cover
        prefix = os.path.join(tmp, slug + "-cv")
        subprocess.run(["pdftoppm", "-r", str(DPI), "-png", "-singlefile", path, prefix], check=True)
        im = Image.open(prefix + ".png").convert("L")
        x1 = (0.125 + tw - 0.375) * DPI
        y1 = (h - 0.125 - 0.375) * DPI
        box = (round(x1 - 2.0 * DPI), round(y1 - 1.2 * DPI), round(x1), round(y1))
        if im.crop(box).getextrema()[0] < 250:
            errs.append("barcode keep-out zone is not white")
        # the box sits 0.375 in from the trim edge and the spine fold (KDP minimum 0.25 in)
        report(f"{slug}-cover", errs, f"{sp['pages']} pages, spine {spine:.4f} in, {w:.4f} x {h:.4f} in, spine text {'yes' if sp['spine_text'] else 'no'}")
    hc = os.path.join(KDP, "covers-hardcover", "letters-bundle-hardcover.pdf")
    if os.path.exists(hc):
        pages, w, h = info(hc)
        ipages = info(os.path.join(KDP, "letters-bundle-interior.pdf"))[0]
        errs = []
        if ipages < 75:
            errs.append("hardcover needs >= 75 pages")
        exp_w, exp_h = 2 * 8.5 + 0.8 + 2 * 0.591, 11 + 2 * 0.591
        if abs(w - exp_w) > 0.01 or abs(h - exp_h) > 0.01:
            errs.append(f"size {w:.4f}x{h:.4f} != {exp_w:.4f}x{exp_h:.4f}")
        report("letters-bundle-hardcover", errs, f"{ipages} pages, {w:.4f} x {h:.4f} in (wrap 0.591, spine 0.45, hinge zone 0.8)")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        for p in sorted(glob.glob(os.path.join(KDP, "*-interior.pdf"))):
            check_interior(p, tmp)
        check_covers(tmp)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
