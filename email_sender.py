# email_sender.py (updated for clean inline table layout in email)

import os
from pathlib import Path
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# -------------------------------------------------------------------
# Simplified inline email CSS (tables only, inline styles applied)
# -------------------------------------------------------------------
INLINE_TABLE_CSS = {
    "table": "width:100%; border-collapse:collapse; font-family:Arial,sans-serif; font-size:14px;",
    "th": "background:#0f172a; color:#e5e7eb; padding:6px 8px; text-align:left; border-bottom:1px solid #334155;",
    "td_even": "background:#0b1120; color:#e5e7eb; padding:6px 8px; border-bottom:1px solid #334155;",
    "td_odd": "background:#111827; color:#e5e7eb; padding:6px 8px; border-bottom:1px solid #334155;",
}


def _wrap_body_with_table_html(body_html: str) -> str:
    """
    Wrap a simplified HTML table snippet in a full HTML shell with inline styles.
    """
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
</head>
<body style="background:#020617; color:#e5e7eb; padding:20px; margin:0; font-family:Arial,sans-serif;">
{body_html}
</body>
</html>
"""


def format_div3_table_for_email(div3_html: str) -> str:
    """
    Convert your inline Div 3 HTML into a simplified table with inline styles
    for proper email rendering.
    Assumes div3_html is a string with team rows.
    """
    # For simplicity, assume div3_html is already a table fragment like:
    # <tr><td>Team A</td><td>W</td><td>Pts</td></tr>
    # We'll wrap it with <table> and inline styles
    table_html = f'<table style="{INLINE_TABLE_CSS["table"]}">\n'
    table_html += (
        f'<tr>'
        f'<th style="{INLINE_TABLE_CSS["th"]}">Team</th>'
        f'<th style="{INLINE_TABLE_CSS["th"]}">W</th>'
        f'<th style="{INLINE_TABLE_CSS["th"]}">Pts</th>'
        f'</tr>\n'
    )

    # Add rows, alternating background colors
    rows = div3_html.split("\n")
    for i, row in enumerate(rows):
        style = INLINE_TABLE_CSS["td_even"] if i % 2 == 0 else INLINE_TABLE_CSS["td_odd"]
        # Assuming row is <tr><td>Team A</td><td>1</td><td>10</td></tr>
        row_clean = row.replace("<tr>", f'<tr style="{style}">')
        table_html += row_clean + "\n"

    table_html += "</table>\n"
    return table_html


def send_report_email(
    receivers,
    subject: str,
    body_html: str,
    attachment_path: str | None = None,
) -> None:
    """
    Send an HTML email with optional attachment via SMTP.
    Environment variables: SMTP_USER, SMTP_PASS
    """

    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").replace("\xa0", "").strip()
    if not smtp_user or not smtp_pass:
        raise RuntimeError("SMTP_USER and SMTP_PASS must be set in environment variables")

    if isinstance(receivers, str):
        receivers = [r.strip() for r in receivers.split(",") if r.strip()]

    # Create email
    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = ", ".join(receivers)
    msg["Subject"] = subject

    # Wrap Div3 table snippet for email body
    email_body = _wrap_body_with_table_html(body_html)

    # Fallback plain text + HTML alternative
    msg.attach(MIMEText("This email requires an HTML-compatible client.", "plain"))
    msg.attach(MIMEText(email_body, "html"))

    # Attach full HTML report if provided
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

    # Send email via SMTP
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, receivers, msg.as_string())

    print("📧 Email sent successfully via SMTP!")
