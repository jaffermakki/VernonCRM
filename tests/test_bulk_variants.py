"""
Tests for the bulk case-variant generator — the tool that creates many
phone-brand/model/color SKUs of one case style in a single pass, instead
of adding them one at a time through the regular Add Product form.
"""
from app.models import Product


def test_bulk_generate_creates_one_row_per_model_times_color(owner_client, db_session):
    resp = owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "Test Wallet Case",
        "category": "CASE", "subcategory": "Generic", "sku_prefix": "",
        "price": "24.99", "cost": "8.00", "stock": "5",
        "reorder_threshold": "2", "reorder_qty": "10",
        "phone_selections": ["Apple||iPhone 16", "Apple||iPhone 16 Pro"],
        "extra_models": "",
        "colors": ["Black", "Clear"],
        "extra_colors": "",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/products"

    variants = db_session.query(Product).filter(Product.variant_group == "Test Wallet Case").all()
    assert len(variants) == 4  # 2 models x 2 colors

    combos = {(v.phone_model, v.color) for v in variants}
    assert combos == {
        ("iPhone 16", "Black"), ("iPhone 16", "Clear"),
        ("iPhone 16 Pro", "Black"), ("iPhone 16 Pro", "Clear"),
    }
    for v in variants:
        assert v.phone_brand == "Apple"
        assert v.price == 24.99
        assert v.cost == 8.00
        assert v.stock == 5
        assert v.sku  # non-empty and, since Product.sku is unique, implicitly distinct


def test_bulk_generate_supports_freeform_models_and_colors(owner_client, db_session):
    """The checklist covers common phones, but a shop needs to be able
    to add something new (or a brand not in the list) without a code
    change — that's what the two textareas are for."""
    resp = owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "Test Freeform Case",
        "category": "CASE", "price": "15.00", "cost": "0", "stock": "0",
        "reorder_threshold": "5", "reorder_qty": "10",
        "phone_selections": [],
        "extra_models": "LG: Velvet\nNokia G50",  # one with an explicit brand, one without
        "colors": [],
        "extra_colors": "Lavender, Mint Green",
    }, follow_redirects=False)
    assert resp.status_code == 303

    variants = db_session.query(Product).filter(Product.variant_group == "Test Freeform Case").all()
    assert len(variants) == 4  # 2 models x 2 colors

    models = {(v.phone_brand, v.phone_model) for v in variants}
    assert ("LG", "Velvet") in models
    assert ("Other", "Nokia G50") in models  # no colon in that line -> falls back to "Other"

    colors = {v.color for v in variants}
    assert colors == {"Lavender", "Mint Green"}


def test_bulk_generate_requires_style_models_and_colors(owner_client, db_session):
    """Missing any of the three required pieces should bounce back to
    the form with an error rather than silently creating nothing (or
    worse, partial garbage rows)."""
    before = db_session.query(Product).count()
    resp = owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "   ",  # whitespace-only — must be treated the same as blank
        "category": "CASE", "price": "10.00", "cost": "0", "stock": "0",
        "reorder_threshold": "5", "reorder_qty": "10",
        "phone_selections": ["Apple||iPhone 16"],
        "colors": ["Black"],
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/products/bulk-variants"
    assert db_session.query(Product).count() == before


def test_bulk_generate_requires_at_least_one_model(owner_client, db_session):
    before = db_session.query(Product).count()
    resp = owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "No Models Case",
        "category": "CASE", "price": "10.00", "cost": "0", "stock": "0",
        "reorder_threshold": "5", "reorder_qty": "10",
        "phone_selections": [],  # nothing checked
        "extra_models": "",
        "colors": ["Black"],
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/products/bulk-variants"
    assert db_session.query(Product).count() == before


def test_bulk_generate_requires_at_least_one_color(owner_client, db_session):
    before = db_session.query(Product).count()
    resp = owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "No Colors Case",
        "category": "CASE", "price": "10.00", "cost": "0", "stock": "0",
        "reorder_threshold": "5", "reorder_qty": "10",
        "phone_selections": ["Apple||iPhone 16"],
        "colors": [],  # nothing checked
        "extra_colors": "",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/products/bulk-variants"
    assert db_session.query(Product).count() == before


