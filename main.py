import os
import asyncio
from pathlib import Path
import textwrap

from yfl_scraper import scrape_all_divisions
from email_sender import send_report_email, _wrap_body_with_css

async def main():
    yfl_username = os.environ.get("YFL_USERNAME")
    yfl_password = os.environ.get("YFL_PASSWORD")
    if not yfl_username or not yfl_password:
        raise RuntimeError("YFL_USERNAME and/or YFL_PASSWORD are not set")

    receiver_env = os.environ.get("EMAIL_RECEIVER")
    if not receiver_env:
        raise RuntimeError("EMAIL_RECEIVER not set")
    receivers = [r.strip() for r in receiver_env.split(",") if r.strip()]

    print("⚽ Starting YFL scrape + HTML build…")
    full_html, inline_div3_html, output_filename = await scrape_all_divisions(
        yfl_username, yfl_password
    )

    # --- Save full HTML report ---
    out_path = Path(output_filename)
    out_path.write_text(full_html, encoding="utf-8")
    print(f"🎉 Saved HTML report to {out_path.resolve()}")

    # --- Prepare inline HTML for email ---
    # Wrap the inline Div 3 in <div> and use smaller logos
    # Replace team-logo class with team-logo-inline for inline email
    inline_html_email = inline_div3_html.replace("team-logo", "team-logo-inline")
    body_html = textwrap.dedent(f"""
        <p>Hi,</p>
        <p>Here is the latest <strong>YFL U11 Form Guide</strong>.</p>
        <p>The full form guide for <strong>U11 Divisions 1–3</strong> is attached as
        <code>{output_filename}</code>.</p>
        <hr/>
        {inline_html_email}
    """)

    subject = os.environ.get("EMAIL_SUBJECT", "YFL Weekly Form Guide — U11")

    send_report_email(
        receivers=receivers,
        subject=subject,
        body_html=body_html,
        attachment_path=str(out_path),
    )

    print("✅ All done: scraped, built HTML, emailed.")


if __name__ == "__main__":
    asyncio.run(main())
