"""
Regression coverage for the Cash Up card-reconciliation fix.

Before this fix, /cashup filtered invoices for payment_method in
("Credit Card", "Debit") — strings POS never actually wrote (it writes
"Card"), and Split payments were excluded from both cash and card totals
entirely. That meant card_expected was silently $0 always, and the cash
side under-counted the drawer on any day with a split payment. There was
no test coverage over this at all, which is exactly how it went unnoticed
— these tests are here so it can't happen again silently.
"""
from datetime import datetime, timedelta

from app.main import resolve_tender_split, payment_method_label, todays_cash_card_totals
from app.models import Product, Invoice, LayawayPayment, Layaway, Customer


def _make_product(db_session, suffix, price=25.00, stock=50):
    p = Product(id=f"ccr-{suffix}", sku=f"CCR-{suffix}".upper(), name=f"Test Product {suffix}",
                category="ACCESSORY", price=price, cost=5.00, stock=stock)
    db_session.add(p)
    db_session.commit()
    return p


# ── resolve_tender_split() — pure function, no DB/HTTP needed ──────────

def test_resolve_split_cash_only():
    cash, card = resolve_tender_split("Cash", 100.0, 0, 0)
    assert (cash, card) == (100.0, 0.0)


def test_resolve_split_card_only():
    cash, card = resolve_tender_split("Card", 100.0, 0, 0)
    assert (cash, card) == (0.0, 100.0)


def test_resolve_split_actual_split():
    cash, card = resolve_tender_split("Split (Cash $20.00 + Card $80.00)", 100.0, 20.0, 80.0)
    assert (cash, card) == (20.0, 80.0)


def test_resolve_split_overpayment_nets_change_out_of_cash():
    # $5 cash + $20 card against a $16.94 total: card is charged the exact
    # $20, and the $8.06 change comes back out of the cash side.
    cash, card = resolve_tender_split("Split (Cash $5.00 + Card $20.00)", 16.94, 5.0, 20.0)
    assert card == 20.0
    assert cash == -3.06
    assert round(cash + card, 2) == 16.94


def test_resolve_split_non_physical_methods_touch_neither():
    for pm in ("UPI", "E-Transfer", "Store Credit"):
        assert resolve_tender_split(pm, 100.0, 0, 0) == (0.0, 0.0), pm


def test_payment_method_label_collapses_split_variants():
    a = payment_method_label("Split (Cash $12.34 + Card $56.78)")
    b = payment_method_label("Split (Cash $1.00 + Card $99.00)")
    assert a == b == "Split (Cash + Card)"


def test_payment_method_label_passthrough_for_non_split():
    for pm in ("Cash", "Card", "UPI", "E-Transfer", "Store Credit"):
        assert payment_method_label(pm) == pm


# ── Full checkout -> Invoice fields, through the real route ────────────

def test_cash_checkout_records_full_cash_amount(owner_client, db_session):
    product = _make_product(db_session, "cash1")
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    resp = owner_client.post("/pos/checkout", data={"payment_method": "Cash", "tendered": "100.00"},
                              follow_redirects=False)
    assert resp.status_code == 303
    invoice_id = resp.headers["location"].rsplit("/", 1)[-1]
    db_session.expire_all()
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice.payment_method == "Cash"
    assert invoice.cash_amount == invoice.total
    assert invoice.card_amount == 0
    assert invoice.card_reference == ""


def test_card_checkout_records_full_card_amount_and_reference(owner_client, db_session):
    product = _make_product(db_session, "card1")
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    resp = owner_client.post("/pos/checkout", data={
        "payment_method": "Card", "card_reference": "AUTH00123",
    }, follow_redirects=False)
    assert resp.status_code == 303
    invoice_id = resp.headers["location"].rsplit("/", 1)[-1]
    db_session.expire_all()
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice.payment_method == "Card"
    assert invoice.card_amount == invoice.total
    assert invoice.cash_amount == 0
    assert invoice.card_reference == "AUTH00123"


def test_card_checkout_reference_is_optional(owner_client, db_session):
    product = _make_product(db_session, "card2")
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    resp = owner_client.post("/pos/checkout", data={"payment_method": "Card"}, follow_redirects=False)
    assert resp.status_code == 303
    invoice_id = resp.headers["location"].rsplit("/", 1)[-1]
    db_session.expire_all()
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice.card_amount == invoice.total
    assert invoice.card_reference == ""  # not required to check out


def test_split_checkout_records_both_amounts_correctly(owner_client, db_session):
    product = _make_product(db_session, "split1", price=100.00)
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    # Ontario HST 13% on $100 = $113.00 total; split as $30 cash + $83 card.
    resp = owner_client.post("/pos/checkout", data={
        "cash_part": "30.00", "card_part": "83.00", "card_reference": "SPLIT001",
    }, follow_redirects=False)
    assert resp.status_code == 303
    invoice_id = resp.headers["location"].rsplit("/", 1)[-1]
    db_session.expire_all()
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice.payment_method.startswith("Split (")
    assert invoice.cash_amount == 30.00
    assert invoice.card_amount == 83.00
    assert invoice.card_reference == "SPLIT001"
    assert round(invoice.cash_amount + invoice.card_amount, 2) == invoice.total


