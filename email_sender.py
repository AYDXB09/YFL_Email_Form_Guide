# email_sender.py
#
# Gmail API helper:
#  - get_gmail_creds(): loads or performs manual OAuth, saving gmail_token.json
#  - send_report_email(): sends HTML email with attachment

import base64
from pathlib import Path
from email.message import EmailMessage

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
OOB_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"


def get_gmail_creds(json_path="client_secret.json", token_path="gmail_token.json"):
    """Get Gmail Credentials.

    1) If token_path exists, load and return creds.
    2) Otherwise, run manual OAuth (prints URL, asks for code).
    """
    token_file = Path(token_path)

    if token_file.exists():
        try:
            print("🔐 Using existing Gmail token…")
            return Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except Exception:
            print("⚠ Failed to load existing token, removing and re-authenticating.")
            token_file.unlink(missing_ok=True)

    print("🔐 Starting manual Gmail OAuth (OOB mode)…")

    flow = InstalledAppFlow.from_client_secrets_file(json_path, SCOPES)

    # Inject redirect URI so Google sees a valid redirect_uri parameter
    flow.oauth2session.redirect_uri = OOB_REDIRECT_URI

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    print("\n👉 Open this URL in a NEW browser tab:")
    print(auth_url)

    code = input("\n✏️ Paste the authorization code here:\n> ").strip()

    flow.fetch_token(code=code)
    creds = flow.credentials

    token_file.write_text(creds.to_json(), encoding="utf-8")
    print(f"✅ Gmail authorization complete. Token saved as {token_file}.")

    return creds


def send_report_email(
    creds,
    receivers,
    subject,
    body_html,
    attachment_path,
):
    """Send one email:
    - HTML body (body_html)
    - Single HTML attachment (attachment_path)
    - To one or more receivers (list)
    """
    if isinstance(receivers, str):
        receivers = [receivers]

    service = build("gmail", "v1", credentials=creds)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = ", ".join(receivers)

    # HTML body
    msg.set_content("This email requires an HTML-compatible client.")
    msg.add_alternative(body_html, subtype="html")

    # Attachment
    if attachment_path:
        p = Path(attachment_path)
        data = p.read_bytes()
        msg.add_attachment(
            data,
            maintype="text",
            subtype="html",
            filename=p.name,
        )

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    body = {"raw": raw}

    sent = service.users().messages().send(userId="me", body=body).execute()
    print("📨 Email sent. Message ID:", sent.get("id"))
