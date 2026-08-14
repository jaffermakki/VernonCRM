"""
Tests for the four features added in this round: warranty status lookup,
the exchange (not refund) workflow, CASL marketing-consent tracking, and
the two-way SMS webhook.
"""
import json
from datetime import datetime, timedelta

from app.models import Product, Customer, Repair, Invoice, InvoiceLine, SmsMessage


def test_warranty_active_right_after_collection(owner_client, db_session):
    """A repair collected today with a 90-day warranty should show as
    active with ~90 days remaining."""
    from app.main import get_warranty_status
    history = json.dumps([{"status": "COLLECTED", "note": "", "date": datetime.utcnow().isoformat()}])
    repair = Repair(id="warr-1", ticket_no=9001, device="Test Phone", issue="Screen",
                     status="COLLECTED", warranty_days=90, status_history=history)
    db_session.add(repair)
    db_session.commit()

    warranty = get_warranty_status(repair)
    assert warranty is not None
    assert warranty["active"] is True
    assert 88 <= warranty["days_remaining"] <= 90


def test_warranty_expired_after_warranty_period(db_session):
    from app.main import get_warranty_status
    old_date = (datetime.utcnow() - timedelta(days=200)).isoformat()
    history = json.dumps([{"status": "COLLECTED", "note": "", "date": old_date}])
    repair = Repair(id="warr-2", ticket_no=9002, device="Test Phone", issue="Battery",
                     status="COLLECTED", warranty_days=90, status_history=history)
    db_session.add(repair)
    db_session.commit()

    warranty = get_warranty_status(repair)
    assert warranty["active"] is False


def test_warranty_none_if_not_yet_collected(db_session):
    from app.main import get_warranty_status
    repair = Repair(id="warr-3", ticket_no=9003, device="Test Phone", issue="Camera",
                     status="IN_PROGRESS", warranty_days=90, status_history="[]")
    db_session.add(repair)
    db_session.commit()
    assert get_warranty_status(repair) is None


def test_warranty_shown_on_repair_detail_page(owner_client, db_session):
    history = json.dumps([{"status": "COLLECTED", "note": "", "date": datetime.utcnow().isoformat()}])
    repair = Repair(id="warr-4", ticket_no=9004, device="Warranty Display Test", issue="Screen",
                     status="COLLECTED", warranty_days=90, status_history=history)
    db_session.add(repair)
    db_session.commit()

    resp = owner_client.get("/repairs/warr-4")
    assert resp.status_code == 200
    assert "Under Warranty" in resp.text


def test_exchange_restocks_original_and_deducts_replacement(owner_client, db_session):
    original = Product(id="exch-orig", sku="EXCH-ORIG", name="Black Case", category="ACCESSORY",
                        price=15.0, cost=5.0, stock=2)
    replacement = Product(id="exch-new", sku="EXCH-NEW", name="Red Case", category="ACCESSORY",
                           price=15.0, cost=5.0, stock=3)
    invoice = Invoice(id="exch-inv", number="EXCH-TEST-1", payment_method="Cash",
                       subtotal=15.0, tax_total=1.95, total=16.95)
    line = InvoiceLine(id="exch-line", invoice_id="exch-inv", product_id="exch-orig",
                        name="Black Case", sku="EXCH-ORIG", qty=1, price=15.0)
    db_session.add_all([original, replacement, invoice, line])
    db_session.commit()

    resp = owner_client.post("/invoices/exch-inv/exchange-line/exch-line",
                              data={"new_product_id": "exch-new"}, follow_redirects=False)
    assert resp.status_code == 303

    db_session.expire_all()
    orig = db_session.get(Product, "exch-orig")
    new = db_session.get(Product, "exch-new")
    updated_line = db_session.get(InvoiceLine, "exch-line")
    assert orig.stock == 3, "original item should be restocked"
    assert new.stock == 2, "replacement item should be deducted"
    assert updated_line.name == "Red Case"
    assert "Exchanged from: Black Case" in updated_line.exchange_note


