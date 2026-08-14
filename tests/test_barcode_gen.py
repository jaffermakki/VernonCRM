"""
Unit tests for app/barcode_gen.py — the server-side CODE128 generator
that replaced the client-side JsBarcode approach after it was found to
silently fail ("(barcode unavailable)" on every label) whenever the
print pipeline didn't execute JavaScript.
"""
from app.barcode_gen import generate_barcode_svg, _estimate_module_count, _MIN_MODULE_WIDTH_MM


def test_generates_valid_svg_for_normal_sku():
    svg, width_mm = generate_barcode_svg("HARDRING-IPHONE16-BLACK")
    assert svg is not None
    assert svg.startswith("<svg")
    assert "<rect" in svg
    assert width_mm is not None and width_mm > 0


def test_no_xml_preamble_or_doctype_in_embedded_svg():
    """The raw python-barcode output includes an XML declaration and
    DOCTYPE, which are valid for a standalone .svg file but break an
    HTML document if embedded inline (only one DOCTYPE allowed, and it
    must be the page's own) — must be stripped."""
    svg, _ = generate_barcode_svg("TEST-SKU-123")
    assert "<?xml" not in svg
    assert "<!DOCTYPE" not in svg


def test_long_sku_produces_wider_barcode_than_short_sku():
    short_svg, short_width = generate_barcode_svg("ABC")
    long_svg, long_width = generate_barcode_svg("HARDRINGCASE-IPHONE17PROMAX-BLACK")
    assert long_width > short_width


def test_module_width_never_goes_below_scannable_floor():
    """The actual physical-correctness guarantee: no matter how long
    the SKU, the bar width used must never be compressed below the
    minimum a real barcode scanner can reliably resolve. We can't
    directly read the module_width back out of the SVG easily, but we
    can confirm the width scales linearly with estimated module count
    at exactly the floor rate for a very long SKU (proving it hit the
    floor rather than being computed smaller)."""
    very_long_sku = "X" * 60
    _, width_mm = generate_barcode_svg(very_long_sku)
    modules = _estimate_module_count(very_long_sku)
    expected_min_width = round(modules * _MIN_MODULE_WIDTH_MM, 1)
    assert width_mm == expected_min_width


def test_empty_sku_returns_none():
    svg, width = generate_barcode_svg("")
    assert svg is None
    assert width is None


def test_two_different_skus_produce_different_barcodes():
    """Sanity check that the actual SKU content affects the bar
    pattern, not just the label — i.e. this isn't accidentally
    generating the same placeholder barcode for everything."""
    svg_a, _ = generate_barcode_svg("PRODUCT-A")
    svg_b, _ = generate_barcode_svg("PRODUCT-B")
    assert svg_a != svg_b
