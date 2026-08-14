"""
Regression tests for the three features added on top of v29: IMEI/serial
tracking, trade-ins, and layaway. Each section verifies both the happy
path (does the feature actually do what it's supposed to, checked
against the database directly — not just "did the page return 200") and
the access-control boundaries (who can and can't use it).
"""
import json

import pytest

from app.models import Repair, Invoice, InvoiceLine, Customer, Product, TradeIn, Layaway, LayawayPayment


# ── IMEI / SERIAL TRACKING ──────────────────────────────────────────

def test_repair_intake_saves_imei(owner_client, db_session):
    owner_client.post("/repairs/add", data={
        "phone": "555-7001", "name": "Imei Customer", "device": "iPhone 13",
        "imei": "356938035643809", "issue": "Screen Replacement",
    }, follow_redirects=False)
    repair = db_session.query(Repair).filter(Repair.device == "iPhone 13", Repair.imei == "356938035643809").first()
    assert repair is not None, "repair should be saved with the IMEI entered at intake"


def test_repair_intake_allows_blank_imei(owner_client, db_session):
    """IMEI is optional — not every repair is a phone with an IMEI (a
    cracked tablet screen, a laptop battery), and staff shouldn't be
    blocked from creating a ticket just because they don't have it yet."""
    resp = owner_client.post("/repairs/add", data={
        "phone": "555-7002", "name": "No Imei Customer", "device": "iPad Pro", "issue": "Battery",
    }, follow_redirects=False)
    assert resp.status_code == 303
    repair = db_session.query(Repair).filter(Repair.device == "iPad Pro").first()
    assert repair is not None
    assert repair.imei == ""


