# email_sender.py
# SMTP email sender with responsive inline Div3 table

import os
from pathlib import Path
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from bs4 import BeautifulSoup

# -------------------------------------------------------------------
# 1) Convert existing inline Div3 HTML to responsive email table
# -------------------------------------------------------------------
def inline_div3_to_responsive_table(inline_div3_html: str) -> str:
    """
    Convert inline_div3_html (from scraper) into
    an email-friendly, responsive table with small logos.
    """
    soup = BeautifulSoup(inline_div3_html, "html.parser")
    
    table_html = """
    <div style="max-width:600px; width:100%; overflow-x:auto;">
      <table style="width:100%; border-collapse:collapse; font-family:Arial,sans-serif; font-size:14px;">
        <tr>
          <th style="background:#0f172a; color:#e5e7eb; padding:6px 8px; border-bottom:1px solid #334155;">Team</th>
          <th style="background:#0f172a; color:#e5e7eb; padding:6px 8px; border-bottom:1px solid #334155;">W</th>
          <th style="background:#0f172a; color:#e5e7eb; padding:6px 8px; border-bottom:1px solid #334155;">Pts</th>
        </tr>
    """

    rows = soup.select("tr")
    for i, row in enumerate(rows):
        bg_color = "#0b1120" if i % 2 == 0 else "#111827"
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        logo_tag = row.find("img")
        logo_src = logo_tag.get("src") if logo_tag else ""

        team_name = cells[0].get_text(strip=True)
        W = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        Pts = cells[2].get_text(strip=True) if len(cells) > 2 else ""

        table_html += f"""
        <tr>
          <td style="background:{bg_color}; color:#e5e7eb; padding:6px 8px; border-bottom:1px solid #334155;">
            {'<img src="' + logo_src + '" width="28" height="28" style="width:28px;height:28px;border-radius:50%;object-fit:cover;vertical-align:middle;margin-right:8px;">' if logo_src else ''}
            {team_name}
          </td>
          <td style="background:{bg_color}; color:#e5e7eb; padding:6px 8px; border-bottom:1px solid #334155; text-align:center;">
            {W}
          </td>
          <td style="background:{bg_color}; color:#e5e7eb; padding:6px 8px; border-bottom:1px solid #334155; text-align:center;">
            {Pts}
          </td>
        </tr>
        """

    table_html += "</table></div>"
    return table_html

# -------------------------------------------------------------------
# 2) Wrap email body with responsive HTML
# -------------------------------------------------------------------
def wrap_body_with_email_html(body_html: str) -> str:
    """
    Wrap body in minimal HTML shell for email, include mobile responsiveness.
    """
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <style>
        @media only screen and (max-width: 480px) {{
          table, th, td {{
            font-size: 12px !important;
          }}
          img {{
            width: 20px !important;
            height: 20px !important;
          }}
        }}
      </style>
    </head>
    <body style="background:#020617; color:#e5e7eb; font-family:Arial,sans-serif; padding:20px; margin:0;">
      {body_html}
    </body>
    </html>
    """

# -------------------------------------------------------------------
# 3) Send email via SMTP
# -------------------------------------------------------------------
def send_report_email(receivers, subject: str, body_html: str, attachment_path: str | None = None) -> None:
    """
    Send an HTML email with optional attachment via SMTP.
    Environment variables required: SMTP_USER, SMTP_PASS
    """

    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").replace("\xa0", "").strip()
    if not smtp_user or not smtp_pass:
        raise RuntimeError("SMTP_USER and SMTP_PASS must be set in environment variables")

    if isinstance(receivers, str):
        receivers = [r.strip() for r in receivers.split(",") if r.strip()]

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = ", ".join(receivers)
    msg["Subject"] = subject

    # Fallback plain text + HTML alternative
    msg.attach(MIMEText("This email requires an HTML-compatible client.", "plain"))
    msg.attach(MIMEText(body_html, "html"))

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

    print("📧 Email sent successfully via SMTP")
