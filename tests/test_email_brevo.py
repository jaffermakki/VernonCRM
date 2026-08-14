"""
Tests for the Brevo HTTPS API email path — confirms send_plain_email and
send_email_receipt correctly dispatch to Brevo's API vs SMTP based on the
email_method setting, without actually hitting Brevo's real API (mocked).
"""
from unittest.mock import patch, MagicMock
from datetime import datetime

from app.notifications import send_plain_email, send_email_receipt


def _set(db_session, key, value):
    from app.main import set_setting
    set_setting(db_session, key, value)


def test_defaults_to_smtp_when_no_email_method_set(db_session):
    """Backward compatibility: shops that configured SMTP before this
    feature existed must keep working exactly as before, with no method
    explicitly chosen."""
    with patch("app.notifications._send_via_smtp") as mock_smtp, \
         patch("app.notifications._send_via_brevo_api") as mock_brevo:
        mock_smtp.return_value = (True, "sent")
        # No SMTP host configured either -> should fail with the SMTP
        # "not configured" message, NOT silently try Brevo.
        ok, msg = send_plain_email(db_session, "test@example.com", "Subject", "Body", _get_setting_helper(db_session))
        assert not ok
        assert "SMTP" in msg or "Email is not configured" in msg
        mock_brevo.assert_not_called()


def test_routes_to_brevo_api_when_configured(db_session):
    _set(db_session, "email_method", "brevo_api")
    from app.encryption import encrypt_value
    _set(db_session, "brevo_api_key", encrypt_value("fake-api-key-123"))
    _set(db_session, "brevo_from_email", "receipts@testshop.com")
    _set(db_session, "brevo_from_name", "Test Shop")

    with patch("app.notifications.httpx.post") as mock_post, \
         patch("app.notifications._send_via_smtp") as mock_smtp:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        ok, msg = send_plain_email(db_session, "customer@example.com", "Test Subject", "Test body", _get_setting_helper(db_session))

        assert ok, msg
        mock_smtp.assert_not_called()  # must not fall through to SMTP
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args.args[0] == "https://api.brevo.com/v3/smtp/email"
        assert call_args.kwargs["headers"]["api-key"] == "fake-api-key-123"
        assert call_args.kwargs["json"]["to"][0]["email"] == "customer@example.com"
        assert call_args.kwargs["json"]["sender"]["email"] == "receipts@testshop.com"


def test_brevo_api_missing_credentials_fails_clearly_without_calling_api(db_session):
    _set(db_session, "email_method", "brevo_api")
    # Deliberately leave brevo_api_key unset — and explicitly clear it,
    # since db_session is shared (session-scoped) across the whole test
    # file. An earlier test in this file sets a fake key; without this
    # reset, that leftover value silently makes this test pass for the
    # wrong reason (or fail, depending on test order) instead of
    # actually exercising the "nothing configured" path it's named for.
    _set(db_session, "brevo_api_key", "")
    _set(db_session, "brevo_from_email", "")
    _set(db_session, "brevo_from_name", "")

    with patch("app.notifications.httpx.post") as mock_post:
        ok, msg = send_plain_email(db_session, "test@example.com", "Subject", "Body", _get_setting_helper(db_session))
        assert not ok
        assert "not fully configured" in msg
        mock_post.assert_not_called()


def test_brevo_api_401_gives_a_clear_error_message(db_session):
    _set(db_session, "email_method", "brevo_api")
    from app.encryption import encrypt_value
    _set(db_session, "brevo_api_key", encrypt_value("bad-key"))
    _set(db_session, "brevo_from_email", "receipts@testshop.com")

    with patch("app.notifications.httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"message": "Key not found"}
        mock_post.return_value = mock_resp

        ok, msg = send_plain_email(db_session, "test@example.com", "Subject", "Body", _get_setting_helper(db_session))
        assert not ok
        assert "401" in msg or "Unauthorized" in msg


def test_email_receipt_uses_brevo_api_and_includes_html(db_session):
    _set(db_session, "email_method", "brevo_api")
    from app.encryption import encrypt_value
    _set(db_session, "brevo_api_key", encrypt_value("fake-key"))
    _set(db_session, "brevo_from_email", "receipts@testshop.com")
    _set(db_session, "shop_name", "Test Shop")

    class FakeLine:
        name = "Screen Repair"; qty = 1; price = 100.0; sku = "RPR-SCRN"; imei = ""
    class FakeInvoice:
        number = "INV-9999"; date = datetime(2026, 7, 18, 10, 0)
        subtotal = 100.0; discount = 0.0; tax_total = 13.0; total = 113.0
        loyalty_pts_used = 0; store_credit_used = 0.0
        tax_breakdown = '[{"label": "HST (13%)", "amount": 13.0}]'
        payment_method = "Card"; customer = None
        lines = [FakeLine()]

    with patch("app.notifications.httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_post.return_value = mock_resp

        ok, msg = send_email_receipt(db_session, FakeInvoice(), "customer@example.com", _get_setting_helper(db_session))
        assert ok, msg
        payload = mock_post.call_args.kwargs["json"]
        assert "htmlContent" in payload and "textContent" in payload
        assert "INV-9999" in payload["htmlContent"]


def _get_setting_helper(db_session):
    from app.main import get_setting as real_get_setting
    return lambda db, key, default="": real_get_setting(db_session, key, default)
