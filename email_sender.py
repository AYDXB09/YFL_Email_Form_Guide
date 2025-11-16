import os
import base64
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


# ---------------------------------------------------------
# LOAD / REFRESH TOKEN (GitHub or local)
# ---------------------------------------------------------
def load_gmail_credentials():
    token_path = Path("gmail_token.json")
    secrets_path = Path("client_secret.json")

    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Refresh token
            creds.refresh(Request())
        else:
            # Need full login (only when running manually)
            flow = InstalledAppFlow.from_client_secrets_file(
                str(secrets_path), SCOPES
            )
            auth_url, _ = flow.authorization_url(prompt="consent")
            print("\n🔐 Open this URL in a browser:")
            print(auth_url)
            code = input("\nPaste authorization code here: ")
            flow.fetch_token(code=code)
            creds = flow.credentials

        # Save refreshed or new credentials
        token_path.write_text(creds.to_json())

    return creds


# ---------------------------------------------------------
# BUILD INLINE EMAIL
# ---------------------------------------------------------
def build_inline_email_html(division3_html: str):
    return f"""
<html>
  <body style="margin:0;padding:0;background:#0b1120;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
    <div style="max-width:900px;margin:0 auto;padding:20px;color:white;">

      <h1 style="font-size:26px;font-weight:700;margin-bottom:10px;">
        YFL Dubai — U11 Division 3
      </h1>

      <p style="color:#cbd5e1;font-size:14px;margin-top:0;margin-bottom:15px;">
        This email shows U11 Division 3 inline.<br>
        The full enhanced guide (Divisions 1, 2 and 3) is attached as HTML.
      </p>

      <!-- COLAB QUALITY EXACT HTML -->
      {division3_html}

    </div>
  </body>
</html>
"""


# ---------------------------------------------------------
# SEND EMAIL (INLINE + ATTACHMENT)
# ---------------------------------------------------------
def send_report_email(creds, receiver_email, inline_html, attachment_path):
    service = build("gmail", "v1", credentials=creds)

    message = MIMEMultipart("mixed")
    message["To"] = receiver_email
    message["From"] = "me"
    message["Subject"] = "YFL Weekly Form Guide — U11 Division 3 (inline) + All Divisions attached"

    # Inline HTML section
    html_part = MIMEMultipart("alternative")
    html_part.attach(MIMEText(inline_html, "html"))
    message.attach(html_part)

    # Attachment
    if attachment_path and Path(attachment_path).exists():
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="html")
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=Path(attachment_path).name,
            )
            message.attach(part)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    service.users().messages().send(
        userId="me", body={"raw": raw_message}
    ).execute()

    print("📨 Email sent successfully!")
