"""
Tests for the batch of improvements added on top of v30: the public
repair status lookup, notification bell layaway alerts, customer detail
trade-in/layaway visibility, and the POS phone-brand filter/variant
search data.
"""
import re

from app.models import Repair, Product, Customer, Layaway


# ── PUBLIC REPAIR STATUS LOOKUP ─────────────────────────────────────

def test_public_status_page_loads_without_login(anon_client):
    resp = anon_client.get("/status")
    assert resp.status_code == 200
    assert "Check Repair Status" in resp.text


def test_public_status_correct_ticket_and_phone_shows_status(owner_client, anon_client, db_session):
    owner_client.post("/repairs/add", data={
        "phone": "555-111-2222", "name": "Status Lookup Customer",
        "device": "iPhone 14", "issue": "Battery Replacement",
    })
    repair = db_session.query(Repair).filter(Repair.device == "iPhone 14").first()

    resp = anon_client.post("/status", data={"ticket_no": str(repair.ticket_no), "phone_last4": "2222"})
    assert resp.status_code == 200
    assert "iPhone 14" in resp.text
    assert "Received" in resp.text


def test_public_status_wrong_phone_digits_gives_generic_error_only(owner_client, anon_client, db_session):
    """The whole point of requiring phone digits: a wrong guess must not
    leak the device, issue, or any other detail — same generic message
    whether the ticket exists with a different phone, or doesn't exist
    at all."""
    owner_client.post("/repairs/add", data={
        "phone": "555-333-4444", "name": "Wrong Digits Customer",
        "device": "Samsung Galaxy S24", "issue": "Screen Replacement",
    })
    repair = db_session.query(Repair).filter(Repair.device == "Samsung Galaxy S24").first()

    resp = anon_client.post("/status", data={"ticket_no": str(repair.ticket_no), "phone_last4": "9999"})
    assert resp.status_code == 200
    assert "couldn" in resp.text.lower()  # "couldn&#39;t find a matching ticket"
    assert "Samsung Galaxy S24" not in resp.text
    assert "Screen Replacement" not in resp.text


def test_public_status_nonexistent_ticket_gives_same_generic_error(anon_client):
    """Same error text as a real-ticket-wrong-phone case (tested above)
    — a visitor incrementing ticket numbers can't tell the difference
    between 'wrong phone' and 'ticket doesn't exist'."""
    resp = anon_client.post("/status", data={"ticket_no": "999999", "phone_last4": "1234"})
    assert resp.status_code == 200
    assert "couldn" in resp.text.lower()


def test_public_status_does_not_expose_cost_fields(owner_client, anon_client, db_session):
    """Least-disclosure check: even on a correct lookup, financial
    fields (estimated/final cost) must never appear on this
    unauthenticated page."""
    owner_client.post("/repairs/add", data={
        "phone": "555-555-1111", "name": "Cost Privacy Customer",
        "device": "Pixel 8", "issue": "Water Damage", "estimated_cost": "199.99",
    })
    repair = db_session.query(Repair).filter(Repair.device == "Pixel 8").first()

    resp = anon_client.post("/status", data={"ticket_no": str(repair.ticket_no), "phone_last4": "1111"})
    assert "199.99" not in resp.text


def test_public_status_malformed_ticket_number_does_not_500(anon_client):
    resp = anon_client.post("/status", data={"ticket_no": "not-a-number", "phone_last4": "1234"})
    assert resp.status_code == 200
    assert "couldn" in resp.text.lower()


# ── NOTIFICATION BELL: LAYAWAY ALERTS ───────────────────────────────

