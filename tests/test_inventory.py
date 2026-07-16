"""
Inventory: suppliers, the purchase-order lifecycle (draft -> sent ->
received, with stock incrementing on receipt), and repair parts-tracking
(stock deducting on use, restoring on removal).
"""
from app.models import Product, Supplier, PurchaseOrder, Repair, RepairPart


def test_supplier_add_and_list(owner_client, db_session):
    resp = owner_client.post("/suppliers/add", data={
        "name": "Acme Parts Co", "contact_name": "Bob", "email": "bob@acme.test",
        "phone": "555-2000", "lead_time_days": "5",
    }, follow_redirects=False)
    assert resp.status_code == 303

    supplier = db_session.query(Supplier).filter(Supplier.name == "Acme Parts Co").first()
    assert supplier is not None
    assert supplier.active is True

    listing = owner_client.get("/suppliers")
    assert "Acme Parts Co" in listing.text


def test_supplier_management_blocked_for_cashier(cashier_client):
    resp = cashier_client.get("/suppliers", follow_redirects=False)
    assert resp.status_code == 403
    resp2 = cashier_client.post("/suppliers/add", data={"name": "Sneaky Supplier"}, follow_redirects=False)
    assert resp2.status_code == 403


def test_purchase_order_full_lifecycle_increments_stock(owner_client, db_session):
    supplier = Supplier(id="test-supplier-1", name="Lifecycle Supplier", active=True)
    product = Product(id="test-product-po", sku="PO-TEST-1", name="PO Test Widget",
                       category="ACCESSORY", price=20.0, cost=8.0, stock=3, reorder_threshold=5, reorder_qty=10)
    db_session.add_all([supplier, product])
    db_session.commit()

    starting_stock = product.stock

    resp = owner_client.post("/purchase-orders/add", data={
        "supplier_id": supplier.id, "notes": "Test PO",
        "product_id": [product.id], "qty": ["10"], "unit_cost": ["8.00"],
    }, follow_redirects=False)
    assert resp.status_code == 303
    po_id = resp.headers["location"].rsplit("/", 1)[-1]

    po = db_session.get(PurchaseOrder, po_id)
    assert po.status == "draft"
    assert len(po.lines) == 1
    assert po.lines[0].qty == 10

    send_resp = owner_client.post(f"/purchase-orders/{po_id}/send", follow_redirects=False)
    assert send_resp.status_code == 303
    db_session.refresh(po)
    assert po.status == "sent"

    line = po.lines[0]
    receive_resp = owner_client.post(f"/purchase-orders/{po_id}/receive", data={
        f"received_{line.id}": "10",
    }, follow_redirects=False)
    assert receive_resp.status_code == 303

    db_session.refresh(po)
    db_session.refresh(product)
    assert po.status == "received"
    assert product.stock == starting_stock + 10, "receiving a PO must add its quantity to stock"


def test_purchase_order_partial_receipt_only_adds_what_arrived(owner_client, db_session):
    supplier = Supplier(id="test-supplier-2", name="Partial Supplier", active=True)
    product = Product(id="test-product-partial", sku="PO-TEST-2", name="Partial Widget",
                       category="ACCESSORY", price=15.0, cost=6.0, stock=0, reorder_threshold=5, reorder_qty=10)
    db_session.add_all([supplier, product])
    db_session.commit()

    resp = owner_client.post("/purchase-orders/add", data={
        "supplier_id": supplier.id, "product_id": [product.id], "qty": ["20"], "unit_cost": ["6.00"],
    }, follow_redirects=False)
    po_id = resp.headers["location"].rsplit("/", 1)[-1]
    po = db_session.get(PurchaseOrder, po_id)
    owner_client.post(f"/purchase-orders/{po_id}/send")

    line = po.lines[0]
    owner_client.post(f"/purchase-orders/{po_id}/receive", data={f"received_{line.id}": "12"})  # only 12 of 20 arrived

    db_session.refresh(product)
    assert product.stock == 12, "only the actually-received quantity should be added, not the full order"


def test_repair_part_usage_deducts_and_removal_restores_stock(owner_client, db_session):
    product = Product(id="test-product-part", sku="PART-TEST-1", name="Test Screen",
                       category="ACCESSORY", price=80.0, cost=30.0, stock=5, reorder_threshold=1, reorder_qty=5)
    db_session.add(product)
    db_session.commit()

    owner_client.post("/repairs/add", data={
        "phone": "555-7777", "name": "Parts Test Customer", "device": "Parts Test Device",
        "issue": "Screen Replacement", "estimated_cost": "100",
    })
    repair = (db_session.query(Repair).filter(Repair.device == "Parts Test Device")
              .order_by(Repair.ticket_no.desc()).first())

    add_resp = owner_client.post(f"/repairs/{repair.id}/parts/add", data={
        "product_id": product.id, "qty": "2",
    }, follow_redirects=False)
    assert add_resp.status_code == 303

    db_session.refresh(product)
    assert product.stock == 3, "adding a part should deduct qty from stock immediately"

    part = db_session.query(RepairPart).filter(RepairPart.repair_id == repair.id).first()
    assert part is not None
    assert part.qty == 2
    assert part.unit_cost == 30.0  # cost snapshot at time of use

    detail = owner_client.get(f"/repairs/{repair.id}")
    assert "Test Screen" in detail.text

    remove_resp = owner_client.post(f"/repairs/{repair.id}/parts/{part.id}/remove", follow_redirects=False)
    assert remove_resp.status_code == 303

    db_session.refresh(product)
    assert product.stock == 5, "removing a part should restore the stock that was deducted"


def test_repair_part_cannot_exceed_available_stock(owner_client, db_session):
    product = Product(id="test-product-lowstock", sku="LOW-1", name="Scarce Part",
                       category="ACCESSORY", price=50.0, cost=20.0, stock=1, reorder_threshold=1, reorder_qty=5)
    db_session.add(product)
    db_session.commit()

    owner_client.post("/repairs/add", data={
        "phone": "555-6666", "name": "Stock Limit Customer", "device": "Stock Limit Device",
        "issue": "Battery Replacement", "estimated_cost": "50",
    })
    repair = (db_session.query(Repair).filter(Repair.device == "Stock Limit Device")
              .order_by(Repair.ticket_no.desc()).first())

    resp = owner_client.post(f"/repairs/{repair.id}/parts/add", data={
        "product_id": product.id, "qty": "5",  # only 1 in stock
    }, follow_redirects=True)
    assert "Only 1" in resp.text or "only 1" in resp.text.lower()

    db_session.refresh(product)
    assert product.stock == 1, "stock must not change when the requested quantity isn't available"
