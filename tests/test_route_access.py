"""
Route access control — turns the manual security audit into permanent
regression tests. If any of these ever start failing, a future change
has silently reopened a gap we deliberately closed.
"""
import pytest


# (method, path, expected_status_for_cashier) — cashier is the lowest role
# that can still log in, so it's the most useful one to sweep broadly.
OWNER_MANAGER_ONLY_GET_ROUTES = [
    "/reports",
    "/reports/eod",
    "/export/csv/inventory",
    "/export/csv/customers",
    "/export/csv/invoices",
    "/export/csv/tax-report",
    "/export/csv/reorder",
    "/products/reorder",
    "/products/reorder/print",
    "/staff",
    "/audit",
    "/suppliers",
    "/purchase-orders",
]

OWNER_ONLY_GET_ROUTES = [
    "/settings",
]


@pytest.mark.parametrize("path", OWNER_MANAGER_ONLY_GET_ROUTES)
def test_owner_manager_only_routes_block_cashier(cashier_client, path):
    resp = cashier_client.get(path, follow_redirects=False)
    assert resp.status_code == 403, f"{path} should block cashiers, got {resp.status_code}"


@pytest.mark.parametrize("path", OWNER_MANAGER_ONLY_GET_ROUTES)
def test_owner_manager_only_routes_allow_manager(manager_client, path):
    resp = manager_client.get(path, follow_redirects=False)
    assert resp.status_code == 200, f"{path} should allow managers, got {resp.status_code}"


@pytest.mark.parametrize("path", OWNER_ONLY_GET_ROUTES)
def test_owner_only_routes_block_manager(manager_client, path):
    resp = manager_client.get(path, follow_redirects=False)
    assert resp.status_code == 403, f"{path} should block managers, got {resp.status_code}"


@pytest.mark.parametrize("path", OWNER_ONLY_GET_ROUTES)
def test_owner_only_routes_allow_owner(owner_client, path):
    resp = owner_client.get(path, follow_redirects=False)
    assert resp.status_code == 200, f"{path} should allow the owner, got {resp.status_code}"


def test_product_add_blocked_for_cashier(cashier_client):
    resp = cashier_client.post("/products/add", data={
        "sku": "HACK-1", "name": "Hacked Item", "price": "0.01", "cost": "0",
    }, follow_redirects=False)
    assert resp.status_code == 403


def test_product_add_allowed_for_manager(manager_client):
    resp = manager_client.post("/products/add", data={
        "sku": "TEST-SKU-1", "name": "Test Widget", "price": "9.99", "cost": "3.00", "stock": "10",
    }, follow_redirects=False)
    assert resp.status_code == 303  # redirect back to /products on success


def test_protected_routes_redirect_anonymous_to_login(anon_client):
    for path in ["/", "/pos", "/repairs", "/reports", "/staff", "/settings"]:
        resp = anon_client.get(path, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login", f"{path} should redirect anonymous users to /login"


def test_manager_cannot_edit_owner_account(manager_client, db_session):
    from app.models import Staff
    owner = db_session.query(Staff).filter(Staff.role == "owner").first()
    resp = manager_client.post(f"/staff/{owner.id}/edit", data={
        "name": owner.name, "role": "owner", "new_pin": "9999",
    }, follow_redirects=False)
    assert resp.status_code == 403


def test_manager_cannot_self_promote_to_owner(manager_client, db_session):
    from app.models import Staff
    manager = db_session.query(Staff).filter(Staff.id == "test-manager").first()
    resp = manager_client.post(f"/staff/{manager.id}/edit", data={
        "name": manager.name, "role": "owner",
    }, follow_redirects=False)
    assert resp.status_code == 403
    db_session.refresh(manager)
    assert manager.role == "manager", "role must not have changed despite the blocked request"


def test_manager_cannot_deactivate_owner(manager_client, db_session):
    from app.models import Staff
    owner = db_session.query(Staff).filter(Staff.role == "owner").first()
    resp = manager_client.post(f"/staff/{owner.id}/toggle", follow_redirects=False)
    assert resp.status_code == 403
    db_session.refresh(owner)
    assert owner.active is True


def test_products_page_renders_with_variant_groups(owner_client, db_session):
    """Regression test for a dict.items()-collision bug: the variant-group
    dict originally used the key 'items', which Jinja resolved to Python's
    built-in dict.items() method instead of the actual product list —
    same bug class as the earlier dashboard checklist crash. Renamed to
    'variants'; this confirms the page actually loads with real grouped
    products in the database, not just via an isolated template render."""
    from app.models import Product
    db_session.add_all([
        Product(id="vg-test-1", sku="VG-TEST-1", name="Clear Case — Model A", category="ACCESSORY",
                variant_group="Clear Case", price=15.0, cost=5.0, stock=5),
        Product(id="vg-test-2", sku="VG-TEST-2", name="Clear Case — Model B", category="ACCESSORY",
                variant_group="Clear Case", price=15.0, cost=5.0, stock=3),
    ])
    db_session.commit()

    resp = owner_client.get("/products")
    assert resp.status_code == 200
    assert "builtin_function_or_method" not in resp.text
    assert "Clear Case" in resp.text
    assert "2 variants" in resp.text


def test_pos_page_renders_with_variant_groups(owner_client, db_session):
    """Same coverage as above but for the POS variant-picker (Option B) —
    confirms the grouped tile, the variant picker's embedded JSON data,
    and a spanning-multiple-brands group all render without error."""
    from app.models import Product
    db_session.add_all([
        Product(id="pos-vg-1", sku="POS-VG-1", name="Clear Case — iPhone 15", category="ACCESSORY",
                subcategory="Apple", variant_group="POS Test Case", price=15.0, cost=5.0, stock=8),
        Product(id="pos-vg-2", sku="POS-VG-2", name="Clear Case — Galaxy S24", category="ACCESSORY",
                subcategory="Samsung", variant_group="POS Test Case", price=18.0, cost=6.0, stock=0),
    ])
    db_session.commit()

    resp = owner_client.get("/pos")
    assert resp.status_code == 200
    assert "builtin_function_or_method" not in resp.text
    assert "POS Test Case" in resp.text
    assert "2 options" in resp.text
    assert "POS-VG-1" in resp.text and "POS-VG-2" in resp.text  # embedded variant-picker data
    assert "$15.00" in resp.text and "18.00" in resp.text  # price range shown on the group tile