def test_split_checkout_overpayment_change_comes_out_of_the_cash_side(owner_client, db_session):
    """Regression test for a real bug caught during manual verification:
    $5 cash + $20 card against a $16.94 sale (customer expects $8.06
    change) was originally recorded as cash_amount=5, card_amount=20 —
    summing to $25, overstating actual drawer cash by the full $8.06 of
    change, since a card terminal can't hand back partial change, so any
    overpayment has to come back out of the cash side. The correct net
    cash impact here is 5 - 8.06 = -3.06: this specific sale needs $3.06
    *more* cash to leave the drawer as change than it took in."""
    product = _make_product(db_session, "split-over", price=14.99)
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    resp = owner_client.post("/pos/checkout", data={
        "cash_part": "5.00", "card_part": "20.00",
    }, follow_redirects=False)
    assert resp.status_code == 303
    invoice_id = resp.headers["location"].rsplit("/", 1)[-1]
    db_session.expire_all()
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice.total == 16.94
    assert invoice.change_given == 8.06
    assert invoice.card_amount == 20.00, "the card terminal really was charged the full $20"
    assert invoice.cash_amount == -3.06, "net cash: $5 tendered minus $8.06 change given back"
    assert round(invoice.cash_amount + invoice.card_amount, 2) == invoice.total, \
        "cash_amount + card_amount must always equal the invoice total, overpayment or not"


def test_upi_and_etransfer_touch_neither_cash_nor_card(owner_client, db_session):
    for pm in ("UPI", "E-Transfer", "Store Credit"):
        product = _make_product(db_session, f"nc-{pm}")
        owner_client.post("/pos/clear")
        owner_client.post(f"/pos/add/{product.id}")
        resp = owner_client.post("/pos/checkout", data={"payment_method": pm}, follow_redirects=False)
        assert resp.status_code == 303, pm
        invoice_id = resp.headers["location"].rsplit("/", 1)[-1]
        db_session.expire_all()
        invoice = db_session.get(Invoice, invoice_id)
        assert invoice.cash_amount == 0, pm
        assert invoice.card_amount == 0, pm


# ── todays_cash_card_totals() — the actual reconciliation math ─────────

def test_todays_totals_aggregates_cash_and_card_invoices(owner_client, db_session):
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    p1 = _make_product(db_session, "agg-cash", price=40.00)
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{p1.id}")
    owner_client.post("/pos/checkout", data={"payment_method": "Cash", "tendered": "200"})

    p2 = _make_product(db_session, "agg-card", price=60.00)
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{p2.id}")
    owner_client.post("/pos/checkout", data={"payment_method": "Card", "card_reference": "REF1"})

    db_session.expire_all()
    totals = todays_cash_card_totals(db_session, today_str)
    # $40 * 1.13 = $45.20 cash, $60 * 1.13 = $67.80 card — at minimum these
    # two sales' worth must be present (other tests in this file/session may
    # have added more, so use >= rather than an exact equality).
    assert totals["cash_sales"] >= 45.20 - 0.01
    assert totals["card_sales"] >= 67.80 - 0.01


def test_todays_totals_excludes_invoices_from_other_days(db_session):
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    yesterday = datetime.utcnow() - timedelta(days=1)

    old_invoice = Invoice(
        number="CCR-OLD-1", payment_method="Card", cash_amount=0, card_amount=999.00,
        card_reference="SHOULD-NOT-COUNT", subtotal=999.00, total=999.00, date=yesterday,
    )
    db_session.add(old_invoice)
    db_session.commit()

    totals = todays_cash_card_totals(db_session, today_str)
    assert totals["card_sales"] < 999.00, "an invoice dated yesterday must not appear in today's totals"
    ids_today = [i.id for i in totals["card_invoices_today"]]
    assert old_invoice.id not in ids_today


def test_todays_totals_excludes_refunded_invoices(db_session):
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    refunded = Invoice(
        number="CCR-REFUNDED-1", payment_method="Card", cash_amount=0, card_amount=500.00,
        subtotal=500.00, total=500.00, date=datetime.utcnow(), refunded=True,
    )
    db_session.add(refunded)
    db_session.commit()

    totals = todays_cash_card_totals(db_session, today_str)
    ids_today = [i.id for i in totals["card_invoices_today"]]
    assert refunded.id not in ids_today


