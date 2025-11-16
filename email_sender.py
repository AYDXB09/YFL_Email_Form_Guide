import os
import base64
import mimetypes
from email.message import EmailMessage
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ------------------------------------------------------
# 1. MATCHING THE NAME EXPECTED BY main.py
# ------------------------------------------------------
def get_gmail_creds(json_path="client_secret.json", token_path="gmail_token.json"):
    """
    Loads Gmail OAuth credentials from token + client secret files.
    This name MUST remain 'get_gmail_creds' because main.py imports it.
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"Client secret file not found: {json_path}")
    if not os.path.exists(token_path):
        raise FileNotFoundError(f"Token file not found: {token_path}")

    creds = Credentials.from_authorized_user_file(token_path, ["https://www.googleapis.com/auth/gmail.send"])
    return creds


# ------------------------------------------------------
# 2. EMAIL SENDER WITH FULL COLAB CSS
# ------------------------------------------------------
def send_report_email(creds, receiver_email, html_content, attachment_path=None):
    """
    Sends an HTML email using Gmail API.
    Embeds the full CSS so inline table looks EXACTLY like the Colab version.
    """

    # ----- CSS identical to your Colab output -----
    css_block = """
    <style>
    body {
        background-color: #0f172a;
        color: white;
        font-family: Arial, sans-serif;
        padding: 20px;
    }
    h2 {
        color: #38bdf8;
        margin-bottom: 12px;
    }
    table {
        width: 100%;
        border-collapse: collapse;
        background: #020617;
        margin-bottom: 30px;
    }
    th {
        background-color: #1e293b;
        padding: 10px;
        border-bottom: 2px solid #475569;
        text-align: left;
        font-size: 13px;
        color: #e2e8f0;
    }
    td {
        padding: 8px 10px;
        border-bottom: 1px solid #1e293b;
        font-size: 13px;
    }
    .team-cell {
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .team-logo {
        width: 24px;
        height: 24px;
        border-radius: 4px;
    }
    .gd-pos { color: #22c55e; font-weight: bold; }
    .gd-neg { color: #ef4444; font-weight: bold; }
    .pos, .pts { font-weight: bold; }
    .next-main { font-weight: bold; display:block; }
    .next-meta { color:#94a3b8; font-size:12px; }
    .form-cell span {
        margin-right: 4px;
    }
    </style>
    """

    html_body = f"{css_block}\n{html_content}"

    message = EmailMessage()
    message["To"] = receiver_email
    message["From"] = "me"
    message["Subject"] = "YFL U11 — Weekly Form Guide"

    message.add_alternative(html_body, subtype="html")

    # Attach file (HTML full table)
    if attachment_path and os.path.exists(attachment_path):
        mime_type, _ = mimetypes.guess_type(attachment_path)
        mime_type = mime_type or "application/octet-stream"
        maintype, subtype = mime_type.split("/")

        with open(attachment_path, "rb") as f:
            file_data = f.read()

        message.add_attachment(
            file_data,
            maintype=maintype,
            subtype=subtype,
            filename=os.path.basename(attachment_path),
        )

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    try:
        service = build("gmail", "v1", credentials=creds)
        send_result = service.users().messages().send(
            userId="me",
            body={"raw": encoded_message}
        ).execute()

        print("📧 Email sent successfully.")
        return send_result

    except HttpError as error:
        print(f"❌ Gmail API Error: {error}")
        raise
