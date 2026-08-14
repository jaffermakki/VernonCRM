"""
Server-side CODE128 barcode generation for the printable label sheet.

Earlier version generated barcodes client-side (JsBarcode, via CDN)
purely in the browser after page load. That works fine when someone is
looking at the page — but the moment the actual PRINT happens through
anything that doesn't execute JavaScript (a "Print to PDF" pipeline, a
dedicated label-printer app that fetches the URL and rasterizes it, an
older browser's print-render pass, or just bad timing where print fires
before the CDN script finishes loading), nothing ever draws the bars,
and the page silently falls back to "(barcode unavailable)" text for
every single label — which is exactly what happened.

Generating the SVG server-side and embedding it directly in the HTML
response fixes this categorically: the barcode is already fully-formed
markup by the time ANY renderer (browser, PDF exporter, label-printer
software) sees the page. Nothing needs to execute for it to appear.
"""

import io

import barcode
from barcode.writer import SVGWriter

_CODE128 = barcode.get_barcode_class("code128")

# CODE128 width grows with string length — a long SKU like
# "HARDRINGCASE-IPHONE17PROMAX-BLACK" (34 chars) is genuinely wider
# than a short one like "ABC123" at a fixed bar width. Rather than
# using one fixed module_width (which either wastes space on short
# SKUs or overflows/compresses illegibly on long ones), estimate the
# module count from the string and scale module_width to land near a
# consistent target physical width — while never going below a floor
# real-world barcode scanners can actually resolve.
_TARGET_WIDTH_MM = 42.0
_MIN_MODULE_WIDTH_MM = 0.15  # below this, cheap scanners start missing bars
_MAX_MODULE_WIDTH_MM = 0.32
_MODULE_HEIGHT_MM = 7.0


def _estimate_module_count(sku: str) -> int:
    # CODE128B: ~11 modules per data character, plus ~35 for the start
    # code, checksum, stop code, and quiet zones either side. Close
    # enough for sizing purposes — doesn't need to be exact, just
    # proportional, since the goal is consistent-looking labels, not a
    # precisely calculated physical width.
    return len(sku) * 11 + 35


def generate_barcode_svg(sku: str) -> tuple[str, float] | tuple[None, None]:
    """Returns (inline SVG markup, physical width in mm) for the given
    SKU, or (None, None) if CODE128 can't encode it. The width is
    returned alongside the SVG so the caller (the print template) can
    flag — on-screen only, never on the actual printed output — any
    label where the barcode had to be generated wider than the
    configured label size, since that's a real "this won't physically
    fit" signal staff need to see before printing a whole sheet."""
    if not sku:
        return None, None

    modules = _estimate_module_count(sku)
    module_width = max(_MIN_MODULE_WIDTH_MM, min(_MAX_MODULE_WIDTH_MM, _TARGET_WIDTH_MM / modules))
    width_mm = round(modules * module_width, 1)

    try:
        instance = _CODE128(sku, writer=SVGWriter())
        buf = io.BytesIO()
        instance.write(buf, options={
            "module_height": _MODULE_HEIGHT_MM,
            "module_width": module_width,
            "quiet_zone": 1.0,
            "font_size": 0,
            "text_distance": 0,
            "write_text": False,  # we render the SKU as our own styled text below the barcode instead
            "background": "white",
            "foreground": "black",
        })
        svg = buf.getvalue().decode("utf-8")
    except Exception:
        return None, None

    # Strip the XML/DOCTYPE preamble python-barcode includes — fine as
    # a standalone .svg file, but invalid to embed inline inside an
    # HTML document (only one DOCTYPE is allowed, and it must be the
    # page's own). Keep everything from the opening <svg> tag onward.
    svg_start = svg.find("<svg")
    if svg_start == -1:
        return None, None
    return svg[svg_start:], width_mm
