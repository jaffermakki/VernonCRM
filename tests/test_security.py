"""
Security-question gate on PIN changes, and the Forgot PIN recovery flow
(intentionally scoped to Owner accounts only).
"""
from app.models import Staff


def _configure_security_question(owner_client, question="What street did you grow up on?", answer="Maple"):
    resp = owner_client.get("/settings")
    assert resp.status_code == 200
    resp2 = owner_client.post("/settings", data={
        "shop_name": "TechPro+ Test", "province": "ON", "invoice_prefix": "INV",
        "points_per_dollar": "1", "points_redeem_rate": "100", "digest_hour": "21",
        "security_question": question, "security_answer": answer,
    }, follow_redirects=False)
    assert resp2.status_code == 303


def test_pin_change_blocked_with_wrong_security_answer(owner_client, db_session):
    _configure_security_question(owner_client, answer="Maple")
    cashier = db_session.query(Staff).filter(Staff.id == "test-cashier").first()

    resp = owner_client.post(f"/staff/{cashier.id}/edit", data={
        "name": cashier.name, "role": "cashier", "new_pin": "5555", "security_answer": "WrongAnswer",
    }, follow_redirects=True)
    assert "Incorrect security answer" in resp.text

    # PIN must be unchanged — verify the OLD pin still logs in
    from starlette.testclient import TestClient
    from app.main import app
    check_client = TestClient(app)
    old_login = check_client.post("/login", data={"pin": "3333"}, follow_redirects=False)
    assert old_login.status_code == 303
    assert old_login.headers["location"] == "/"


def test_pin_change_succeeds_with_correct_security_answer(owner_client, db_session):
    _configure_security_question(owner_client, answer="Maple")
    technician = db_session.query(Staff).filter(Staff.id == "test-technician").first()

    resp = owner_client.post(f"/staff/{technician.id}/edit", data={
        "name": technician.name, "role": "technician", "new_pin": "6789", "security_answer": "maple",  # case-insensitive
    }, follow_redirects=False)
    assert resp.status_code == 303

    from starlette.testclient import TestClient
    from app.main import app
    check_client = TestClient(app)
    new_login = check_client.post("/login", data={"pin": "6789"}, follow_redirects=False)
    assert new_login.status_code == 303
    assert new_login.headers["location"] == "/"

    # restore original PIN so other tests relying on "4444" still pass
    owner_client.post(f"/staff/{technician.id}/edit", data={
        "name": technician.name, "role": "technician", "new_pin": "4444", "security_answer": "maple",
    })


def test_forgot_pin_only_offers_owner_accounts(owner_client, anon_client, db_session):
    _configure_security_question(owner_client, answer="Maple")
    owner = db_session.query(Staff).filter(Staff.role == "owner").first()
    resp = anon_client.get("/forgot-pin")
    assert resp.status_code == 200
    assert f'value="{owner.id}"' in resp.text  # the actual owner IS a selectable option
    assert "Test Manager" not in resp.text  # non-owner accounts must not be selectable
    assert "Test Cashier" not in resp.text
    assert "Test Technician" not in resp.text


def test_forgot_pin_cannot_target_a_non_owner_account_directly(owner_client, anon_client, db_session):
    """Even if someone crafts a raw POST with a non-owner staff_id, the
    server must reject it — the page only hiding the option isn't enough."""
    _configure_security_question(owner_client, answer="Maple")
    cashier = db_session.query(Staff).filter(Staff.id == "test-cashier").first()

    resp = anon_client.post("/forgot-pin", data={
        "staff_id": cashier.id, "security_answer": "Maple", "new_pin": "1111", "confirm_pin": "1111",
    }, follow_redirects=True)
    assert "recovered this way" in resp.text  # avoid the apostrophe: Jinja correctly escapes can't -> can&#39;t

    db_session.refresh(cashier)
    from app.auth import verify_pin
    assert not verify_pin("1111", cashier.pin_hash), "cashier PIN must not have changed"


def test_forgot_pin_resets_owner_with_correct_answer(owner_client, anon_client, db_session):
    _configure_security_question(owner_client, answer="Maple")
    owner = db_session.query(Staff).filter(Staff.role == "owner").first()

    resp = anon_client.post("/forgot-pin", data={
        "staff_id": owner.id, "security_answer": "Maple", "new_pin": "5678", "confirm_pin": "5678",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"

    login_check = anon_client.post("/login", data={"pin": "5678"}, follow_redirects=False)
    assert login_check.status_code == 303
    assert login_check.headers["location"] == "/"

    # restore original owner PIN for any other test relying on "1234"
    anon_client.post("/forgot-pin", data={
        "staff_id": owner.id, "security_answer": "Maple", "new_pin": "1234", "confirm_pin": "1234",
    })
