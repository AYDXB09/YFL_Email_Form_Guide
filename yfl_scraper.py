# yfl_scraper.py
# Restored version – API-based, multi-week form aggregation
# Produces:
# 1) inline HTML for Division 3
# 2) full HTML attachment for Divisions 1–3

import os
import aiohttp
import asyncio
from datetime import date
from collections import defaultdict
from typing import Dict, List, Tuple

API_BASE = "https://api.sportstack.ai/api/v1"
ORGANIZER = "yfl"
COMPETITION_ID = 4

# league_id, label
TOURNAMENTS = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]


# ------------------------------------------------------------
# Auth
# ------------------------------------------------------------
def _auth_headers() -> Dict[str, str]:
    token = os.getenv("SPORTSTACK_API_TOKEN")
    if not token:
        raise RuntimeError("Missing SPORTSTACK_API_TOKEN")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


# ------------------------------------------------------------
# API helpers
# ------------------------------------------------------------
async def fetch_fixtures_for_week(
    session: aiohttp.ClientSession,
    league_id: int,
    week_id: int,
) -> List[dict]:
    url = (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
        f"?league_id={league_id}&competition_id={COMPETITION_ID}&week_id={week_id}"
    )
    async with session.get(url) as r:
        if r.status != 200:
            return []
        payload = await r.json()
        return payload.get("data", [])


async def discover_week_ids(
    session: aiohttp.ClientSession,
    league_id: int,
) -> List[int]:
    """
    Discover valid week_ids by probing known pattern.
    Sportstack weeks are not sequential; they increment by 2.
    """
    discovered = []
    for wid in range(50, 80):  # safe range seen in DevTools
        fixtures = await fetch_fixtures_for_week(session, league_id, wid)
        if fixtures:
            discovered.append(wid)
    return sorted(discovered)


# ------------------------------------------------------------
# Form logic
# ------------------------------------------------------------
def result_for_team(fixture: dict, team_name: str) -> str:
    if fixture["home_team_name"] == team_name:
        return (
            "W" if fixture["home_team_score"] > fixture["away_team_score"]
            else "D" if fixture["home_team_score"] == fixture["away_team_score"]
            else "L"
        )
    else:
        return (
            "W" if fixture["away_team_score"] > fixture["home_team_score"]
            else "D" if fixture["away_team_score"] == fixture["home_team_score"]
            else "L"
        )


def build_form_table(fixtures: List[dict]) -> Dict[str, List[str]]:
    form = defaultdict(list)

    # sort chronologically
    fixtures = sorted(fixtures, key=lambda x: (x["date"], x["start_at"]))

    for fx in fixtures:
        home = fx["home_team_name"]
        away = fx["away_team_name"]

        form[home].append(result_for_team(fx, home))
        form[away].append(result_for_team(fx, away))

    return form


# ------------------------------------------------------------
# HTML rendering
# ------------------------------------------------------------
def render_form_row(results: List[str]) -> str:
    return "".join(
        f"<span class='f {r}'>{r}</span>" for r in results
    )


def render_division_section(title: str, form: Dict[str, List[str]]) -> str:
    rows = ""
    for club in sorted(form.keys()):
        rows += (
            "<tr>"
            f"<td>{club}</td>"
            f"<td>{render_form_row(form[club])}</td>"
            "</tr>"
        )

    if not rows:
        rows = "<tr><td colspan='2'>No fixtures available.</td></tr>"

    return f"""
<section>
  <h2>{title}</h2>
  <table>
    <tr><th>Club</th><th>Form</th></tr>
    {rows}
  </table>
</section>
"""


# ------------------------------------------------------------
# Main entry (called by main.py)
# ------------------------------------------------------------
async def scrape_all_divisions(*_args) -> Tuple[str, str, str]:
    today = date.today().isoformat()
    headers = _auth_headers()

    full_sections = []
    inline_div3_html = ""

    async with aiohttp.ClientSession(headers=headers) as session:
        for league_id, label in TOURNAMENTS:
            week_ids = await discover_week_ids(session, league_id)

            all_fixtures = []
            for wid in week_ids:
                all_fixtures.extend(
                    await fetch_fixtures_for_week(session, league_id, wid)
                )

            form = build_form_table(all_fixtures)
            section_html = render_division_section(label, form)
            full_sections.append(section_html)

            if league_id == 92:
                inline_div3_html = section_html

    full_html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>YFL Weekly Form Guide — U11</title>
<style>
body {{ font-family: Arial; background:#0b1220; color:#fff }}
table {{ width:100%; border-collapse:collapse; margin-bottom:24px }}
th, td {{ padding:6px; border-bottom:1px solid #222 }}
.f.W {{ color:#3fb950; margin-right:4px }}
.f.D {{ color:#d29922; margin-right:4px }}
.f.L {{ color:#f85149; margin-right:4px }}
</style>
</head>
<body>
<h1>YFL Weekly Form Guide — U11</h1>
<p>Generated: {today}</p>
{''.join(full_sections)}
</body>
</html>
"""

    filename = f"yfl_u11_form_guide_{today}.html"
    return full_html, inline_div3_html, filename