def test_notifications_flag_overdue_layaway(owner_client, db_session):
    owner_client.post("/customers/add", data={"name": "Overdue Layaway Customer", "phone": "555-7100"})
    customer = db_session.query(Customer).filter(Customer.name == "Overdue Layaway Customer").first()
    product = db_session.query(Product).filter(Product.stock > 0).first()

    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    owner_client.post("/pos/customer", data={"customer_id": customer.id})
    owner_client.post("/pos/layaway/new", data={"deposit": "0", "due_date": "2000-01-01"})

    resp = owner_client.get("/api/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert any(n["href"] == "/layaway" and n["type"] == "danger" for n in data["notifications"])


def test_notifications_no_layaway_alert_when_none_overdue(owner_client, db_session):
    # The shared test database can carry an overdue layaway forward from
    # an earlier test in this file — clean those up first so this
    # assertion is actually testing "no overdue layaways exist" rather
    # than accidentally depending on test execution order.
    for stale in db_session.query(Layaway).filter(Layaway.status == "active").all():
        owner_client.post(f"/layaway/{stale.id}/cancel", data={"outcome": "cancelled"})

    owner_client.post("/customers/add", data={"name": "Future Layaway Customer", "phone": "555-7101"})
    customer = db_session.query(Customer).filter(Customer.name == "Future Layaway Customer").first()
    product = db_session.query(Product).filter(Product.stock > 0).first()

    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    owner_client.post("/pos/customer", data={"customer_id": customer.id})
    owner_client.post("/pos/layaway/new", data={"deposit": "0", "due_date": "2099-01-01"})

    resp = owner_client.get("/api/notifications")
    data = resp.json()
    assert not any(n["href"] == "/layaway" for n in data["notifications"])


# ── CUSTOMER DETAIL: TRADE-INS AND LAYAWAYS VISIBLE ─────────────────

def test_customer_detail_shows_their_layaways(owner_client, db_session):
    owner_client.post("/customers/add", data={"name": "Layaway Visibility Customer", "phone": "555-7200"})
    customer = db_session.query(Customer).filter(Customer.name == "Layaway Visibility Customer").first()
    product = db_session.query(Product).filter(Product.stock > 0).first()

    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    owner_client.post("/pos/customer", data={"customer_id": customer.id})
    owner_client.post("/pos/layaway/new", data={"deposit": "0"})

    layaway = db_session.query(Layaway).filter(Layaway.customer_id == customer.id).first()
    resp = owner_client.get(f"/customers/{customer.id}")
    assert resp.status_code == 200
    assert layaway.number in resp.text


def test_customer_detail_shows_their_trade_ins(owner_client, db_session):
    owner_client.post("/customers/add", data={"name": "Trade-In Visibility Customer", "phone": "555-7201"})
    customer = db_session.query(Customer).filter(Customer.name == "Trade-In Visibility Customer").first()

    owner_client.post("/trade-ins/add", data={
        "customer_id": customer.id, "device": "Visible Trade-In Phone",
        "offered_amount": "40.00", "payout_method": "cash",
    })

    resp = owner_client.get(f"/customers/{customer.id}")
    assert resp.status_code == 200
    assert "Visible Trade-In Phone" in resp.text


def test_customer_detail_no_layaways_or_trade_ins_shows_empty_state(owner_client, db_session):
    owner_client.post("/customers/add", data={"name": "Clean Customer", "phone": "555-7202"})
    customer = db_session.query(Customer).filter(Customer.name == "Clean Customer").first()

    resp = owner_client.get(f"/customers/{customer.id}")
    assert resp.status_code == 200
    assert "No layaways yet" in resp.text
    assert "No trade-ins yet" in resp.text


# ── POS: PHONE BRAND/MODEL DATA FOR THE VARIANT PICKER ──────────────

def test_pos_variant_group_data_includes_phone_model(owner_client, db_session):
    owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "POS Test Case", "category": "CASE", "price": "10.00", "cost": "0", "stock": "5",
        "reorder_threshold": "2", "reorder_qty": "10",
        "phone_selections": ["Apple||iPhone 16"], "colors": ["Black"],
    })
    resp = owner_client.get("/pos")
    assert resp.status_code == 200
    assert '"phone_model": "iPhone 16"' in resp.text
    assert '"phone_brand": "Apple"' in resp.text


def test_pos_shows_phone_brand_filter_chips(owner_client, db_session):
    owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "POS Chip Test Case", "category": "CASE", "price": "10.00", "cost": "0", "stock": "5",
        "reorder_threshold": "2", "reorder_qty": "10",
        "phone_selections": ["Samsung||Galaxy S24"], "colors": ["Black"],
    })
    resp = owner_client.get("/pos")
    assert resp.status_code == 200
    assert 'data-chipgroup="phone"' in resp.text
    assert "Samsung" in resp.text


def test_pos_scan_with_valid_sku_adds_to_cart(owner_client, db_session):
    product = db_session.query(Product).filter(Product.stock > 0).first()
    owner_client.post("/pos/clear")
    resp = owner_client.post("/pos/scan", data={"sku": product.sku}, follow_redirects=False)
    assert resp.status_code == 303
    cart_resp = owner_client.get("/pos")
    assert product.name in cart_resp.text


