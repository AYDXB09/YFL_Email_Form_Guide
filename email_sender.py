# email_sender.py
#
# Gmail API helper:
#   - get_gmail_creds(): loads or performs manual OAuth, saving gmail_token.json
#   - send_report_email(): sends HTML email with attachment
#
# It also wraps the body HTML in a minimal <html><head><style>...</style><body>...</body>
# shell so the inline Div 3 table uses the same dark CSS as the full report.

import base64
from pathlib import Path
from email.message import EmailMessage

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
OOB_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"

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
    """
    If body_html is just a fragment, wrap it in a full HTML shell
    with our CSS. If the caller already passed a full <html> document,
    leave it as-is.
    """
    lower = body_html.strip().lower()
    if lower.startswith("<!doctype") or lower.startswith("<html"):
        # Assume caller already added CSS, don't touch it.
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


def get_gmail_creds(json_path: str = "client_secret.json",
                    token_path: str = "gmail_token.json") -> Credentials:
    """
    Load Gmail credentials from token_path if present, otherwise
    run the manual OAuth flow (OOB) and save the token.

    This function name is what main.py expects – do NOT rename it.
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

    # Explicitly set redirect URI for OOB
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
    creds: Credentials,
    receivers,
    subject: str,
    body_html: str,
    attachment_path: str | None,
) -> None:
    """
    Send a single email:
      - HTML body (body_html) wrapped in our CSS shell
      - Optional HTML attachment (attachment_path)
      - To one or more receivers (list or comma-separated string)
    """
    if isinstance(receivers, str):
        receivers = [r.strip() for r in receivers.split(",") if r.strip()]

    service = build("gmail", "v1", credentials=creds)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = ", ".join(receivers)

    # Wrap body with CSS + HTML boilerplate
    html_with_css = _wrap_body_with_css(body_html)

    # Fallback plain text + HTML alternative
    msg.set_content("This email requires an HTML-compatible client.")
    msg.add_alternative(html_with_css, subtype="html")

    # Attachment (full HTML report)
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
