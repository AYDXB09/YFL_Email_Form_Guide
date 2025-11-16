import base64
import json
import mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# -------------------------------------------------------------------
# 1) LOAD GMAIL CREDS FROM gmail_token.json (GitHub or Colab)
# -------------------------------------------------------------------
def get_gmail_creds(token_path="gmail_token.json"):
    """
    Loads Gmail OAuth token (already created in Colab earlier).

    On GitHub Actions:
    - token file is reconstructed from the repo secret GMAIL_TOKEN_JSON.
    """

    with open(token_path, "r") as f:
        token_data = json.load(f)

    creds = Credentials.from_authorized_user_info(
        token_data,
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )

    return creds


# -------------------------------------------------------------------
# 2) FULL INLINE CSS (Dark theme identical to Colab version)
# -------------------------------------------------------------------
INLINE_CSS = """
<style>
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #020617;
  color: #f8fafc;
  padding: 20px;
}
h2 { color: #f8fafc; margin-bottom: 12px; }

table {
  width: 100%;
  border-collapse: collapse;
  background: #0f172a;
  color: #f8fafc;
  font-size: 14px;
}
th {
  background: #1e293b;
  padding: 8px;
  text-align: left;
  border-bottom: 2px solid #334155;
}
td {
  padding: 8px;
  border-bottom: 1px solid #1e293b;
}

.team-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.team-logo {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  object-fit: cover;
}

.gd-pos { color: #22c55e; font-weight: 700; }
.gd-neg { color: #ef4444; font-weight: 700; }

.form-cell span {
  display:inline-flex;
  align-items:center;
  justify-content:center;
  width:24px;
  height:24px;
  border-radius:999px;
  margin-right:4px;
  font-size:11px;
  font-weight:700;
  background:#020617;
}

.form-W { border:2px solid #22c55e; color:#22c55e; }
.form-D { border:2px solid #eab308; color:#eab308; }
.form-L { border:2px solid #ef4444; color:#ef4444; }
.form-N { border:2px solid #9ca3af; color:#9ca3af; }
.form-V { 
  border:2px solid #9ca3af; 
  background: repeating-linear-gradient(45deg,#9ca3af 0,#9ca3af 4px,#e5e7eb 4px,#e5e7eb 8px);
  color:#020617;
}

.next-main { font-weight: 600; display:block; }
.next-meta { font-size: 12px; opacity: 0.7; }
</style>
"""


# -------------------------------------------------------------------
# 3) SEND EMAIL (inline HTML + attachment)
# -------------------------------------------------------------------
def send_report_email(
    creds,
    receiver_email,
    html_inline_div3,
    html_attachment_path="yfl_u11_form_guide.html"
):
    """
    Sends:
      1) Inline HTML (Div 3 only)
      2) Full HTML attachment (Div 1–3)

    """
    service = build("gmail", "v1", credentials=creds)

    msg = MIMEMultipart()
    msg["To"] = receiver_email
    msg["Subject"] = "YFL Weekly Form Guide — U11 Division 3 (Inline) + All Divisions Attached"

    # ------------------------------------------------------------
    # HTML BODY (inline)
    # ------------------------------------------------------------
    html_body = f"""
    <html>
    <head>{INLINE_CSS}</head>
    <body>
      <h2>YFL Dubai — Under 11 Form Guide</h2>
      <p>This email shows <b>U11 Division 3</b> inline.<br>
      For Divisions 1–3, open the attached HTML file <b>yfl_u11_form_guide.html</b>.</p>
      {html_inline_div3}
    </body>
    </html>
    """

    msg.attach(MIMEText(html_body, "html"))

    # ------------------------------------------------------------
    # ATTACHMENT (Full HTML)
    # ------------------------------------------------------------
    with open(html_attachment_path, "rb") as f:
        attachment_data = f.read()

    attachment = MIMEBase("text", "html")
    attachment.set_payload(attachment_data)
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        f'attachment; filename="{html_attachment_path}"'
    )

    msg.attach(attachment)

    # ------------------------------------------------------------
    # SEND EMAIL
    # ------------------------------------------------------------
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()

    return True
