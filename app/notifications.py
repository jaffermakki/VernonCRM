import smtplib
import ssl
import json
import base64
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
import httpx
from .encryption import decrypt_value


def _send_via_smtp(host: str, port: int, user: str, password: str, msg: MIMEText) -> tuple[bool, str]:
    """Shared low-level sender. Returns (success, message). Auto-selects
    SSL vs STARTTLS based on port, since using the wrong one for a given
    port is a common reason mail silently fails to send or arrives never."""
    try:
        if port == 465:
            # Port 465 = implicit TLS from the start of the connection.
            # Using regular SMTP+starttls() here (the previous behavior,
            # regardless of port) does not speak the protocol port 465
            # expects and can hang, time out, or be rejected by the server.
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as server:
                server.login(user, password)
                refused = server.send_message(msg)
        else:
            # Port 587 (or 25 with STARTTLS support) = plaintext connection
            # that upgrades to TLS via STARTTLS.
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(user, password)
                refused = server.send_message(msg)

        if refused:
            # send_message() returns a dict of {recipient: (code, reason)}
            # for any address the server didn't accept. The previous code
            # never checked this, so a server-side rejection of the
            # recipient still reported "sent successfully" back to staff.
            reasons = "; ".join(f"{addr}: {info}" for addr, info in refused.items())
            return False, f"Server rejected the recipient: {reasons}"
        return True, "Email accepted by the mail server."
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP login failed — check the username/password in Settings."
    except smtplib.SMTPRecipientsRefused as e:
        return False, f"Server refused the recipient address: {e}"
    except (smtplib.SMTPException, OSError, TimeoutError) as e:
        return False, f"Failed to send email: {e}"


def _from_address_warning(user: str, from_addr: str) -> str:
    """Flags the #1 real-world cause of 'sent successfully but never
    arrives': sending with a From address on a different domain than the
    authenticated SMTP account. Gmail/Outlook/etc. often accept the
    message at the SMTP level, then silently drop or spam-filter it on
    the receiving end because SPF/DKIM don't match. The SMTP protocol
    has no way to surface this to the sender — it just vanishes."""
    def domain(addr):
        return addr.split("@")[-1].lower().strip() if "@" in addr else ""
    if from_addr and user and domain(from_addr) != domain(user):
        return (f" Note: your From address ({from_addr}) is on a different domain than "
                f"your SMTP login ({user}) — many providers silently drop mail like this "
                f"due to SPF/DKIM mismatches. Set From Address to the same address as "
                f"SMTP Username in Settings, or leave From Address blank to use it automatically.")
    return ""


def _send_via_brevo_api(api_key: str, from_email: str, from_name: str, to_email: str,
                         subject: str, html_content: str = None, text_content: str = None) -> tuple[bool, str]:
    """Sends via Brevo's HTTPS transactional email API instead of SMTP.
    This is a genuinely different code path, not just an alternate
    credential type: it's a normal HTTPS POST on port 443, which is never
    blocked — unlike SMTP ports 25/465/587, which Railway and Render both
    block on their free tiers (the exact issue we hit earlier in this
    project). Requires the separate Brevo *API key* (Settings > SMTP & API
    > API Keys) — NOT the SMTP key used for the smtp-relay.brevo.com path;
    using one where the other belongs is a common mix-up."""
    payload = {
        "sender": {"name": from_name or from_email, "email": from_email},
        "to": [{"email": to_email}],
        "subject": subject,
    }
    if html_content:
        payload["htmlContent"] = html_content
    if text_content:
        payload["textContent"] = text_content
    if not html_content and not text_content:
        return False, "No email content provided."

    try:
        resp = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"},
            json=payload, timeout=15,
        )
    except httpx.RequestError as e:
        return False, f"Could not reach Brevo's API: {e}"

    if resp.status_code in (200, 201):
        return True, "Accepted by Brevo's API."
    try:
        detail = resp.json().get("message", resp.text)
    except Exception:
        detail = resp.text
    if resp.status_code == 401:
        return False, f"Brevo rejected the API key (401 Unauthorized): {detail}"
    return False, f"Brevo API error ({resp.status_code}): {detail}"


