# email_sender.py
#
# SMTP version:
#   - send_report_email(): sends HTML email with optional attachment
#   - wraps body HTML in CSS shell (same as before)
#   - uses environment variables SMTP_USER / SMTP_PASS
#   - no Google OAuth required

import os
from pathlib import Path
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# -------------------------------------------------------------------
# CSS used for the inline email (matches the full HTML report look)
# -------------------------------------------------------------------
INLINE_EMAIL_CSS = """
<style>
body {
  background:#020617;
  color:#e5e7eb;
  font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  padding:20px;
  margin:0;
}
h1 {
  margin:0 0 8px 0;
}
h2 {
  margin:16px 0 8px 0;
}
p {
  margin:0 0 12px 0;
  color:#9ca3af;
}
table {
  width:100%;
  border-collapse:collapse;
  font-size:14px;
}
th,td {
  padding:6px 8px;
  border-bottom:1px solid #334155;
}
thead {
  background:#0f172a;
}
tbody tr:nth-child(even) { background:#0b1120; }
tbody tr:nth-child(odd)  { background:#111827; }
td.form-cell { max-width:360px; }
.gd-pos { color:#22c55e; font-weight:700; }
.gd-neg { color:#ef4444; font-weight:700; }
.gd-zero { color:#9ca3af; }
.next-main { font-weight:700; display:block; }
.next-meta { color:#9ca3af; font-size:12px; display:block; }
.pos { color:#9ca3af; }
.pts { font-weight:700; }
.team-cell {
  display:flex;
  align-items:center;
  gap:8px;
}
.team-logo {
  width:28px;
  height:28px;
  border-radius:50%;
  object-fit:cover;
  background:#0f172a;
}
.division-panel {
  margin-top:8px;
}
</style>
"""


def _wrap_body_with_css(body_html: str) -> str:
    """Wrap body HTML with CSS shell if not already a full HTML doc"""
    lower = body_html.strip().lower()
    if lower.startswith("<!doctype") or lower.startswith("<html"):
        return body_html
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
{INLINE_EMAIL_CSS}
</head>
<body>
{body_html}
</body>
</html>
"""


def send_report_email(
    receivers,
    subject: str,
    body_html: str,
    attachment_path: str | None = None,
) -> None:
    """
    Send an HTML email with optional attachment via SMTP.

    Environment variables:
      SMTP_USER = Gmail address
      SMTP_PASS = Gmail App Password
    """

    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    if not smtp_user or not smtp_pass:
        raise RuntimeError("SMTP_USER and SMTP_PASS must be set in environment variables")

    if isinstance(receivers, str):
        receivers = [r.strip() for r in receivers.split(",") if r.strip()]

    # Create email
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = ", ".join(receivers)
    msg["Subject"] = subject

    # Wrap body with CSS
    html_with_css = _wrap_body_with_css(body_html)

    # Fallback plain text + HTML alternative
    msg.attach(MIMEText("This email requires an HTML-compatible client.", "plain"))
    msg.attach(MIMEText(html_with_css, "html"))

    # Attach HTML file if provided
    if attachment_path:
        p = Path(attachment_path)
        if p.exists():
            with open(p, "rb") as f:
                attachment = MIMEApplication(f.read(), _subtype="html")
                attachment.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=p.name,
                )
                msg.attach(attachment)
        else:
            print(f"⚠ Attachment not found: {attachment_path}")

    # Send email via Gmail SMTP
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, receivers, msg.as_string())

    print("📧 Email sent successfully via SMTP!")
