import smtplib
import ssl
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


def send_plain_email(db, to_email: str, subject: str, body: str, get_setting) -> tuple[bool, str]:
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


def _receipt_html(shop_name, shop_address, shop_phone, invoice):
    rows = "".join(
        f'<tr><td style="padding:8px 0;border-bottom:1px solid #e8e2d9;color:#2c2c2c">{l.name} '
        f'<span style="color:#9a9284">×{l.qty}</span></td>'
        f'<td style="padding:8px 0;border-bottom:1px solid #e8e2d9;text-align:right;color:#2c2c2c">'
        f'${l.price * l.qty:.2f}</td></tr>'
        for l in invoice.lines
    )
    addr_line = f'<div style="color:#7a7060;font-size:12px;margin-top:4px">{shop_address}</div>' if shop_address else ""
    phone_line = f'<div style="color:#7a7060;font-size:12px">{shop_phone}</div>' if shop_phone else ""
    return f"""\
<div style="background:#f4f1ea;padding:28px 12px;font-family:Georgia,'Times New Roman',serif">
  <div style="max-width:520px;margin:0 auto;background:#fdfcf9;border:1px solid #e8e2d9;padding:32px 30px">
    <div style="border-bottom:2px solid #1e5c3a;padding-bottom:16px;margin-bottom:20px">
      <div style="font-size:20px;font-weight:bold;color:#1e5c3a">{shop_name}</div>
      {addr_line}{phone_line}
    </div>
    <div style="font-size:13px;color:#7a7060;margin-bottom:4px">Receipt for</div>
    <div style="font-size:16px;color:#2c2c2c;margin-bottom:20px">Invoice {invoice.number} &nbsp;·&nbsp; {invoice.date.strftime('%b %d, %Y')}</div>
    <table style="width:100%;border-collapse:collapse;font-size:13px">{rows}</table>
    <table style="width:100%;margin-top:14px;font-size:13px">
      <tr><td style="color:#7a7060;padding:2px 0">Subtotal</td><td style="text-align:right;color:#2c2c2c">${invoice.subtotal:.2f}</td></tr>
      <tr><td style="color:#7a7060;padding:2px 0">Discount</td><td style="text-align:right;color:#2c2c2c">-${invoice.discount:.2f}</td></tr>
      <tr><td style="color:#7a7060;padding:2px 0">Tax</td><td style="text-align:right;color:#2c2c2c">${invoice.tax_total:.2f}</td></tr>
      <tr><td style="color:#1e5c3a;font-weight:bold;font-size:16px;padding-top:8px;border-top:1px solid #e8e2d9">Total</td>
          <td style="text-align:right;color:#1e5c3a;font-weight:bold;font-size:16px;padding-top:8px;border-top:1px solid #e8e2d9">${invoice.total:.2f}</td></tr>
    </table>
    <div style="margin-top:26px;padding-top:16px;border-top:1px solid #e8e2d9;text-align:center;color:#9a9284;font-size:12px">
      Thank you for your business!
    </div>
  </div>
</div>"""


def send_email_receipt(db, invoice, to_email: str, get_setting) -> tuple[bool, str]:
    host = get_setting(db, "smtp_host", "")
    port = get_setting(db, "smtp_port", "")
    user = get_setting(db, "smtp_user", "")
    password = decrypt_value(get_setting(db, "smtp_password", ""))
    from_addr = get_setting(db, "smtp_from", "") or user

    if not (host and port and user and password):
        return False, "Email is not configured — go to Settings → Notifications to set up SMTP."

    shop_name = get_setting(db, "shop_name", "Your Shop")
    shop_address = get_setting(db, "shop_address", "")
    shop_phone = get_setting(db, "shop_phone", "")
    lines_text = "\n".join(f"{l.name} x{l.qty} — ${l.price * l.qty:.2f}" for l in invoice.lines)
    text_body = (
        f"Receipt from {shop_name}\n\n"
        f"Invoice: {invoice.number}\n"
        f"Date: {invoice.date.strftime('%b %d, %Y %H:%M')}\n\n"
        f"{lines_text}\n\n"
        f"Subtotal: ${invoice.subtotal:.2f}\n"
        f"Discount: ${invoice.discount:.2f}\n"
        f"Tax: ${invoice.tax_total:.2f}\n"
        f"Total: ${invoice.total:.2f}\n\n"
        f"Thank you for your business!"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your receipt from {shop_name} — {invoice.number}"
    msg["From"] = from_addr
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(_receipt_html(shop_name, shop_address, shop_phone, invoice), "html"))

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
