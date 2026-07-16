"""
Business logic tests — tax math, the discount cap fix, and a permanent
regression test for the exact dashboard bug we hit and fixed mid-project
(Jinja's `dict.items` colliding with a dict *key* literally named "items").
"""
import re

from app.tax import calc_canadian_tax, PROVINCE_TAX


def test_ontario_hst_is_a_single_13_percent_line():
    result = calc_canadian_tax(100.0, "ON")
    assert len(result["lines"]) == 1
    assert result["lines"][0]["amount"] == 13.00
    assert result["tax_total"] == 13.00
    assert result["total"] == 113.00


def test_bc_has_separate_gst_and_pst_lines():
    result = calc_canadian_tax(100.0, "BC")
    assert len(result["lines"]) == 2
    amounts = {l["label"].split(" ")[0]: l["amount"] for l in result["lines"]}
    assert amounts["GST"] == 5.00
    assert amounts["PST"] == 7.00
    assert result["tax_total"] == 12.00
    assert result["total"] == 112.00


def test_unknown_province_code_falls_back_to_ontario():
    result = calc_canadian_tax(100.0, "XX")
    assert result["total"] == calc_canadian_tax(100.0, "ON")["total"]


def test_every_province_total_equals_taxable_plus_tax(): # invariant that must always hold
    for province in PROVINCE_TAX:
        result = calc_canadian_tax(250.0, province)
        assert result["total"] == round(250.0 + result["tax_total"], 2), province


def test_zero_taxable_produces_zero_tax():
    result = calc_canadian_tax(0.0, "QC")
    assert result["tax_total"] == 0.0
    assert result["total"] == 0.0


def _first_active_product_id(db_session):
    from app.models import Product
    return db_session.query(Product).filter(Product.stock > 0).first().id


def test_dollar_discount_cannot_exceed_subtotal(owner_client, db_session):
    """Regression test for the discount-cap fix: a $500 manual discount on a
    $50 cart must not push the total negative — it should cap at $0.00."""
    product_id = _first_active_product_id(db_session)
    owner_client.post("/pos/clear")  # start from an empty cart
    owner_client.post("/pos/add-custom", data={"product_id": product_id, "custom_price": "50.00"})
    owner_client.post("/pos/discount", data={"mode": "$", "value": "500"})

    resp = owner_client.get("/pos")
    assert resp.status_code == 200
    match = re.search(r"Charge \$([\d.]+)", resp.text)
    assert match, "Could not find the Charge button total in the rendered POS page"
    total = float(match.group(1))
    assert total == 0.00, f"Expected total capped at $0.00, got ${total}"
    assert "$-" not in resp.text, "A negative dollar amount was rendered somewhere on the page"

    owner_client.post("/pos/clear")  # leave the cart clean for other tests


def test_percentage_discount_cannot_exceed_100(owner_client, db_session):
    product_id = _first_active_product_id(db_session)
    owner_client.post("/pos/clear")
    owner_client.post("/pos/add-custom", data={"product_id": product_id, "custom_price": "20.00"})
    owner_client.post("/pos/discount", data={"mode": "%", "value": "500"})  # 500%, should cap at 100%

    resp = owner_client.get("/pos")
    match = re.search(r"Charge \$([\d.]+)", resp.text)
    total = float(match.group(1))
    assert total == 0.00

    owner_client.post("/pos/clear")


def test_dashboard_renders_without_crashing(owner_client):
    """Regression test for the checklist dict-key-collision bug: the
    dashboard used to 500 with 'builtin_function_or_method object is not
    iterable' because a dict passed to the template had a key literally
    named 'items', which Jinja resolved to dict.items (the built-in method)
    instead of the actual data. This must never come back. (The bug wasn't
    tied to any particular data state, so this doesn't depend on running
    before or after any other test file.)"""
    resp = owner_client.get("/")
    assert resp.status_code == 200
    assert "builtin_function_or_method" not in resp.text
