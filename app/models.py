import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from .database import Base


def gen_id():
    return uuid.uuid4().hex[:12]


class Staff(Base):
    __tablename__ = "staff"
    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False, default="cashier")  # owner | manager | cashier | technician
    pin_hash = Column(String, nullable=False)
    active = Column(Boolean, default=True)


class Product(Base):
    __tablename__ = "products"
    id = Column(String, primary_key=True, default=gen_id)
    sku = Column(String, unique=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, default="")
    subcategory = Column(String, default="")  # "Brand" in the UI
    variant_group = Column(String, default="")  # e.g. "Clear Silicone Case" — groups model/color variants together for browsing, without changing how stock is tracked per-SKU
    price = Column(Float, default=0)
    cost = Column(Float, default=0)
    stock = Column(Integer, default=0)
    reorder_threshold = Column(Integer, default=5)  # flag for reorder when stock <= this
    reorder_qty = Column(Integer, default=10)        # suggested quantity to reorder


class Customer(Base):
    __tablename__ = "customers"
    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    phone = Column(String, default="")
    email = Column(String, default="")
    notes = Column(Text, default="")
    points = Column(Integer, default=0)
    store_credit = Column(Float, default=0)
    spent = Column(Float, default=0)
    last_visit = Column(String, default="")


class Repair(Base):
    __tablename__ = "repairs"
    id = Column(String, primary_key=True, default=gen_id)
    ticket_no = Column(Integer, default=1001)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True)
    device = Column(String, default="")
    issue = Column(String, default="")
    description = Column(Text, default="")
    status = Column(String, default="RECEIVED")
    estimated_cost = Column(Float, nullable=True)
    final_cost = Column(Float, nullable=True)
    warranty_days = Column(Integer, default=90)
    promised_by = Column(String, default="")
    technician_id = Column(String, ForeignKey("staff.id"), nullable=True)
    status_history = Column(Text, default="[]")  # JSON list of {status, note, date}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    customer = relationship("Customer")
    technician = relationship("Staff")


class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(String, primary_key=True, default=gen_id)
    number = Column(String, unique=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True)
    staff_id = Column(String, ForeignKey("staff.id"), nullable=True)
    repair_id = Column(String, ForeignKey("repairs.id"), nullable=True)
    payment_method = Column(String, default="Cash")
    subtotal = Column(Float, default=0)
    discount = Column(Float, default=0)
    loyalty_pts_used = Column(Integer, default=0)
    store_credit_used = Column(Float, default=0)
    tendered = Column(Float, default=0)
    change_given = Column(Float, default=0)
    tax_breakdown = Column(Text, default="")  # JSON string of [{label, amount}]
    tax_total = Column(Float, default=0)
    total = Column(Float, default=0)
    refunded = Column(Boolean, default=False)
    date = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer")
    staff = relationship("Staff")
    repair = relationship("Repair")
    lines = relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan")


class HeldCart(Base):
    __tablename__ = "held_carts"
    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, default="Held Cart")
    cart_json = Column(Text, default="[]")
    customer_id = Column(String, nullable=True)
    disc_mode = Column(String, default="$")
    disc_value = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id = Column(String, primary_key=True, default=gen_id)
    invoice_id = Column(String, ForeignKey("invoices.id"))
    product_id = Column(String, nullable=True)
    name = Column(String)
    sku = Column(String, default="")
    qty = Column(Integer, default=1)
    price = Column(Float, default=0)

    invoice = relationship("Invoice", back_populates="lines")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(String, primary_key=True, default=gen_id)
    ts = Column(DateTime, default=datetime.utcnow)
    staff_id = Column(String, nullable=True)
    staff_name = Column(String, default="System")
    action = Column(String)
    detail = Column(Text, default="")


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(Text)


class LoginState(Base):
    """Tracks shared PIN-pad lockout state (mirrors the brute-force
    protection from the JS version) — single row, id='global'."""
    __tablename__ = "login_state"
    id = Column(String, primary_key=True, default="global")
    fail_count = Column(Integer, default=0)
    lock_until = Column(DateTime, nullable=True)


class CashSession(Base):
    __tablename__ = "cash_sessions"
    id = Column(String, primary_key=True, default=gen_id)
    date = Column(String)  # YYYY-MM-DD — one session per day, like the original
    open_float = Column(Float, default=0)
    expected = Column(Float, default=0)
    actual = Column(Float, default=0)
    difference = Column(Float, default=0)
    card_expected = Column(Float, default=0)   # what the CRM recorded as card/debit sales
    card_batch = Column(Float, default=0)      # what the bank terminal's batch/settlement report shows
    card_difference = Column(Float, default=0)
    notes = Column(Text, default="")
    closed_at = Column(DateTime, default=datetime.utcnow)
    closed_by_id = Column(String, nullable=True)
    closed_by_name = Column(String, default="")


class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String)
    contact_name = Column(String, default="")
    email = Column(String, default="")
    phone = Column(String, default="")
    lead_time_days = Column(Integer, default=7)
    notes = Column(Text, default="")
    active = Column(Boolean, default=True)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    id = Column(String, primary_key=True, default=gen_id)
    number = Column(String, default="")
    supplier_id = Column(String, ForeignKey("suppliers.id"), nullable=True)
    status = Column(String, default="draft")  # draft, sent, received, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    received_at = Column(DateTime, nullable=True)
    created_by_name = Column(String, default="")
    notes = Column(Text, default="")

    supplier = relationship("Supplier")
    lines = relationship("PurchaseOrderLine", back_populates="po", cascade="all, delete-orphan")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id = Column(String, primary_key=True, default=gen_id)
    po_id = Column(String, ForeignKey("purchase_orders.id"))
    product_id = Column(String, ForeignKey("products.id"), nullable=True)
    name = Column(String, default="")
    sku = Column(String, default="")
    qty = Column(Integer, default=1)
    unit_cost = Column(Float, default=0)
    received_qty = Column(Integer, default=0)

    po = relationship("PurchaseOrder", back_populates="lines")


class RepairPart(Base):
    """A product consumed on a repair job — deducts stock immediately when
    added and lets the repair's true margin (charge minus parts cost) be
    calculated, instead of parts silently vanishing from inventory counts."""
    __tablename__ = "repair_parts"
    id = Column(String, primary_key=True, default=gen_id)
    repair_id = Column(String, ForeignKey("repairs.id"))
    product_id = Column(String, ForeignKey("products.id"), nullable=True)
    name = Column(String, default="")
    qty = Column(Integer, default=1)
    unit_cost = Column(Float, default=0)  # snapshot of product cost at time of use
    added_at = Column(DateTime, default=datetime.utcnow)

    repair = relationship("Repair", backref="parts")
