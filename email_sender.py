import base64
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


# ------------------------------------------------------------
# LOAD GMAIL CREDENTIALS (GitHub-friendly)
# ------------------------------------------------------------
def load_gmail_credentials():
    """
    Loads Gmail OAuth credentials from gmail_token.json and client_secret.json.
    """

    if not os.path.exists("gmail_token.json"):
        raise RuntimeError("gmail_token.json not found in repo workspace")

    creds = Credentials.from_authorized_user_file(
        "gmail_token.json",
        scopes=["https://www.googleapis.com/auth/gmail.send"]
    )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

    return creds


# ------------------------------------------------------------
# INLINE CSS WRAPPER (Used for inline Div 3)
# ------------------------------------------------------------
def wrap_inline_html(html_table):
    """
    Injects full dark-theme CSS identical to your Colab output.
    """

    return f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
<style>
    body {{
        background:#0b1120;
        color:#fff;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        padding:20px;
    }}
    table {{
        width:100%;
        border-collapse: collapse;
        background:#0f172a;
        color:#fff;
    }}
    th {{
        background:#1e293b;
        padding:10px;
        text-align:left;
        font-size:14px;
        font-weight:600;
        border-bottom:1px solid #334155;
    }}
    td {{
        padding:10px;
        border-bottom:1px solid #1e293b;
        font-size:13px;
    }}
    .team-cell {{
        display:flex;
        align-items:center;
    }}
    .team-logo {{
        width:24px;
        height:24px;
        border-radius:4px;
        margin-right:8px;
    }}
    .pos {{
        font-weight:700;
        color:#38bdf8;
    }}
    .gd-pos {{ color:#22c55e; font-weight:700; }}
    .gd-neg {{ color:#ef4444; font-weight:700; }}
    .pts {{ font-weight:700; }}
    .next-main {{ display:block; font-weight:600; }}
    .next-meta {{ display:block; font-size:12px; opacity:0.8; }}
</style>
</head>
<body>
{html_table}
</body>
</html>
"""


# ------------------------------------------------------------
# SEND EMAIL (inline HTML + attachment)
# ------------------------------------------------------------
def send_report_email(creds, receiver, inline_html, attachment_path):
    """Sends 1 email with:
    - inline HTML (Div 3)
    - attachment of full HTML report
    """

    service = build("gmail", "v1", credentials=creds)

    msg = MIMEMultipart("mixed")
    msg["To"] = receiver
    msg["From"] = "me"
    msg["Subject"] = "YFL Weekly Form Guide — U11"

    # Add inline HTML
    msg.attach(MIMEText(inline_html, "html"))

    # Add attachment
    with open(attachment_path, "rb") as f:
        attachment = MIMEApplication(f.read(), _subtype="html")
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=os.path.basename(attachment_path)
        )
        msg.attach(attachment)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    service.users().messages().send(
        userId="me",
        body={"raw": raw}
    ).execute()
