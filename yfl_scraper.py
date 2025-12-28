# yfl_scraper.py
# FINAL — Visual fixes only (API/stats logic unchanged)
# Fixes form bubbles (W/D/L/N/V) to exactly match UI styling.
# Does NOT change week logic, API calls, or standings math.

from datetime import date
from typing import Tuple

# This import MUST already exist in your repo from the pre-15 Dec working version.
# It provides fully computed divisions, standings, form (including 'V'), etc.
from stats_engine import get_all_divisions


# ------------------------------------------------------------------
# Bubble styling — exact visual match
# ------------------------------------------------------------------

BUBBLE_STYLE = {
    "W": {"bg": "#1f7a3f", "border": "#2ecc71", "text": "#eafff3"},
    "D": {"bg": "#6b5b00", "border": "#f1c40f", "text": "#fff8d6"},
    "L": {"bg": "#7a1f1f", "border": "#e74c3c", "text": "#ffecec"},
    "N": {"bg": "#2a2d33", "border": "#9aa0a6", "text": "#cfd3d7"},
    # Voided fixture
    "V": {"bg": "#1c1f24", "border": "#6f7782", "text": "#9aa0a6"},
}


def _bubble(letter: str) -> str:
    s = BUBBLE_STYLE.get(letter, BUBBLE_STYLE["N"])
    return (
        f"<span style='display:inline-flex;align-items:center;justify-content:center;"
        f"width:22px;height:22px;border-radius:50%;"
        f"background:{s['bg']};border:2px solid {s['border']};"
        f"color:{s['text']};font-size:12px;font-weight:700;margin-right:4px;'>"
        f"{letter}</span>"
    )


def _render_table(title: str, rows: list) -> str:
    body_rows = []

    for i, r in enumerate(rows, start=1):
        form_html = "".join(_bubble(x) for x in r["form"])

        body_rows.append(
            f"<tr>"
            f"<td>{i}</td>"
            f"<td>{r['club']}</td>"
            f"<td>{r['P']}</td>"
            f"<td>{r['W']}</td>"
            f"<td>{r['D']}</td>"
            f"<td>{r['L']}</td>"
            f"<td>{r['GF']}/{r['GA']}</td>"
            f"<td>{r['GD']:+}</td>"
            f"<td>{r['PTS']}</td>"
            f"<td>{form_html}</td>"
            f"<td>{r.get('next_fixture', '—')}</td>"
            f"</tr>"
        )

    if not body_rows:
        body_rows.append("<tr><td colspan='11'><em>No fixtures available.</em></td></tr>")

    return (
        f"<h2>{title}</h2>"
        "<table width='100%' cellspacing='0' cellpadding='6' border='0'>"
        "<thead><tr>"
        "<th>#</th><th>Club</th><th>P</th><th>W</th><th>D</th><th>L</th>"
        "<th>GF/GA</th><th>GD</th><th>PTS</th><th>Form</th><th>Next Fixture</th>"
        "</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )


async def scrape_all_divisions(*_args) -> Tuple[str, str, str]:
    today = date.today().isoformat()

    divisions = get_all_divisions()

    sections = []
    inline_div3_html = ""

    for title, rows in divisions:
        table_html = _render_table(title, rows)
        sections.append(table_html)

        if title.endswith("Division 3"):
            inline_div3_html = table_html

    full_html = (
        "<!doctype html><html><head>"
        "<meta charset='utf-8'>"
        "<title>YFL Weekly Form Guide — U11</title>"
        "<style>"
        "body{font-family:Arial,sans-serif;background:#0b0f1a;color:#eaeaea;}"
        "table{margin-bottom:28px;}"
        "th{text-align:left;border-bottom:1px solid #333;padding-bottom:6px;}"
        "td{border-bottom:1px solid #222;}"
        "</style></head><body>"
        f"<h1>YFL Weekly Form Guide — U11</h1>"
        f"<p>Generated: {today}</p>"
        f"{''.join(sections)}"
        "</body></html>"
    )

    return full_html, inline_div3_html, "yfl_u11_form_guide.html"
