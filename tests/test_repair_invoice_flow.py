"""
End-to-end test of the repair -> payment -> invoice flow: create a ticket,
walk it through the pipeline to Ready, charge & collect at the register,
then verify the invoice is linked back to the ticket and the ticket was
auto-marked Collected — the whole point of that feature.
"""
from app.models import Repair, Invoice


def _create_repair(owner_client, phone="555-9999", device="Test Phone X", issue="Screen Replacement"):
    owner_client.post("/repairs/add", data={
        "phone": phone, "name": "Test Customer", "device": device, "issue": issue,
        "description": "cracked screen", "estimated_cost": "150.00", "warranty_days": "90",
    }, follow_redirects=False)


def _advance_to_ready(owner_client, db_session, repair_id):
    # RECEIVED -> DIAGNOSED -> WAITING -> IN_PROGRESS -> READY
    for _ in range(4):
        owner_client.post(f"/repairs/{repair_id}/advance", data={"note": ""}, follow_redirects=False)


def test_charge_and_collect_links_invoice_and_marks_collected(owner_client, db_session):
    _create_repair(owner_client, phone="555-8001", device="Regression Test Phone")
    repair = (db_session.query(Repair)
              .filter(Repair.device == "Regression Test Phone")
              .order_by(Repair.ticket_no.desc()).first())
    assert repair is not None
    assert repair.status == "RECEIVED"

    _advance_to_ready(owner_client, db_session, repair.id)
    db_session.refresh(repair)
    assert repair.status == "READY"

    # Charge & Collect sends the repair to the register
    resp = owner_client.post(f"/repairs/{repair.id}/charge", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/pos"

    pos_page = owner_client.get("/pos")
    assert f"Repair #{repair.ticket_no}" in pos_page.text

    # Complete the sale
    checkout = owner_client.post("/pos/checkout", data={
        "payment_method": "Cash", "tendered": "200.00",
    }, follow_redirects=False)
    assert checkout.status_code == 303
    assert checkout.headers["location"].startswith("/invoices/")

    db_session.expire_all()
    updated_repair = db_session.get(Repair, repair.id)
    assert updated_repair.status == "COLLECTED", "repair should auto-advance to Collected once paid"

    invoice = db_session.query(Invoice).filter(Invoice.repair_id == repair.id).first()
    assert invoice is not None, "the invoice must be linked back to the repair"
    # $150 repair charge + Ontario HST (13%, the seeded default province) = $169.50
    assert invoice.total == 169.50

    # And the reverse link: the repair detail page should list this invoice
    detail = owner_client.get(f"/repairs/{repair.id}")
    assert invoice.number in detail.text


def test_manual_advance_to_collected_without_charging_still_works(owner_client, db_session):
    """The no-charge path (e.g. warranty rework) must keep working —
    Charge & Collect is additive, not a replacement for manual advancement."""
    _create_repair(owner_client, phone="555-8002", device="Warranty Rework Phone")
    repair = (db_session.query(Repair)
              .filter(Repair.device == "Warranty Rework Phone")
              .order_by(Repair.ticket_no.desc()).first())

    for _ in range(6):  # all the way through to COLLECTED, no payment involved
        owner_client.post(f"/repairs/{repair.id}/advance", data={"note": "no charge"}, follow_redirects=False)

    db_session.refresh(repair)
    assert repair.status == "COLLECTED"

    invoice = db_session.query(Invoice).filter(Invoice.repair_id == repair.id).first()
    assert invoice is None, "no invoice should exist for a repair collected without charging"


def test_checkout_recovers_from_invoice_number_collision(owner_client, db_session):
    """Simulates two checkouts racing for the same invoice number: pre-insert
    an invoice using the number the counter is about to hand out next, then
    check out for real. The checkout must still succeed — with a different,
    unique number — instead of crashing with a raw database error."""
    from app.models import Setting, Product
    from app.main import get_setting

    prefix = get_setting(db_session, "invoice_prefix", "INV")
    counter = int(get_setting(db_session, "invoice_counter", "1000"))
    colliding_number = f"{prefix}-{counter}"

    db_session.add(Invoice(number=colliding_number, staff_id=None, payment_method="Cash",
                            subtotal=1, tax_total=0, total=1))
    db_session.commit()

    product = db_session.query(Product).filter(Product.stock > 0).first()
    owner_client.post("/pos/clear")
    owner_client.post("/pos/add-custom", data={"product_id": product.id, "custom_price": "10.00"})

    resp = owner_client.post("/pos/checkout", data={
        "payment_method": "Cash", "tendered": "20.00",
    }, follow_redirects=False)

    assert resp.status_code == 303, "checkout must succeed despite the collision, not 500"
    assert resp.headers["location"].startswith("/invoices/")
    new_invoice_id = resp.headers["location"].rsplit("/", 1)[-1]

    db_session.expire_all()
    new_invoice = db_session.get(Invoice, new_invoice_id)
    assert new_invoice.number != colliding_number, "must not have reused the colliding number"
    assert new_invoice.number.startswith(prefix)

    owner_client.post("/pos/clear")
