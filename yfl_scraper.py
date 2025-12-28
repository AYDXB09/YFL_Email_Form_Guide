# yfl_scraper.py
# FINAL – RESTORED BEHAVIOUR
# Inline U11 Division 3 + Full Attachment (Div 1–3)

import os
import aiohttp
from datetime import date
from typing import Tuple, List, Dict

# --------------------------------------------------
# CONFIG
# --------------------------------------------------

API_BASE = "https://api.sportstack.ai/api/v1"
ORGANIZER = "yfl"
COMPETITION_ID = 4

TOURNAMENTS = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]

# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def _require_env():
    if not os.getenv("SPORTSTACK_API_TOKEN"):
        raise RuntimeError("Missing SPORTSTACK_API_TOKEN")

def _auth_headers():
    return {
        "Authorization": f"Bearer {os.environ['SPORTSTACK_API_TOKEN']}",
        "Accept": "application/json",
    }

# --------------------------------------------------
# API CALLS
# --------------------------------------------------

async def fetch_all_fixtures(
    session: aiohttp.ClientSession,
    league_id: int,
) -> List[Dict]:
    """
    Pulls ALL fixtures for ALL weeks by brute-force scanning.
    This matches browser behaviour and avoids week_id guessing.
    """

    fixtures: List[Dict] = []

    # empirically seen week_ids range ~52–80
    for week_id in range(50, 85):
        url = (
            f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
            f"?league_id={league_id}&competition_id={COMPETITION_ID}&week_id={week_id}"
        )

        async with session.get(url) as resp:
            if resp.status != 200:
                continue

            data = await resp.json()
            if isinstance(data, list) and data:
                fixtures.extend(data)

    # de-duplicate by fixture id
    uniq = {}
    for f in fixtures:
        uniq[f["id"]] = f

    return list(uniq.values())

# --------------------------------------------------
# HTML BUILDERS
# --------------------------------------------------

def build_division_table(label: str, fixtures: List[Dict]) -> str:
    rows = []

    for f in sorted(fixtures, key=lambda x: (x["date"], x["start_at"])):
        rows.append(
            f"""
            <tr>
              <td>{f['week_name']}</td>
              <td>{f['home_team_name']}</td>
              <td>{f['away_team_name']}</td>
              <td>{f['home_team_score']} – {f['away_team_score']}</td>
              <td>{f['date']}</td>
              <td>{f['start_at']}</td>
              <td>{f['location_name']} – {f['pitch_name']}</td>
            </tr>
            """
        )

    return f"""
    <h2>YFL Dubai — {label}</h2>
    <table border="1" cellpadding="6" cellspacing="0" width="100%">
      <thead>
        <tr>
          <th>Week</th>
          <th>Home</th>
          <th>Away</th>
          <th>Score</th>
          <th>Date</th>
          <th>Kickoff</th>
          <th>Venue</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
    """

# --------------------------------------------------
# MAIN ENTRY (CALLED BY main.py)
# --------------------------------------------------

async def scrape_all_divisions(*_args) -> Tuple[str, str, str]:
    """
    RETURNS:
    1) full_html        → attachment
    2) inline_div3_html → email body
    3) filename
    """

    _require_env()
    today = date.today().isoformat()

    sections = []
    inline_div3_html = ""

    async with aiohttp.ClientSession(headers=_auth_headers()) as session:
        for league_id, label in TOURNAMENTS:
            fixtures = await fetch_all_fixtures(session, league_id)

            if not fixtures:
                raise RuntimeError(f"No fixtures fetched for {label}")

            table_html = build_division_table(label, fixtures)
            sections.append(table_html)

            if label == "U11 Division 3":
                inline_div3_html = table_html

    full_html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>YFL U11 Form Guide</title>
</head>
<body>
<h1>YFL Weekly Form Guide — U11</h1>
<p>Generated: {today}</p>
{''.join(sections)}
</body>
</html>
"""

    filename = f"yfl_u11_form_guide_{today}.html"

    return full_html, inline_div3_html, filename