def test_bulk_generate_disambiguates_sku_collisions(owner_client, db_session):
    """Running the generator twice for the same style/model/color
    combination (e.g. staff accidentally double-submits) must not
    crash on the SKU unique constraint or silently drop the second
    batch — it should create a distinguishable second SKU."""
    payload = {
        "variant_group": "Test Collision Case",
        "category": "CASE", "price": "10.00", "cost": "0", "stock": "0",
        "reorder_threshold": "5", "reorder_qty": "10",
        "phone_selections": ["Apple||iPhone 16"],
        "colors": ["Black"],
    }
    first = owner_client.post("/products/bulk-variants/generate", data=payload, follow_redirects=False)
    assert first.status_code == 303
    second = owner_client.post("/products/bulk-variants/generate", data=payload, follow_redirects=False)
    assert second.status_code == 303

    variants = db_session.query(Product).filter(Product.variant_group == "Test Collision Case").all()
    assert len(variants) == 2
    skus = {v.sku for v in variants}
    assert len(skus) == 2, "both rows must have distinct SKUs, not a silently overwritten/duplicated one"


def test_bulk_generate_blocked_for_cashier(cashier_client, db_session):
    before = db_session.query(Product).count()
    resp = cashier_client.post("/products/bulk-variants/generate", data={
        "variant_group": "Blocked Case", "category": "CASE", "price": "10.00", "cost": "0", "stock": "0",
        "reorder_threshold": "5", "reorder_qty": "10",
        "phone_selections": ["Apple||iPhone 16"], "colors": ["Black"],
    }, follow_redirects=False)
    assert resp.status_code == 403
    assert db_session.query(Product).count() == before


def test_bulk_variants_form_requires_manager_or_owner(technician_client, cashier_client):
    for client in (technician_client, cashier_client):
        resp = client.get("/products/bulk-variants", follow_redirects=False)
        assert resp.status_code == 403


def test_bulk_generate_supports_laptop_models(owner_client, db_session):
    resp = owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "Laptop Sleeve",
        "category": "LAPTOP_ACC", "subcategory": "Incase",
        "price": "39.99", "cost": "12.00", "stock": "3",
        "reorder_threshold": "2", "reorder_qty": "5",
        "phone_selections": ["Apple||MacBook Air 13\" (M2/M3)", "Dell||XPS 13"],
        "colors": ["Black", "Gray"],
    }, follow_redirects=False)
    assert resp.status_code == 303

    variants = db_session.query(Product).filter(Product.variant_group == "Laptop Sleeve").all()
    assert len(variants) == 4  # 2 laptop models x 2 colors
    brands = {v.phone_brand for v in variants}
    assert brands == {"Apple", "Dell"}
    for v in variants:
        assert v.category == "LAPTOP_ACC"


def test_bulk_generate_supports_console_controller_models(owner_client, db_session):
    resp = owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "Controller Skin",
        "category": "GAMING", "subcategory": "Generic",
        "price": "12.99", "cost": "3.00", "stock": "10",
        "reorder_threshold": "3", "reorder_qty": "10",
        "phone_selections": ["Sony||DualSense Controller", "Microsoft||Xbox Controller"],
        "colors": ["Black", "Red", "Blue"],
    }, follow_redirects=False)
    assert resp.status_code == 303

    variants = db_session.query(Product).filter(Product.variant_group == "Controller Skin").all()
    assert len(variants) == 6  # 2 controller models x 3 colors
    models = {v.phone_model for v in variants}
    assert models == {"DualSense Controller", "Xbox Controller"}


def test_bulk_variants_form_loads_for_owner(owner_client):
    resp = owner_client.get("/products/bulk-variants")
    assert resp.status_code == 200
    assert "Bulk-Create Variants" in resp.text