def test_todays_totals_flags_card_sales_missing_a_reference(db_session):
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    with_ref = Invoice(number="CCR-WITHREF-1", payment_method="Card", cash_amount=0, card_amount=10.00,
                        card_reference="HASREF", subtotal=10, total=10, date=datetime.utcnow())
    without_ref = Invoice(number="CCR-NOREF-1", payment_method="Card", cash_amount=0, card_amount=10.00,
                           card_reference="", subtotal=10, total=10, date=datetime.utcnow())
    db_session.add_all([with_ref, without_ref])
    db_session.commit()

    totals = todays_cash_card_totals(db_session, today_str)
    assert totals["card_missing_ref"] >= 1
    ref_map = {i.id: i.card_reference for i in totals["card_invoices_today"]}
    assert ref_map.get(with_ref.id) == "HASREF"
    assert ref_map.get(without_ref.id) == ""


def test_layaway_installment_paid_today_counts_toward_cash_or_card(db_session):
    """A deposit/installment collected today should show up in today's
    reconciliation even though the layaway itself isn't paid off yet —
    that money is really sitting in the drawer or on the terminal today,
    regardless of when the layaway finishes."""
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    customer = Customer(name="Layaway Recon Customer", phone="555-7777")
    db_session.add(customer)
    db_session.commit()
    layaway = Layaway(number="LAY-RECON-1", customer_id=customer.id, cart_json="[]",
                       subtotal=200, tax_total=0, total=200, paid_total=0, status="active")
    db_session.add(layaway)
    db_session.commit()

    cash_payment = LayawayPayment(layaway_id=layaway.id, amount=50.00, method="Cash",
                                   created_at=datetime.utcnow())
    debit_payment = LayawayPayment(layaway_id=layaway.id, amount=30.00, method="Debit",
                                    created_at=datetime.utcnow())
    db_session.add_all([cash_payment, debit_payment])
    db_session.commit()

    totals = todays_cash_card_totals(db_session, today_str)
    assert totals["cash_sales"] >= 50.00 - 0.01
    assert totals["card_sales"] >= 30.00 - 0.01


def test_layaway_payoff_invoice_does_not_double_count_earlier_installments(owner_client, db_session):
    """The lump-sum invoice created when a layaway is finally paid off must
    contribute $0 to cash_amount/card_amount — its installments were
    already counted individually, on the days each was actually paid."""
    product = _make_product(db_session, "layaway-payoff", price=50.00, stock=10)
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")

    customer = Customer(name="Payoff Test Customer", phone="555-6666")
    db_session.add(customer)
    db_session.commit()
    owner_client.post("/pos/customer", data={"customer_id": customer.id})

    resp = owner_client.post("/pos/layaway/new", data={"deposit": "", "due_date": ""}, follow_redirects=False)
    assert resp.status_code == 303
    db_session.expire_all()
    layaway = db_session.query(Layaway).filter_by(customer_id=customer.id).order_by(Layaway.created_at.desc()).first()
    assert layaway is not None

    # Pay it off in one go, today, via Debit.
    pay_resp = owner_client.post(f"/layaway/{layaway.id}/payment", data={
        "amount": f"{layaway.total:.2f}", "method": "Debit",
    }, follow_redirects=False)
    assert pay_resp.status_code == 303

    db_session.expire_all()
    payoff_invoice = db_session.query(Invoice).filter(Invoice.payment_method == f"Layaway ({layaway.number})").first()
    assert payoff_invoice is not None
    assert payoff_invoice.cash_amount == 0
    assert payoff_invoice.card_amount == 0, "the lump-sum payoff invoice must not itself count toward card_sales"

    # But the totals for today must still reflect the installment payment
    # that actually happened (via LayawayPayment, not the payoff invoice).
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    totals = todays_cash_card_totals(db_session, today_str)
    assert totals["card_sales"] >= layaway.total - 0.01


# ── /cashup route-level sanity (uses the fixed totals end to end) ──────

def test_cashup_page_renders_with_new_fields(owner_client, db_session):
    resp = owner_client.get("/cashup")
    assert resp.status_code == 200
    assert "Cash Sales" in resp.text
    assert "Card / Debit" in resp.text


def test_cashup_close_uses_corrected_card_expected(owner_client, db_session):
    product = _make_product(db_session, "cashup-close", price=20.00)
    owner_client.post("/pos/clear")
    owner_client.post(f"/pos/add/{product.id}")
    owner_client.post("/pos/checkout", data={"payment_method": "Card", "card_reference": "CLOSEREF"})

    db_session.expire_all()
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    expected_card = todays_cash_card_totals(db_session, today_str)["card_sales"]

    resp = owner_client.post("/cashup/close", data={
        "open_float": "200", "actual": "200",
    }, follow_redirects=False)
    assert resp.status_code == 303

    from app.models import CashSession
    db_session.expire_all()
    session_row = db_session.query(CashSession).filter(CashSession.date == today_str).first()
    assert session_row is not None
    assert session_row.card_expected == expected_card
    assert session_row.card_expected > 0, "card_expected must no longer be silently stuck at $0"
