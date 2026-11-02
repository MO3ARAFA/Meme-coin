#!/usr/bin/env python3
"""Pre-flight check for the Hroofy interior PDFs.

For every PDF in print-files/ it verifies:
  * page size (trim + 0.125 in bleed) and an even page count;
  * that all fonts are embedded;
  * that no ink falls outside the safe area (0.5 in inside the trim, plus the
    gutter on the binding edge), by rasterising every page with pdftoppm.
It also writes preview sheets (first 4 + last 2 pages) to print-files/_preview/.

Requires poppler-utils (pdfinfo, pdffonts, pdftoppm) and Pillow.
Exit code 1 if any check fails.
"""

import glob
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
PRINT_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "print-files"))
PREVIEW_DIR = os.path.join(PRINT_DIR, "_preview")

# slug: (trim_w_in, trim_h_in, safe_in, gutter_in, binding)
SPEC = {
    "arabic-alphabet-interior": (8.5, 11, 0.5, 0.25, "right"),
    "english-alphabet-interior": (8.5, 11, 0.5, 0.25, "left"),
    "numbers-math-interior": (8.5, 11, 0.5, 0.25, "right"),
    "magic-pocket-gift-interior": (4.25, 6.875, 0.375, 0.125, "right"),
}
BLEED = 0.125
DPI = 48
TOL_PX = 2


def pdfinfo(path):
    out = subprocess.run(
        ["pdfinfo", path], capture_output=True, text=True, check=True
    ).stdout
    pages = int(re.search(r"Pages:\s+(\d+)", out).group(1))
    w, h = map(float, re.search(r"Page size:\s+([\d.]+) x ([\d.]+) pts", out).groups())
    return pages, w / 72, h / 72


def fonts_embedded(path):
    out = subprocess.run(
        ["pdffonts", path], capture_output=True, text=True, check=True
    ).stdout.splitlines()[2:]
    return all(line.split()[-5] == "yes" for line in out if line.strip())


def check(slug, spec, tmp):
    tw, th, safe, gutter, binding = spec
    path = os.path.join(PRINT_DIR, f"{slug}.pdf")
    errors = []
    pages, w, h = pdfinfo(path)
    if abs(w - (tw + 2 * BLEED)) > 0.01 or abs(h - (th + 2 * BLEED)) > 0.01:
        errors.append(
            f"page size {w:.3f} x {h:.3f} in, expected {tw + 2 * BLEED} x {th + 2 * BLEED}"
        )
    if pages % 2:
        errors.append(f"odd page count {pages}")
    if not fonts_embedded(path):
        errors.append("not all fonts embedded")

    prefix = os.path.join(tmp, slug)
    subprocess.run(
        ["pdftoppm", "-r", str(DPI), "-png", path, prefix],
        check=True,
        capture_output=True,
    )
    files = sorted(
        glob.glob(prefix + "-*.png"),
        key=lambda p: int(re.search(r"-(\d+)\.png$", p).group(1)),
    )
    for f in files:
        n = int(re.search(r"-(\d+)\.png$", f).group(1))
        im = Image.open(f).convert("L")
        W, H = im.size
        box = ImageOps.invert(im).point(lambda v: 255 if v > 25 else 0).getbbox()
        if not box:
            continue
        odd = n % 2 == 1
        gutter_left = odd if binding == "left" else not odd
        b = BLEED * DPI
        left = b + safe * DPI + (gutter * DPI if gutter_left else 0)
        right = W - b - safe * DPI - (0 if gutter_left else gutter * DPI)
        top, bottom = b + safe * DPI, H - b - safe * DPI
        if (
            box[0] < left - TOL_PX
            or box[1] < top - TOL_PX
            or box[2] > right + TOL_PX
            or box[3] > bottom + TOL_PX
        ):
            errors.append(
                f"page {n}: ink {box} outside safe area {(round(left), round(top), round(right), round(bottom))}"
            )

    pick = files[:4] + files[-2:]
    thumbs = [Image.open(f).convert("RGB") for f in pick]
    tw_px, th_px = thumbs[0].size
    sheet = Image.new("RGB", (len(thumbs) * (tw_px + 10) + 10, th_px + 20), "#9a9a9a")
    for i, t in enumerate(thumbs):
        sheet.paste(t, (10 + i * (tw_px + 10), 10))
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    sheet.save(os.path.join(PREVIEW_DIR, f"{slug}-first-last.png"))
    return pages, errors


def main():
    failed = False
    with tempfile.TemporaryDirectory() as tmp:
        for slug, spec in SPEC.items():
            pages, errors = check(slug, spec, tmp)
            status = "OK " if not errors else "FAIL"
            print(f"[{status}] {slug}: {pages} pages")
            for e in errors:
                print("       -", e)
            failed |= bool(errors)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