def _brevo_api_credentials(db, get_setting):
    """Shared credential lookup for the Brevo API path, used by both
    send_plain_email and send_email_receipt."""
    api_key = decrypt_value(get_setting(db, "brevo_api_key", ""))
    from_email = get_setting(db, "brevo_from_email", "") or get_setting(db, "smtp_from", "")
    from_name = get_setting(db, "brevo_from_name", "") or get_setting(db, "shop_name", "")
    return api_key, from_email, from_name


def send_plain_email(db, to_email: str, subject: str, body: str, get_setting) -> tuple[bool, str]:
    if get_setting(db, "email_method", "smtp") == "brevo_api":
        api_key, from_email, from_name = _brevo_api_credentials(db, get_setting)
        if not (api_key and from_email):
            return False, "Brevo API is not fully configured — set the API key and From address in Settings → Notifications."
        return _send_via_brevo_api(api_key, from_email, from_name, to_email, subject, text_content=body)

    host = get_setting(db, "smtp_host", "")
    port = get_setting(db, "smtp_port", "")
    user = get_setting(db, "smtp_user", "")
    password = decrypt_value(get_setting(db, "smtp_password", ""))
    from_addr = get_setting(db, "smtp_from", "") or user

    if not (host and port and user and password):
        return False, "Email is not configured — go to Settings → Notifications to set up SMTP."

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    ok, detail = _send_via_smtp(host, int(port), user, password, msg)
    if ok:
        return True, "Email accepted by the mail server." + _from_address_warning(user, from_addr)
    return False, detail


