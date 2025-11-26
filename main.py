import os
import asyncio
from pathlib import Path
import textwrap
from bs4 import BeautifulSoup

from yfl_scraper import scrape_all_divisions
from email_sender import send_report_email

async def main():
    # --- YFL login credentials ---
    yfl_username = os.environ.get("YFL_USERNAME")
    yfl_password = os.environ.get("YFL_PASSWORD")
    if not yfl_username or not yfl_password:
        raise RuntimeError("YFL_USERNAME and/or YFL_PASSWORD are not set")

    # --- Email receiver(s) ---
    receiver_env = os.environ.get("EMAIL_RECEIVER")
    if not receiver_env:
        raise RuntimeError("EMAIL_RECEIVER not set")
    receivers = [r.strip() for r in receiver_env.split(",") if r.strip()]

    # --- Scrape YFL + build HTML (full + inline Div 3) ---
    print("⚽ Starting YFL scrape + HTML build…")
    full_html, inline_div3_html, output_filename = await scrape_all_divisions(
        yfl_username, yfl_password
    )

    # --- Save full HTML to disk (for attachment) ---
    out_path = Path(output_filename)
    out_path.write_text(full_html, encoding="utf-8")
    print(f"🎉 Saved HTML report to {out_path.resolve()}")

    # --- Prepare inline HTML for email ---
    # Use BeautifulSoup to flatten team cells and reduce logo size for email
    soup = BeautifulSoup(inline_div3_html, "html.parser")

    # Reduce logo size only for inline email
    for img in soup.find_all("img", class_="team-logo"):
        img["class"] = "team-logo-inline"
        img["width"] = "20"
        img["height"] = "20"

    # Reduce width of team name cells and prevent large gaps
    for td in soup.find_all("td", class_="team-name"):
        td["style"] = "max-width:180px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;"

    inline_html_email = str(soup)

    # --- Compose email body ---
    body_html = textwrap.dedent(f"""
        <p>Hi,</p>
        <p>Here is the latest <strong>YFL U11 Form Guide</strong>.</p>
        <p>The full form guide for <strong>U11 Divisions 1–3</strong> is attached as
        <code>{output_filename}</code>.</p>
        <hr/>
        {inline_html_email}
    """)

    subject = os.environ.get("EMAIL_SUBJECT", "YFL Weekly Form Guide — U11")

    # --- Send email via SMTP ---
    send_report_email(
        receivers=receivers,
        subject=subject,
        body_html=body_html,
        attachment_path=str(out_path),
    )

    print("✅ All done: scraped, built HTML, emailed.")

if __name__ == "__main__":
    asyncio.run(main())