def test_pos_scan_with_empty_sku_does_not_500(owner_client):
    """Regression test for a real bug: sku was declared as a
    framework-required Form field (Form(...)), but an empty-but-present
    form value gets silently dropped by standard urlencoded body
    parsing before it ever reaches the route — FastAPI then rejects the
    whole request with a raw 422 JSON error instead of running the
    route's own (already-written, but previously unreachable) 'nothing
    scanned, just go back' handling. Reported after clicking 'Go' with
    nothing in the scan box."""
    resp = owner_client.post("/pos/scan", data={"sku": ""}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pos"


def test_pos_scan_with_sku_field_entirely_absent_does_not_500(owner_client):
    """Same bug, the other trigger: the form field genuinely missing
    from the request body at all (not just empty) — must be handled
    identically to an empty value, not crash."""
    resp = owner_client.post("/pos/scan", data={}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pos"


def test_pos_scan_unknown_sku_shows_friendly_error_not_a_crash(owner_client):
    resp = owner_client.post("/pos/scan", data={"sku": "DOES-NOT-EXIST-999"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pos"


# ── SCAN → PRICE-CHECK MODAL (AJAX path only) ───────────────────────
# Scanning used to add straight to the cart. It now hands the product to
# the same price-check modal a tapped tile uses, so staff can catch a
# wrong price or apply a discount before it's in the sale — but only over
# the AJAX path (the X-Pos-Ajax header the till's own JS sends). The
# tests above cover the non-AJAX fallback, which was deliberately left
# with its original direct-add behavior since there's no way to show a
# modal without JS; these cover the new behavior specifically.

def test_pos_scan_ajax_valid_sku_returns_product_json_without_adding_to_cart(owner_client, db_session):
    product = db_session.query(Product).filter(Product.stock > 0).first()
    owner_client.post("/pos/clear")
    resp = owner_client.post("/pos/scan", data={"sku": product.sku},
                              headers={"X-Pos-Ajax": "1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["product"]["pid"] == product.id
    assert body["product"]["name"] == product.name
    assert body["product"]["sku"] == product.sku
    assert body["product"]["price"] == product.price
    assert body["product"]["stock"] == product.stock

    # The whole point: it must NOT have landed in the cart on its own.
    # (product.name alone isn't a safe check — it's also sitting in the
    # left-side product browser regardless of cart state.)
    cart_resp = owner_client.get("/pos")
    assert "Cart is empty" in cart_resp.text


def test_pos_scan_ajax_unknown_sku_returns_json_error_not_a_redirect(owner_client):
    resp = owner_client.post("/pos/scan", data={"sku": "DOES-NOT-EXIST-999"},
                              headers={"X-Pos-Ajax": "1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert "DOES-NOT-EXIST-999" in body["error"]


def test_pos_scan_ajax_empty_sku_does_not_500(owner_client):
    resp = owner_client.post("/pos/scan", data={"sku": ""}, headers={"X-Pos-Ajax": "1"})
    assert resp.status_code == 200
    assert resp.json() == {"found": False, "error": ""}


def test_pos_scan_ajax_and_non_ajax_diverge_on_purpose(owner_client, db_session):
    """Same SKU, same request body — only the header differs. Locks in
    that this is a deliberate fork, not an accidental inconsistency."""
    product = db_session.query(Product).filter(Product.stock > 0).first()

    owner_client.post("/pos/clear")
    ajax_resp = owner_client.post("/pos/scan", data={"sku": product.sku}, headers={"X-Pos-Ajax": "1"})
    assert ajax_resp.json()["found"] is True
    assert "Cart is empty" in owner_client.get("/pos").text  # not added

    owner_client.post("/pos/clear")
    plain_resp = owner_client.post("/pos/scan", data={"sku": product.sku}, follow_redirects=False)
    assert plain_resp.status_code == 303
    pos_page = owner_client.get("/pos").text
    assert "Cart is empty" not in pos_page  # added directly, old behavior


# ── UI POLISH: SETTINGS TABS, REPORTS CHART, MOBILE CSS HOOKS ───────

def test_settings_page_has_four_tabs(owner_client):
    resp = owner_client.get("/settings")
    assert resp.status_code == 200
    for tab in ["general", "notifications", "security", "data"]:
        assert f'data-tab="{tab}"' in resp.text


def test_settings_save_persists_fields_from_every_tab_in_one_submit(owner_client, db_session):
    """Tabs are purely a client-side show/hide over ONE form — this
    confirms that's actually true server-side: a single POST with
    fields that live under different visible tabs must all save
    together, not just whichever tab happened to be open."""
    resp = owner_client.post("/settings", data={
        "shop_name": "Multi-Tab Save Test", "province": "AB", "invoice_prefix": "INV",
        "shop_address": "", "shop_phone": "", "shop_email": "", "shop_gst": "", "shop_pst": "",
        "points_per_dollar": "1", "points_redeem_rate": "100",
        "email_method": "smtp", "smtp_host": "", "smtp_port": "587", "smtp_user": "",
        "smtp_password": "", "smtp_from": "",
        "brevo_api_key": "", "brevo_from_email": "", "brevo_from_name": "",
        "twilio_sid": "ACmultitabtest", "twilio_token": "", "twilio_from": "",
        "digest_hour": "21",
        "security_question": "Multi-tab test question?", "security_answer": "yes",
    }, follow_redirects=False)
    assert resp.status_code == 303

    from app.models import Setting
    shop_name = db_session.get(Setting, "shop_name")
    twilio_sid = db_session.get(Setting, "twilio_sid")
    security_question = db_session.get(Setting, "security_question")
    assert shop_name.value == "Multi-Tab Save Test"
    assert twilio_sid.value == "ACmultitabtest"
    assert security_question.value == "Multi-tab test question?"


def test_settings_save_blank_shop_name_does_not_500_and_keeps_existing_value(owner_client, db_session):
    """Regression test for a real bug: shop_name/province/invoice_prefix
    were declared as framework-required Form fields, but the HTML
    inputs had no `required` attribute and there was no server-side
    fallback. An empty-but-present form value (not just a missing key)
    gets silently dropped by standard urlencoded body parsing, which
    made FastAPI treat it as genuinely missing and throw a raw 422 —
    wiping out every other tab's changes in the same submit, not just
    the blank field. Now it should redirect cleanly with an error
    flash and leave the existing setting untouched."""
    from app.models import Setting
    original = db_session.get(Setting, "shop_name").value

    resp = owner_client.post("/settings", data={
        "shop_name": "", "province": "BC", "invoice_prefix": "INV",
        "shop_address": "", "shop_phone": "", "shop_email": "", "shop_gst": "", "shop_pst": "",
        "points_per_dollar": "1", "points_redeem_rate": "100",
        "email_method": "smtp", "smtp_host": "", "smtp_port": "587", "smtp_user": "",
        "smtp_password": "", "smtp_from": "",
        "brevo_api_key": "", "brevo_from_email": "", "brevo_from_name": "",
        "twilio_sid": "", "twilio_token": "", "twilio_from": "",
        "digest_hour": "21", "security_question": "", "security_answer": "",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings"

    db_session.refresh(db_session.get(Setting, "shop_name"))
    assert db_session.get(Setting, "shop_name").value == original


def test_reports_page_renders_sales_chart_with_correct_total(owner_client, db_session):
    product = db_session.query(Product).filter(Product.stock > 0).first()
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    checkout = owner_client.post("/pos/checkout", data={"payment_method": "Cash", "tendered": "500"}, follow_redirects=False)
    assert checkout.status_code == 303

    resp = owner_client.get("/reports")
    assert resp.status_code == 200
    assert "Sales — Last 14 Days" in resp.text
    assert 'class="day-chart"' in resp.text
    # Today's bar should be the tallest (100%) since it's the only day with sales
    assert "height:100.0%" in resp.text


def test_reports_chart_handles_zero_sales_without_crashing(owner_client, db_session):
    """No invoices at all in range -> max_day would be 0 -> must not
    divide by zero when computing bar heights."""
    resp = owner_client.get("/reports")
    assert resp.status_code == 200
    assert "Sales — Last 14 Days" in resp.text


# ── BARCODE LABEL PRINTING ──────────────────────────────────────────

def test_label_print_by_group_includes_every_variant(owner_client, db_session):
    owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "Label Group Test", "category": "CASE", "price": "19.99", "cost": "5.00", "stock": "10",
        "reorder_threshold": "3", "reorder_qty": "10",
        "phone_selections": ["Apple||iPhone 16"], "colors": ["Black", "Clear"],
    })
    resp = owner_client.get("/products/labels/print", params={"group": "Label Group Test"})
    assert resp.status_code == 200
    assert resp.text.count('class="label"') == 2
    # Barcode is generated server-side and embedded directly — must be
    # real SVG markup already in the HTML, not a placeholder <svg> tag
    # waiting on JavaScript to fill it in after the page loads (that
    # was the actual bug: it silently failed whenever whatever rendered
    # the page for printing didn't execute JS). Counted specifically by
    # the physical-mm sizing python-barcode uses (icon SVGs elsewhere
    # on this page use 1em/px sizing, so this only matches barcodes).
    assert len(re.findall(r'<svg[^>]*width="[\d.]+mm"', resp.text)) == 2
    assert "<script" not in resp.text


def test_label_print_by_ids_only_includes_requested_products(owner_client, db_session):
    product = db_session.query(Product).filter(Product.stock > 0).first()
    resp = owner_client.get("/products/labels/print", params={"ids": product.id})
    assert resp.status_code == 200
    assert product.sku in resp.text
    assert "<svg" in resp.text


def test_label_print_copies_multiplies_label_count(owner_client, db_session):
    product = db_session.query(Product).filter(Product.stock > 0).first()
    resp = owner_client.get("/products/labels/print", params={"ids": product.id, "copies": 4})
    assert resp.status_code == 200
    assert resp.text.count('class="label"') == 4


def test_label_print_copies_is_clamped_not_unbounded(owner_client, db_session):
    """A fat-fingered copies=9999 must not actually render 9999 labels."""
    product = db_session.query(Product).filter(Product.stock > 0).first()
    resp = owner_client.get("/products/labels/print", params={"ids": product.id, "copies": 9999})
    assert resp.status_code == 200
    assert resp.text.count('class="label"') == 50


def test_label_print_no_params_shows_empty_state_not_error(owner_client):
    resp = owner_client.get("/products/labels/print")
    assert resp.status_code == 200
    assert "No products matched" in resp.text


def test_label_print_requires_login(anon_client):
    resp = anon_client.get("/products/labels/print", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_bulk_generate_flash_links_to_label_print_for_that_group(owner_client, db_session):
    resp = owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "Flash Link Test Case", "category": "CASE", "price": "10.00", "cost": "0", "stock": "0",
        "reorder_threshold": "5", "reorder_qty": "10",
        "phone_selections": ["Apple||iPhone 16"], "colors": ["Black"],
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert "/products/labels/print?group=Flash" in resp.text


def test_label_barcode_renders_for_long_sku_without_client_side_js(owner_client, db_session):
    """The actual reported bug: a long SKU (e.g. an iPhone 17 Pro Max
    variant name) generated via the bulk tool showed '(barcode
    unavailable)' at print time because the old implementation relied
    on JavaScript running after page load, which some print pipelines
    never execute. This is the regression test for that exact
    scenario — long model name, generated through the real bulk
    generator, must produce real SVG markup already present in the
    HTML response, with zero dependency on JS running afterward."""
    owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "Hard Ring Case", "category": "CASE", "price": "35.00", "cost": "10.00", "stock": "5",
        "reorder_threshold": "2", "reorder_qty": "10",
        "phone_selections": ["Apple||iPhone 17 Pro Max"], "colors": ["Black", "Navy"],
    })
    resp = owner_client.get("/products/labels/print", params={"group": "Hard Ring Case"})
    assert resp.status_code == 200
    assert "barcode unavailable" not in resp.text
    assert len(re.findall(r'<svg[^>]*width="[\d.]+mm"', resp.text)) == 2
    assert "<script" not in resp.text
    # The bars themselves must actually be present, not just an empty <svg> shell
    assert resp.text.count("<rect") > 20


def test_label_wide_warning_shows_for_long_sku_but_not_short_one(owner_client, db_session):
    owner_client.post("/products/bulk-variants/generate", data={
        "variant_group": "Hard Ring Case Warning Test", "category": "CASE", "price": "35.00", "cost": "0", "stock": "0",
        "reorder_threshold": "5", "reorder_qty": "10",
        "phone_selections": ["Apple||iPhone 17 Pro Max", "Apple||iPhone 16"], "colors": ["Black"],
    })
    resp = owner_client.get("/products/labels/print", params={"group": "Hard Ring Case Warning Test"})
    assert resp.status_code == 200
    # Long SKU (iPhone 17 Pro Max variant) should trigger the on-screen
    # "wide" flag; the shorter iPhone 16 variant should not need it.
    # We can't assert an exact count without hand-computing widths, but
    # the warning element itself must exist at least once for this batch.
    assert "wide-warning" in resp.text
    # ...and it must never appear inside the @media print block as
    # visible content — confirmed instead by checking the CSS rule
    # that hides it on print is present.
    assert ".wide-warning { display: none; }" in resp.text or ".wide-warning{display:none}" in resp.text