def test_repair_imei_can_be_edited_after_creation(owner_client, db_session):
    owner_client.post("/repairs/add", data={
        "phone": "555-7003", "name": "Edit Imei Customer", "device": "Pixel 8", "issue": "Charging Port",
    }, follow_redirects=False)
    repair = db_session.query(Repair).filter(Repair.device == "Pixel 8").first()
    assert repair.imei == ""

    resp = owner_client.post(f"/repairs/{repair.id}/imei", data={"imei": "990000862471854"}, follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(repair)
    assert repair.imei == "990000862471854"

    # And it can be cleared back out (e.g. it was entered wrong)
    owner_client.post(f"/repairs/{repair.id}/imei", data={"imei": ""}, follow_redirects=False)
    db_session.refresh(repair)
    assert repair.imei == ""


def test_pos_sale_carries_imei_onto_invoice_line(owner_client, db_session):
    product = db_session.query(Product).filter(Product.stock > 0).first()
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    owner_client.post("/pos/imei/0", data={"imei": "123456789012345"})

    resp = owner_client.post("/pos/checkout", data={"payment_method": "Cash", "tendered": "500.00"}, follow_redirects=False)
    assert resp.status_code == 303
    invoice_id = resp.headers["location"].rsplit("/", 1)[-1]

    db_session.expire_all()
    line = db_session.query(InvoiceLine).filter(InvoiceLine.invoice_id == invoice_id).first()
    assert line.imei == "123456789012345"


def test_pos_sale_without_imei_leaves_it_blank(owner_client, db_session):
    """Accessories (screen protectors, cases) shouldn't be forced to
    carry an IMEI — only serialized devices need one."""
    product = db_session.query(Product).filter(Product.stock > 0).first()
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")

    resp = owner_client.post("/pos/checkout", data={"payment_method": "Cash", "tendered": "500.00"}, follow_redirects=False)
    invoice_id = resp.headers["location"].rsplit("/", 1)[-1]

    db_session.expire_all()
    line = db_session.query(InvoiceLine).filter(InvoiceLine.invoice_id == invoice_id).first()
    assert line.imei == ""


def test_search_finds_repair_by_imei(owner_client, db_session):
    owner_client.post("/repairs/add", data={
        "phone": "555-7004", "name": "Search Imei Customer", "device": "Galaxy S23",
        "imei": "358965101234567", "issue": "Water Damage",
    }, follow_redirects=False)

    resp = owner_client.get("/search", params={"q": "358965101234567"})
    assert resp.status_code == 200
    assert "Galaxy S23" in resp.text


def test_search_finds_invoice_by_imei(owner_client, db_session):
    product = db_session.query(Product).filter(Product.stock > 0).first()
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    owner_client.post("/pos/imei/0", data={"imei": "987654321098765"})
    checkout = owner_client.post("/pos/checkout", data={"payment_method": "Cash", "tendered": "500.00"}, follow_redirects=False)
    invoice_id = checkout.headers["location"].rsplit("/", 1)[-1]
    db_session.expire_all()
    invoice = db_session.get(Invoice, invoice_id)

    resp = owner_client.get("/search", params={"q": "987654321098765"})
    assert resp.status_code == 200
    assert invoice.number in resp.text


# ── TRADE-INS ────────────────────────────────────────────────────────

def test_trade_in_new_customer_issues_store_credit(owner_client, db_session):
    resp = owner_client.post("/trade-ins/add", data={
        "customer_id": "", "new_customer_name": "Trade In Newbie", "new_customer_phone": "555-6001",
        "device": "iPhone 11, 64GB", "imei": "351234567890123", "condition": "Good",
        "offered_amount": "120.00", "payout_method": "store_credit", "notes": "",
    }, follow_redirects=False)
    assert resp.status_code == 303

    customer = db_session.query(Customer).filter(Customer.name == "Trade In Newbie").first()
    assert customer is not None, "a new customer should be created when none is selected"
    assert customer.store_credit == 120.00

    trade_in = db_session.query(TradeIn).filter(TradeIn.device == "iPhone 11, 64GB").first()
    assert trade_in is not None
    assert trade_in.imei == "351234567890123"
    assert trade_in.payout_method == "store_credit"
    assert trade_in.status == "accepted"


def test_trade_in_existing_customer_adds_to_existing_credit(owner_client, db_session):
    owner_client.post("/customers/add", data={"name": "Existing Trader", "phone": "555-6002"})
    customer = db_session.query(Customer).filter(Customer.name == "Existing Trader").first()
    customer.store_credit = 10.00
    db_session.commit()

    owner_client.post("/trade-ins/add", data={
        "customer_id": customer.id, "device": "Pixel 7", "offered_amount": "75.00",
        "payout_method": "store_credit",
    }, follow_redirects=False)

    db_session.refresh(customer)
    assert customer.store_credit == 85.00, "trade-in credit should add to whatever store credit the customer already had"

    # No duplicate customer should have been created
    matches = db_session.query(Customer).filter(Customer.name == "Existing Trader").all()
    assert len(matches) == 1


def test_trade_in_cash_payout_does_not_touch_store_credit(owner_client, db_session):
    owner_client.post("/customers/add", data={"name": "Cash Trader", "phone": "555-6003"})
    customer = db_session.query(Customer).filter(Customer.name == "Cash Trader").first()

    owner_client.post("/trade-ins/add", data={
        "customer_id": customer.id, "device": "OnePlus 9", "offered_amount": "50.00",
        "payout_method": "cash",
    }, follow_redirects=False)

    db_session.refresh(customer)
    assert customer.store_credit == 0, "a cash payout must not also grant store credit"

    trade_in = db_session.query(TradeIn).filter(TradeIn.device == "OnePlus 9").first()
    assert trade_in.payout_method == "cash"


def test_trade_in_walk_in_with_no_customer_at_all(owner_client, db_session):
    """Staff should be able to log a trade-in without creating a
    customer record at all (anonymous walk-in)."""
    resp = owner_client.post("/trade-ins/add", data={
        "customer_id": "", "new_customer_name": "", "device": "Old Flip Phone",
        "offered_amount": "5.00", "payout_method": "cash",
    }, follow_redirects=False)
    assert resp.status_code == 303
    trade_in = db_session.query(TradeIn).filter(TradeIn.device == "Old Flip Phone").first()
    assert trade_in is not None
    assert trade_in.customer_id is None


def test_trade_in_status_can_be_updated(owner_client, db_session):
    owner_client.post("/trade-ins/add", data={
        "device": "Status Test Phone", "offered_amount": "20.00", "payout_method": "cash",
    }, follow_redirects=False)
    trade_in = db_session.query(TradeIn).filter(TradeIn.device == "Status Test Phone").first()
    assert trade_in.status == "accepted"

    owner_client.post(f"/trade-ins/{trade_in.id}/status", data={"status": "resold"}, follow_redirects=False)
    db_session.refresh(trade_in)
    assert trade_in.status == "resold"


def test_trade_in_blocked_for_technician(technician_client):
    resp = technician_client.post("/trade-ins/add", data={
        "device": "Blocked Phone", "offered_amount": "10.00", "payout_method": "cash",
    }, follow_redirects=False)
    assert resp.status_code == 403, "technicians handle repairs, not buy/sell transactions"


def test_trade_in_allowed_for_cashier(cashier_client, db_session):
    resp = cashier_client.post("/trade-ins/add", data={
        "device": "Cashier Accepted Phone", "offered_amount": "10.00", "payout_method": "cash",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert db_session.query(TradeIn).filter(TradeIn.device == "Cashier Accepted Phone").first() is not None


def test_trade_ins_page_requires_login(anon_client):
    resp = anon_client.get("/trade-ins", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


# ── LAYAWAY ──────────────────────────────────────────────────────────

def _start_layaway(client, db_session, deposit="0", due_date="", customer_name_suffix=""):
    """Helper: creates a customer, adds one in-stock product to the
    cart, attaches the customer, and starts a layaway. Returns
    (layaway, product, starting_stock)."""
    client.post("/customers/add", data={"name": f"Layaway Customer{customer_name_suffix}", "phone": "555-5000"})
    customer = db_session.query(Customer).filter(Customer.name == f"Layaway Customer{customer_name_suffix}").first()

    product = db_session.query(Product).filter(Product.stock > 0).first()
    starting_stock = product.stock

    client.post("/pos/clear")
    client.post(f"/pos/add/{product.id}")
    client.post("/pos/customer", data={"customer_id": customer.id})
    resp = client.post("/pos/layaway/new", data={"deposit": deposit, "due_date": due_date}, follow_redirects=False)
    assert resp.status_code == 303
    layaway_id = resp.headers["location"].rsplit("/", 1)[-1]

    db_session.expire_all()
    layaway = db_session.get(Layaway, layaway_id)
    return layaway, product, starting_stock


def test_layaway_requires_a_customer(owner_client, db_session):
    product = db_session.query(Product).filter(Product.stock > 0).first()
    owner_client.post("/pos/clear")
    owner_client.post("/pos/customer", data={"customer_id": ""})  # explicitly no customer
    owner_client.post(f"/pos/add/{product.id}")

    # Count before/after rather than asserting a global 0 — the shared test
    # DB may already have layaways from other test files by the time this
    # runs (execution order isn't guaranteed), so what actually matters is
    # that *this* rejected attempt didn't create one, not that none exist
    # anywhere in the database.
    before = db_session.query(Layaway).count()
    resp = owner_client.post("/pos/layaway/new", data={"deposit": "0"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pos", "should bounce back to POS with an error, not create a layaway"
    assert db_session.query(Layaway).count() == before


def test_layaway_requires_a_non_empty_cart(owner_client, db_session):
    owner_client.post("/customers/add", data={"name": "Empty Cart Customer", "phone": "555-5099"})
    customer = db_session.query(Customer).filter(Customer.name == "Empty Cart Customer").first()
    owner_client.post("/pos/clear")
    owner_client.post("/pos/customer", data={"customer_id": customer.id})

    resp = owner_client.post("/pos/layaway/new", data={"deposit": "0"}, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pos"
    assert db_session.query(Layaway).filter(Layaway.customer_id == customer.id).count() == 0


def test_layaway_creation_reserves_stock_and_records_deposit(owner_client, db_session):
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="15.00", due_date="2026-12-01", customer_name_suffix="A")

    assert layaway is not None
    assert layaway.status == "active"
    assert layaway.paid_total == 15.00
    assert layaway.due_date == "2026-12-01"
    assert layaway.number.startswith("LAY-")

    db_session.refresh(product)
    assert product.stock == starting_stock - 1, "stock must be reserved immediately, same as a normal sale"

    payments = db_session.query(LayawayPayment).filter(LayawayPayment.layaway_id == layaway.id).all()
    assert len(payments) == 1
    assert payments[0].amount == 15.00


def test_layaway_with_no_deposit_starts_at_zero_paid(owner_client, db_session):
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="0", customer_name_suffix="B")
    assert layaway.paid_total == 0
    assert db_session.query(LayawayPayment).filter(LayawayPayment.layaway_id == layaway.id).count() == 0


def test_layaway_partial_payment_updates_balance_without_completing(owner_client, db_session):
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="5.00", customer_name_suffix="C")
    total = layaway.total
    assert total > 5.00, "test product must cost more than the deposit for this test to be meaningful"

    partial = round((total - 5.00) / 2, 2)
    resp = owner_client.post(f"/layaway/{layaway.id}/payment", data={"amount": str(partial), "method": "Cash"}, follow_redirects=False)
    assert resp.status_code == 303

    db_session.refresh(layaway)
    assert layaway.status == "active", "should still be active — not fully paid off yet"
    assert layaway.paid_total == round(5.00 + partial, 2)
    assert layaway.invoice_id is None


def test_layaway_full_payoff_converts_to_invoice_without_double_deducting_stock(owner_client, db_session):
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="0", customer_name_suffix="D")
    stock_after_reserve = starting_stock - 1

    resp = owner_client.post(f"/layaway/{layaway.id}/payment", data={"amount": str(layaway.total), "method": "Cash"}, follow_redirects=False)
    assert resp.status_code == 303

    db_session.refresh(layaway)
    assert layaway.status == "completed"
    assert layaway.paid_total == layaway.total
    assert layaway.invoice_id is not None

    invoice = db_session.get(Invoice, layaway.invoice_id)
    assert invoice is not None
    assert invoice.total == layaway.total
    assert invoice.payment_method == f"Layaway ({layaway.number})"

    line = db_session.query(InvoiceLine).filter(InvoiceLine.invoice_id == invoice.id).first()
    assert line is not None
    assert line.product_id == product.id

    db_session.refresh(product)
    assert product.stock == stock_after_reserve, "stock must NOT be deducted a second time on payoff — it was already reserved at creation"


def test_layaway_payoff_awards_loyalty_points_and_spend(owner_client, db_session):
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="0", customer_name_suffix="E")
    customer = layaway.customer
    points_before = customer.points or 0
    spent_before = customer.spent or 0

    owner_client.post(f"/layaway/{layaway.id}/payment", data={"amount": str(layaway.total), "method": "Cash"}, follow_redirects=False)

    db_session.refresh(customer)
    assert customer.spent == round(spent_before + layaway.total, 2)
    assert customer.points > points_before, "completing a layaway should earn loyalty points just like a normal sale"


def test_layaway_overpayment_still_completes(owner_client, db_session):
    """Paying more than the remaining balance (customer rounds up, pays
    a bit extra) should still successfully complete the layaway rather
    than getting stuck just under the threshold."""
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="0", customer_name_suffix="F")
    overpay = round(layaway.total + 10.00, 2)

    resp = owner_client.post(f"/layaway/{layaway.id}/payment", data={"amount": str(overpay), "method": "Cash"}, follow_redirects=False)
    assert resp.status_code == 303

    db_session.refresh(layaway)
    assert layaway.status == "completed"
    assert layaway.paid_total == overpay


def test_layaway_zero_or_negative_payment_is_rejected(owner_client, db_session):
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="0", customer_name_suffix="G")

    resp = owner_client.post(f"/layaway/{layaway.id}/payment", data={"amount": "0", "method": "Cash"}, follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(layaway)
    assert layaway.paid_total == 0, "a $0 payment must not be recorded"
    assert layaway.status == "active"


def test_layaway_cannot_be_paid_once_completed(owner_client, db_session):
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="0", customer_name_suffix="H")
    owner_client.post(f"/layaway/{layaway.id}/payment", data={"amount": str(layaway.total), "method": "Cash"}, follow_redirects=False)
    db_session.refresh(layaway)
    assert layaway.status == "completed"
    paid_before = layaway.paid_total

    # Try to pay again on an already-completed layaway
    owner_client.post(f"/layaway/{layaway.id}/payment", data={"amount": "5.00", "method": "Cash"}, follow_redirects=False)
    db_session.refresh(layaway)
    assert layaway.paid_total == paid_before, "no further payments should be accepted once completed"


