#!/usr/bin/env python3
"""Merge interior PDFs into single-volume bundle books for Lulu Direct.

Lulu Direct maps one Shopify variant to one print job, so a bundle that should
print as ONE book needs ONE interior PDF. This script concatenates the
interiors (pages, fonts, Trim/Bleed boxes are kept) and checks that every
source has the same page size.

    letters-bundle-interior.pdf = arabic-alphabet-interior.pdf (60)
                                + english-alphabet-interior.pdf (56)  -> 116 pages

Both books keep their own ownership page, back pages and certificate, so the
volume reads as two complete books bound together. The total stays even, as
Lulu requires.

Run generate_print_pdfs.py first, then:
    python3 merge_bundles.py
    python3 generate_print_covers.py letters_bundle
"""
import os
import sys

from pypdf import PdfReader, PdfWriter

HERE = os.path.dirname(os.path.abspath(__file__))
PRINT_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "print-files"))
if "--target" in sys.argv and sys.argv[sys.argv.index("--target") + 1] == "kdp":
    PRINT_DIR = os.path.join(PRINT_DIR, "kdp")

BUNDLES = {
    "letters-bundle-interior": ["arabic-alphabet-interior", "english-alphabet-interior"],
}


def merge(name, parts):
    writer = PdfWriter()
    size = None
    total = 0
    for part in parts:
        reader = PdfReader(os.path.join(PRINT_DIR, f"{part}.pdf"))
        for page in reader.pages:
            box = (round(float(page.mediabox.width), 2), round(float(page.mediabox.height), 2))
            if size is None:
                size = box
            elif box != size:
                sys.exit(f"{part}: page size {box} differs from {size}")
            writer.add_page(page)
        total += len(reader.pages)
    if total % 2:
        sys.exit(f"{name}: odd page count {total}")
    writer.add_metadata({"/Title": name, "/Author": "Hroofy"})
    out = os.path.join(PRINT_DIR, f"{name}.pdf")
    with open(out, "wb") as f:
        writer.write(f)
    print(f"{name}: {total} pages, {size[0] / 72:.3f} x {size[1] / 72:.3f} in <- {' + '.join(parts)}")


if __name__ == "__main__":
    for name, parts in BUNDLES.items():
        merge(name, parts)
