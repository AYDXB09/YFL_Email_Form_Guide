import base64
import mimetypes
from email.message import EmailMessage
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


# --------------------------------------------------------------------
# 1) Load Gmail Credentials
# --------------------------------------------------------------------
def get_gmail_service(token_path="gmail_token.json"):
    creds = Credentials.from_authorized_user_file(
        token_path,
        scopes=["https://www.googleapis.com/auth/gmail.send"]
    )
    return build("gmail", "v1", credentials=creds)


# --------------------------------------------------------------------
# 2) Build Inline Email HTML (Div 3 Only)
# --------------------------------------------------------------------
def build_inline_html(div3_html: str) -> str:
    """
    Wraps the DIV3 HTML inside a full email-safe HTML template + CSS.
    """

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
<title>YFL Weekly Form Guide</title>

<style>

body {{
  background: #0f172a;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  color: #f8fafc;
  padding: 20px;
}}

h2 {{
  margin-top: 0;
  font-size: 26px;
  font-weight: 700;
  color: #ffffff;
}}

table {{
  width: 100%;
  border-collapse: collapse;
  background: #020617;
  margin-top: 15px;
}}

thead th {{
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
  padding: 8px 6px;
  border-bottom: 1px solid #1e293b;
  text-align: left;
}}

tbody td {{
  padding: 10px 6px;
  border-bottom: 1px solid #1e293b;
  font-size: 14px;
}}

.team-cell {{
  display: flex;
  align-items: center;
  gap: 8px;
}}

.team-logo {{
  width: 28px;
  height: 28px;
  border-radius: 4px;
  object-fit: contain;
  background: #1e293b;
}}

.gd-pos {{ color: #22c55e; font-weight: 700; }}
.gd-neg {{ color: #ef4444; font-weight: 700; }}
.pts {{ font-weight: 700; color: #e2e8f0; }}

.form-cell {{
  display: flex;
  align-items: center;
  gap: 4px;
}}

.next-cell {{
  display: flex;
  flex-direction: column;
}}

.next-main {{
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
}}

.next-meta {{
  font-size: 11px;
  color: #94a3b8;
}}

</style>
</head>

<body>

<h1 style="font-size:28px;font-weight:700;margin-bottom:5px;">
  YFL Dubai — U11 Weekly Form Guide
</h1>

<p style="color:#cbd5e1;font-size:14px;margin-bottom:12px;">
  This email contains the full **U11 Division 3** table inline.<br/>
  For Divisions 1–3, open the attached HTML file.
</p>

{div3_html}

</body>
</html>
"""


# --------------------------------------------------------------------
# 3) Build the full email with attachment
# --------------------------------------------------------------------
def build_email_html_with_attachment(
    sender: str,
    receivers: list[str],
    inline_html: str,
    attachment_html: str,
    attachment_filename="yfl_u11_form_guide.html"
):
    msg = EmailMessage()
    msg["To"] = ", ".join(receivers)
    msg["From"] = sender
    msg["Subject"] = "YFL Weekly Form Guide — U11 Div 3 (Inline) + All Divisions attached"

    # Inline HTML body
    msg.set_content("Your email client does not support HTML.", subtype="plain")
    msg.add_alternative(inline_html, subtype="html")

    # Attachment
    msg.add_attachment(
        attachment_html.encode("utf-8"),
        maintype="text",
        subtype="html",
        filename=attachment_filename
    )

    return msg


# --------------------------------------------------------------------
# 4) Send Email
# --------------------------------------------------------------------
def send_email(
    div3_html: str,
    full_html: str,
    sender_email: str,
    receivers: list[str],
    token_path="gmail_token.json"
):
    """
    Sends ONE email:
      - Inline HTML = Div 3 table
      - Attachment = Full multi-division HTML
    """
    service = get_gmail_service(token_path)

    inline_email_html = build_inline_html(div3_html)

    message_obj = build_email_html_with_attachment(
        sender=sender_email,
        receivers=receivers,
        inline_html=inline_email_html,
        attachment_html=full_html
    )

    encoded_message = base64.urlsafe_b64encode(
        message_obj.as_bytes()
    ).decode("utf-8")

    send_dict = {"raw": encoded_message}

    result = service.users().messages().send(
        userId="me",
        body=send_dict
    ).execute()

    print("📨 Email sent. Gmail Message ID:", result.get("id"))
    return result
