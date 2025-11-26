import os
import asyncio
import textwrap
from pathlib import Path

from yfl_scraper import scrape_all_divisions
from email_sender import send_report_email, inline_div3_to_responsive_table, wrap_body_with_email_html


async def main():
    # --- YFL login credentials ---
    yfl_username = os.environ.get("YFL_USERNAME")
    yfl_password = os.environ.get("YFL_PASSWORD")

    if not yfl_username or not yfl_password:
        raise RuntimeError(
            "YFL_USERNAME and/or YFL_PASSWORD are not set. "
            "Configure them as environment variables or GitHub Secrets."
        )

    # --- Email receiver(s) ---
    receiver_env = os.environ.get("EMAIL_RECEIVER")
    if not receiver_env:
        raise RuntimeError(
            "EMAIL_RECEIVER is not set. Set it to one or more email addresses (comma-separated)."
        )
    receivers = [r.strip() for r in receiver_env.split(",") if r.strip()]

    # --- Email subject ---
    subject = os.environ.get("EMAIL_SUBJECT", "YFL Weekly Form Guide — U11")

    # --- 1) Scrape YFL + build HTML (full + inline Div 3) ---
    print("⚽ Starting YFL scrape + HTML build…")
    full_html, inline_div3_html, output_filename = await scrape_all_divisions(
        yfl_username,
        yfl_password,
    )

    # Save full HTML to disk (for attachment)
    out_path = Path(output_filename)
    out_path.write_text(full_html, encoding="utf-8")
    print(f"🎉 Saved HTML report to {out_path.resolve()}")

    # --- 2) Convert Div 3 inline HTML to responsive table ---
    responsive_div3_html = inline_div3_to_responsive_table(inline_div3_html)

    # --- 3) Build email body ---
    body_html = f"""
    <p>Hi,</p>
    <p>Here is the latest <strong>YFL U11 Form Guide</strong>.</p>
    <p>
      The full form guide for <strong>U11 Divisions 1–3</strong> is attached as
      <code>{output_filename}</code>.
    </p>
    <hr/>
    {responsive_div3_html}
    """

    body_html = wrap_body_with_email_html(body_html)

    # --- 4) Send email via SMTP ---
    print("\n📧 Preparing to send email with HTML attached…")
    send_report_email(
        receivers=receivers,
        subject=subject,
        body_html=body_html,
        attachment_path=str(out_path)
    )

    print("✅ All done: scraped, built HTML, emailed.")


if __name__ == "__main__":
    asyncio.run(main())
