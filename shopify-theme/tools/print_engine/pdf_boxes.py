"""Normalise rendered PDFs to exact print dimensions and set Trim/Bleed boxes.

Chromium rounds page sizes slightly (up to ~0.006 in). Printers check the
exact size, so every page is scaled to the exact MediaBox and gets a TrimBox
(inset by the bleed) and a BleedBox (= MediaBox).
"""
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject


def normalise(path, width_in, height_in, bleed_in=0.125):  # bleed_in = casewrap wrap on hardcover covers
    w, h, b = width_in * 72, height_in * 72, bleed_in * 72
    reader = PdfReader(path)
    writer = PdfWriter()
    for page in reader.pages:
        page.scale_to(w, h)
        page.mediabox = RectangleObject([0, 0, w, h])
        page.cropbox = RectangleObject([0, 0, w, h])
        page.bleedbox = RectangleObject([0, 0, w, h])
        page.trimbox = RectangleObject([b, b, w - b, h - b])
        writer.add_page(page)
    writer.add_metadata({"/Title": path.rsplit("/", 1)[-1].replace(".pdf", ""), "/Author": "Hroofy"})
    with open(path, "wb") as f:
        writer.write(f)