def test_exchange_blocked_on_refunded_invoice(owner_client, db_session):
    product = Product(id="exch-blocked-p", sku="EXCH-BLK", name="Item", category="ACCESSORY", price=10.0, cost=3.0, stock=5)
    invoice = Invoice(id="exch-blocked-inv", number="EXCH-TEST-2", payment_method="Cash",
                       subtotal=10.0, tax_total=1.3, total=11.3, refunded=True)
    line = InvoiceLine(id="exch-blocked-line", invoice_id="exch-blocked-inv", product_id="exch-blocked-p",
                        name="Item", sku="EXCH-BLK", qty=1, price=10.0)
    db_session.add_all([product, invoice, line])
    db_session.commit()

    resp = owner_client.post("/invoices/exch-blocked-inv/exchange-line/exch-blocked-line",
                              data={"new_product_id": "exch-blocked-p"}, follow_redirects=False)
    # Should redirect without making any change — refunded invoices can't be exchanged
    assert resp.status_code == 303
    db_session.expire_all()
    unchanged = db_session.get(InvoiceLine, "exch-blocked-line")
    assert unchanged.name == "Item"  # untouched


def test_exchange_requires_manager_or_owner(cashier_client, db_session):
    product = Product(id="exch-perm-p", sku="EXCH-PERM", name="Item", category="ACCESSORY", price=10.0, cost=3.0, stock=5)
    invoice = Invoice(id="exch-perm-inv", number="EXCH-TEST-3", payment_method="Cash", subtotal=10.0, tax_total=1.3, total=11.3)
    line = InvoiceLine(id="exch-perm-line", invoice_id="exch-perm-inv", product_id="exch-perm-p",
                        name="Item", sku="EXCH-PERM", qty=1, price=10.0)
    db_session.add_all([product, invoice, line])
    db_session.commit()

    resp = cashier_client.post("/invoices/exch-perm-inv/exchange-line/exch-perm-line",
                                data={"new_product_id": "exch-perm-p"}, follow_redirects=False)
    assert resp.status_code == 403


def test_casl_consent_stamped_on_customer_add(owner_client, db_session):
    owner_client.post("/customers/add", data={
        "name": "Consent Test Customer", "phone": "555-9001", "marketing_consent": "on",
    })
    customer = db_session.query(Customer).filter(Customer.name == "Consent Test Customer").first()
    assert customer is not None
    assert customer.marketing_consent is True
    assert customer.consent_date is not None


def test_casl_consent_not_set_without_checkbox(owner_client, db_session):
    owner_client.post("/customers/add", data={"name": "No Consent Customer", "phone": "555-9002"})
    customer = db_session.query(Customer).filter(Customer.name == "No Consent Customer").first()
    assert customer.marketing_consent is False
    assert customer.consent_date is None


def test_sms_webhook_rejects_wrong_secret(anon_client):
    resp = anon_client.post("/webhooks/sms-reply/wrong-secret-value", data={"From": "+15551234567", "Body": "Hi"})
    assert resp.status_code == 403


def test_sms_webhook_accepts_correct_secret_and_logs_message(anon_client, owner_client, db_session):
    from app.main import get_sms_webhook_secret
    secret = get_sms_webhook_secret(db_session)

    customer = Customer(id="sms-test-cust", name="SMS Test Customer", phone="+15559998888")
    db_session.add(customer)
    db_session.commit()

    resp = anon_client.post(f"/webhooks/sms-reply/{secret}",
                             data={"From": "+15559998888", "Body": "Is my phone ready?"})
    assert resp.status_code == 200
    assert "<Response" in resp.text  # valid TwiML

    db_session.expire_all()
    msg = db_session.query(SmsMessage).filter(SmsMessage.phone == "+15559998888").first()
    assert msg is not None
    assert msg.direction == "in"
    assert msg.body == "Is my phone ready?"
    assert msg.customer_id == "sms-test-cust"  # matched by phone number


def test_sms_webhook_handles_unknown_phone_gracefully(anon_client, db_session):
    from app.main import get_sms_webhook_secret
    secret = get_sms_webhook_secret(db_session)
    resp = anon_client.post(f"/webhooks/sms-reply/{secret}",
                             data={"From": "+15550000000", "Body": "Random text from unknown number"})
    assert resp.status_code == 200
    db_session.expire_all()
    msg = db_session.query(SmsMessage).filter(SmsMessage.phone == "+15550000000").first()
    assert msg is not None
    assert msg.customer_id is None  # no matching customer, logged anyway