def test_layaway_cancel_restocks_items(owner_client, db_session):
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="10.00", customer_name_suffix="I")
    stock_after_reserve = starting_stock - 1
    db_session.refresh(product)
    assert product.stock == stock_after_reserve

    resp = owner_client.post(f"/layaway/{layaway.id}/cancel", data={"outcome": "cancelled"}, follow_redirects=False)
    assert resp.status_code == 303

    db_session.refresh(layaway)
    assert layaway.status == "cancelled"

    db_session.refresh(product)
    assert product.stock == starting_stock, "cancelling must put the reserved stock back"


def test_layaway_forfeit_restocks_but_marks_forfeited(owner_client, db_session):
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="10.00", customer_name_suffix="J")

    resp = owner_client.post(f"/layaway/{layaway.id}/cancel", data={"outcome": "forfeited"}, follow_redirects=False)
    assert resp.status_code == 303

    db_session.refresh(layaway)
    assert layaway.status == "forfeited"

    db_session.refresh(product)
    assert product.stock == starting_stock, "forfeited items go back on the shelf too — the customer doesn't get them"


def test_layaway_cancel_blocked_for_cashier(cashier_client, owner_client, db_session):
    """Cancelling/forfeiting moves stock and writes off a customer's
    deposit — that's a manager-level decision, same tier as refunds."""
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="0", customer_name_suffix="K")

    resp = cashier_client.post(f"/layaway/{layaway.id}/cancel", data={"outcome": "cancelled"}, follow_redirects=False)
    assert resp.status_code == 403

    db_session.refresh(layaway)
    assert layaway.status == "active", "a blocked cancel attempt must not have changed anything"


def test_layaway_cancel_allowed_for_manager(manager_client, owner_client, db_session):
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="0", customer_name_suffix="L")
    resp = manager_client.post(f"/layaway/{layaway.id}/cancel", data={"outcome": "cancelled"}, follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(layaway)
    assert layaway.status == "cancelled"


def test_layaway_list_and_detail_pages_render(owner_client, db_session):
    layaway, product, starting_stock = _start_layaway(owner_client, db_session, deposit="8.00", customer_name_suffix="M")

    list_resp = owner_client.get("/layaway")
    assert list_resp.status_code == 200
    assert layaway.number in list_resp.text

    detail_resp = owner_client.get(f"/layaway/{layaway.id}")
    assert detail_resp.status_code == 200
    assert layaway.number in detail_resp.text
    assert product.name in detail_resp.text


def test_layaway_routes_require_login(anon_client):
    for path in ["/layaway"]:
        resp = anon_client.get(path, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"
