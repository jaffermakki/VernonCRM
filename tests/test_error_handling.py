"""
Regression coverage for a real bug caught during a UI sweep: hitting
/customers/<bogus-id> crashed with a raw, unstyled "Internal Server Error"
instead of a graceful redirect. invoice_detail and repair_detail had the
exact same gap — db.get() returning None, then used directly in a
template with no check. layaway_detail and product_edit_page already had
the right guard; these three didn't.

Also covers the new catch-all exception handler, added as a safety net
for whatever the *next* unguarded case turns out to be.
"""
from app.main import app
from fastapi import Request


def test_customer_detail_with_bogus_id_redirects_not_crashes(owner_client):
    resp = owner_client.get("/customers/this-id-does-not-exist", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/customers"


def test_invoice_detail_with_bogus_id_redirects_not_crashes(owner_client):
    resp = owner_client.get("/invoices/this-id-does-not-exist", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/invoices"


def test_repair_detail_with_bogus_id_redirects_not_crashes(owner_client):
    resp = owner_client.get("/repairs/this-id-does-not-exist", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/repairs"


# ── The catch-all handler itself ────────────────────────────────────────
# The three fixes above close the only unguarded cases that existed in the
# app today — which means there's no longer a real route left to trigger
# an unhandled exception through. To test the handler itself rather than
# just "no known route crashes right now", a route that deliberately
# raises is registered directly on the same `app` the tests already run
# against. It's a fixed, unique path that doesn't collide with anything
# real, and it stays registered for the rest of the test session, which is
# harmless — it's not reachable by anything except a test that names it.
@app.get("/__test_trigger_unhandled_exception__")
def _trigger_unhandled_exception(request: Request):
    raise RuntimeError("deliberate failure for test_error_handling.py")


def test_unhandled_exception_returns_styled_500_not_a_raw_crash(seed_roles):
    # TestClient's default raise_server_exceptions=True re-raises into the
    # test for easier debugging — useful everywhere else, but it means it
    # wouldn't actually exercise the exception handler at all here; it'd
    # just show the exception propagating past it. A real deployment
    # (Uvicorn) always goes through the handler, so this uses a client
    # configured the same way to test the real behavior.
    from starlette.testclient import TestClient
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/login", data={"pin": seed_roles["owner"]}, follow_redirects=False)
    assert resp.status_code == 303

    resp = client.get("/__test_trigger_unhandled_exception__")
    assert resp.status_code == 500
    assert "Something went wrong" in resp.text
    # Must not leak the exception message or a raw traceback to the client.
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text
    assert "test_error_handling.py" not in resp.text