def _shop_logo_data_uri() -> str:
    """Embeds the actual logo bytes directly in the email HTML instead of
    linking to it by URL. A linked <img src="http://..."> only works if
    that URL is something the *recipient's* mail client can reach — which
    fails by design during local testing (request.base_url is something
    like http://127.0.0.1:8000/, meaningless outside that one machine),
    and can also break in production behind certain proxies/CDNs. Embedding
    removes that dependency entirely: the logo renders identically whether
    this is sent from a laptop on a home network or a live server.

    Known tradeoff: base64-embedded images render correctly in Gmail,
    Apple Mail, Outlook.com, Yahoo, and virtually every mobile client —
    the ones a repair shop's actual customers use — but desktop Outlook's
    older rendering engine sometimes doesn't display them. Full
    compatibility there would need CID-attached images instead, which is
    real added complexity for a client segment unlikely to show up in a
    walk-in retail customer's inbox.
    """
    try:
        logo_path = Path(__file__).resolve().parent.parent / "static" / "logo-dark.png"
        data = base64.b64encode(logo_path.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{data}"
    except OSError:
        return ""


def _receipt_html(shop_name, shop_address, shop_phone, invoice, province_label="", base_url=""):
    """Email-safe rebuild of the same 'warm paper' invoice look used on
    screen and in print (templates/invoice_detail.html) — same forest
    green / cream / gold palette, same layout, same copy. Previously this
    was a much plainer, differently-colored one-off that had drifted from
    what the invoice actually looks like; a customer comparing the two
    would reasonably think something was broken.

    Built with inline styles and table layouts rather than the app's
    normal CSS: most email clients (Outlook desktop especially) strip
    <style> blocks, ignore @import/<link> fonts entirely, and don't
    support CSS custom properties at all — none of which is true of a
    browser, so this can't just reuse the print template directly.
    """
    tax_lines = json.loads(invoice.tax_breakdown) if invoice.tax_breakdown else []
    F = "Arial,Helvetica,sans-serif"  # the email-safe stand-in for 'Inter'
    SERIF = "Georgia,'Times New Roman',serif"

    def totals_row(label, value, color="#6b6456", bold=False):
        w = "700" if bold else "400"
        return (
            f'<tr><td style="padding:4px 0;font-size:12.5px;color:{color};font-family:{F};font-weight:{w}">{label}</td>'
            f'<td style="padding:4px 0;font-size:12.5px;color:{color};text-align:right;font-family:{F};font-weight:{w}">{value}</td></tr>'
        )

    item_rows = "".join(
        f'<tr style="background:{"#f7f4ef" if i % 2 else "#fdfcf9"}">'
        f'<td style="padding:9px 12px;font-size:12.5px;color:#2c2c2c;font-weight:600;font-family:{F};border-bottom:1px solid #ede8df">'
        f'{l.name}'
        + (f'<div style="font-weight:400;font-size:10px;color:#888;margin-top:2px">IMEI/Serial: {l.imei}</div>' if l.imei else '')
        + '</td>'
        f'<td style="padding:9px 12px;font-size:11px;color:#888;font-family:monospace;border-bottom:1px solid #ede8df">{l.sku or "—"}</td>'
        f'<td style="padding:9px 12px;font-size:12.5px;color:#2c2c2c;text-align:center;font-family:{F};border-bottom:1px solid #ede8df">{l.qty}</td>'
        f'<td style="padding:9px 12px;font-size:12.5px;color:#2c2c2c;text-align:right;font-family:{F};border-bottom:1px solid #ede8df">${l.price:.2f}</td>'
        f'<td style="padding:9px 12px;font-size:12.5px;color:#2c2c2c;text-align:right;font-weight:700;font-family:{F};border-bottom:1px solid #ede8df">${l.price * l.qty:.2f}</td>'
        '</tr>'
        for i, l in enumerate(invoice.lines)
    )

    totals_rows = totals_row("Subtotal", f"${invoice.subtotal:.2f}")
    if invoice.discount > 0:
        totals_rows += totals_row("Discount", f"−${invoice.discount:.2f}", color="#c0392b")
    if invoice.loyalty_pts_used > 0:
        totals_rows += totals_row("Loyalty points redeemed", f"{invoice.loyalty_pts_used} pts", color="#c0392b")
    if invoice.store_credit_used > 0:
        totals_rows += totals_row("Store credit redeemed", f"−${invoice.store_credit_used:.2f}", color="#c0392b")
    for tl in tax_lines:
        totals_rows += totals_row(tl["label"], f'${tl["amount"]:.2f}')

    addr_line = f'{shop_address}<br/>' if shop_address else ""
    phone_line = f'{shop_phone}<br/>' if shop_phone else ""
    logo_url = _shop_logo_data_uri()
    logo_html = (f'<img src="{logo_url}" alt="{shop_name}" height="34" style="display:block;margin-bottom:8px;border:0"/>'
                 if logo_url else f'<div style="font-size:20px;font-weight:bold;color:#1e5c3a;font-family:{SERIF}">{shop_name}</div>')
    customer_name = invoice.customer.name if invoice.customer else "Walk-in Customer"
    tax_footer = f"Taxes per {province_label}" if province_label else ""

    return f"""\
<div style="background:#eee9df;padding:28px 12px;font-family:{SERIF}">
  <table role="presentation" style="max-width:600px;width:100%;margin:0 auto;background:#fdfcf9;border:1px solid #e8e2d9;border-collapse:collapse">
    <tr><td style="padding:34px 32px">

      <table role="presentation" style="width:100%;border-collapse:collapse;padding-bottom:18px;border-bottom:2px solid #1e5c3a">
        <tr>
          <td style="vertical-align:top">
            {logo_html}
            <div style="font-size:11px;color:#7a7060;font-family:{F};line-height:1.7">{addr_line}{phone_line}</div>
          </td>
          <td style="vertical-align:top;text-align:right">
            <div style="font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#1e5c3a;font-family:{F}">Invoice</div>
            <div style="font-size:23px;font-weight:bold;color:#1e5c3a;font-family:{SERIF}">{invoice.number}</div>
            <div style="font-size:11px;color:#7a7060;margin-top:6px;font-family:{F};line-height:1.7">
              Date: {invoice.date.strftime('%B %d, %Y')}<br/>{province_label}
            </div>
          </td>
        </tr>
      </table>

      <table role="presentation" style="width:100%;background:#f0f5f1;border:1px solid #c8dece;border-radius:8px;border-collapse:separate;margin-top:20px">
        <tr>
          <td style="padding:12px 8px;text-align:center;width:25%">
            <div style="font-size:9px;letter-spacing:1px;text-transform:uppercase;color:#5a8a6a;font-family:{F};font-weight:600">Invoice #</div>
            <div style="font-size:12.5px;font-weight:700;color:#1e3a28;font-family:{F}">{invoice.number}</div>
          </td>
          <td style="padding:12px 8px;text-align:center;width:25%">
            <div style="font-size:9px;letter-spacing:1px;text-transform:uppercase;color:#5a8a6a;font-family:{F};font-weight:600">Date</div>
            <div style="font-size:12.5px;font-weight:700;color:#1e3a28;font-family:{F}">{invoice.date.strftime('%b %d, %Y')}</div>
          </td>
          <td style="padding:12px 8px;text-align:center;width:25%">
            <div style="font-size:9px;letter-spacing:1px;text-transform:uppercase;color:#5a8a6a;font-family:{F};font-weight:600">Payment</div>
            <div style="font-size:12.5px;font-weight:700;color:#1e3a28;font-family:{F}">{invoice.payment_method}</div>
          </td>
          <td style="padding:12px 8px;text-align:center;width:25%">
            <div style="font-size:9px;letter-spacing:1px;text-transform:uppercase;color:#5a8a6a;font-family:{F};font-weight:600">Total (CAD)</div>
            <div style="font-size:15px;font-weight:700;color:#1e5c3a;font-family:{SERIF}">${invoice.total:.2f}</div>
          </td>
        </tr>
      </table>

      <table role="presentation" style="width:100%;background:#f8f5ee;border-collapse:collapse;margin-top:20px">
        <tr><td style="border-left:3px solid #1e5c3a;padding:12px 16px">
          <div style="font-size:9px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#1e5c3a;font-family:{F};margin-bottom:4px">Bill To</div>
          <div style="font-size:14px;font-weight:700;color:#1e3a28;font-family:{SERIF}">{customer_name}</div>
        </td></tr>
      </table>

      <table role="presentation" style="width:100%;border-collapse:collapse;margin-top:20px">
        <tr style="background:#1e5c3a">
          <th style="padding:9px 12px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.7px;text-transform:uppercase;color:#fff;font-family:{F}">Description</th>
          <th style="padding:9px 12px;text-align:left;font-size:10px;font-weight:600;letter-spacing:.7px;text-transform:uppercase;color:#fff;font-family:{F}">SKU</th>
          <th style="padding:9px 12px;text-align:center;font-size:10px;font-weight:600;letter-spacing:.7px;text-transform:uppercase;color:#fff;font-family:{F}">Qty</th>
          <th style="padding:9px 12px;text-align:right;font-size:10px;font-weight:600;letter-spacing:.7px;text-transform:uppercase;color:#fff;font-family:{F}">Unit Price</th>
          <th style="padding:9px 12px;text-align:right;font-size:10px;font-weight:600;letter-spacing:.7px;text-transform:uppercase;color:#fff;font-family:{F}">Amount</th>
        </tr>
        {item_rows}
      </table>

      <table role="presentation" style="width:100%;margin-top:16px">
        <tr><td style="width:55%">&nbsp;</td><td style="width:45%">
          <table role="presentation" style="width:100%;border-collapse:collapse">
            {totals_rows}
            <tr><td style="padding-top:10px;border-top:2px solid #b8964a;font-size:16px;font-weight:700;color:#1e3a28;font-family:{SERIF}">Total (CAD)</td>
                <td style="padding-top:10px;border-top:2px solid #b8964a;font-size:16px;font-weight:700;color:#1e3a28;text-align:right;font-family:{SERIF}">${invoice.total:.2f}</td></tr>
          </table>
        </td></tr>
      </table>

      <table role="presentation" style="width:100%;margin-top:24px;padding-top:16px;border-top:1px solid #c8dece;border-collapse:collapse">
        <tr>
          <td style="font-size:12px;color:#5a8a6a;font-style:italic;font-family:{SERIF}">Thank you for choosing {shop_name}</td>
          <td style="font-size:10.5px;color:#a89880;text-align:right;font-family:{F}">{tax_footer}</td>
        </tr>
      </table>
      <div style="text-align:center;margin-top:14px;padding:8px 0;border-top:1px solid #c8dece;font-size:12px;font-weight:700;letter-spacing:.5px;color:#1e3a28;font-family:{F}">
        NO REFUND — EXCHANGE ONLY
      </div>

    </td></tr>
  </table>
</div>"""


def send_email_receipt(db, invoice, to_email: str, get_setting, province_label: str = "", base_url: str = "") -> tuple[bool, str]:
    shop_name = get_setting(db, "shop_name", "Your Shop")
    shop_address = get_setting(db, "shop_address", "")
    shop_phone = get_setting(db, "shop_phone", "")
    tax_lines = json.loads(invoice.tax_breakdown) if invoice.tax_breakdown else []
    lines_text = "\n".join(f"{l.name} x{l.qty} — ${l.price * l.qty:.2f}" for l in invoice.lines)
    tax_text = "\n".join(f"{tl['label']}: ${tl['amount']:.2f}" for tl in tax_lines) or f"Tax: ${invoice.tax_total:.2f}"
    discount_line = f"Discount: -${invoice.discount:.2f}\n" if invoice.discount > 0 else ""
    text_body = (
        f"Receipt from {shop_name}\n\n"
        f"Invoice: {invoice.number}\n"
        f"Date: {invoice.date.strftime('%b %d, %Y %H:%M')}\n"
        f"Payment: {invoice.payment_method}\n\n"
        f"{lines_text}\n\n"
        f"Subtotal: ${invoice.subtotal:.2f}\n"
        f"{discount_line}"
        f"{tax_text}\n"
        f"Total: ${invoice.total:.2f}\n\n"
        f"Thank you for choosing {shop_name}\n"
        f"NO REFUND — EXCHANGE ONLY"
    )
    html_body = _receipt_html(shop_name, shop_address, shop_phone, invoice, province_label, base_url)
    subject = f"Your receipt from {shop_name} — {invoice.number}"

    if get_setting(db, "email_method", "smtp") == "brevo_api":
        api_key, from_email, from_name = _brevo_api_credentials(db, get_setting)
        if not (api_key and from_email):
            return False, "Brevo API is not fully configured — set the API key and From address in Settings → Notifications."
        ok, detail = _send_via_brevo_api(api_key, from_email, from_name or shop_name, to_email,
                                          subject, html_content=html_body, text_content=text_body)
        if ok:
            return True, "Receipt " + detail.lower() + " If it doesn't arrive within a few minutes, check spam/junk."
        return False, detail

    host = get_setting(db, "smtp_host", "")
    port = get_setting(db, "smtp_port", "")
    user = get_setting(db, "smtp_user", "")
    password = decrypt_value(get_setting(db, "smtp_password", ""))
    from_addr = get_setting(db, "smtp_from", "") or user

    if not (host and port and user and password):
        return False, "Email is not configured — go to Settings → Notifications to set up SMTP."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    ok, detail = _send_via_smtp(host, int(port), user, password, msg)
    if ok:
        warning = _from_address_warning(user, from_addr)
        base = "Receipt accepted by the mail server."
        if warning:
            return True, base + warning
        return True, base + " If it doesn't arrive within a few minutes, check spam/junk."
    return False, detail


def send_sms(db, to_phone: str, message: str, get_setting) -> tuple[bool, str]:
    sid = get_setting(db, "twilio_sid", "")
    token = decrypt_value(get_setting(db, "twilio_token", ""))
    from_phone = get_setting(db, "twilio_from", "")

    if not (sid and token and from_phone):
        return False, "SMS is not configured — go to Settings → Notifications to set up Twilio."

    try:
        resp = httpx.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(sid, token),
            data={"From": from_phone, "To": to_phone, "Body": message},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True, "SMS sent successfully."
        return False, f"Twilio error ({resp.status_code}): {resp.text[:200]}"
    except Exception as e:
        return False, f"Failed to send SMS: {e}"
