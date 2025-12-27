# yfl_scraper.py — API-only, CI-safe, 401 FIXED

import aiohttp
from datetime import date
from typing import List, Tuple, Dict, Any

API_BASE = "https://api.sportstack.ai/api/v1"

ORGANIZER = "yfl"
PARENT_COMPETITION_ID = 4

TOURNAMENTS: List[Tuple[int, str]] = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]

# Required headers (prevents 401)
API_HEADERS = {
    "x-organizer": "yfl",
    "accept": "application/json",
    "user-agent": "Mozilla/5.0",
    "origin": "https://leaguehub-yfl.sportstack.ai",
    "referer": "https://leaguehub-yfl.sportstack.ai/",
}


async def fetch_league_overview(
    session: aiohttp.ClientSession, league_id: int
) -> Dict[str, Any]:
    url = (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/competitions/"
        f"{PARENT_COMPETITION_ID}/leagues/{league_id}/overview"
    )

    async with session.get(url, headers=API_HEADERS) as resp:
        if resp.status != 200:
            raise RuntimeError(
                f"API call failed ({resp.status}) for league {league_id}"
            )
        return await resp.json()


def build_table_html(label: str, overview: Dict[str, Any]) -> str:
    standings = overview.get("standings", [])
    if not standings:
        raise RuntimeError(f"No standings data for {label}")

    rows_html = []
    for row in standings:
        rows_html.append(
            f"""
<tr>
  <td>{row.get('position','')}</td>
  <td>{row.get('teamName','')}</td>
  <td>{row.get('played','')}</td>
  <td>{row.get('won','')}</td>
  <td>{row.get('drawn','')}</td>
  <td>{row.get('lost','')}</td>
  <td>{row.get('goalsFor','')}/{row.get('goalsAgainst','')}</td>
  <td>{row.get('goalDifference','')}</td>
  <td>{row.get('points','')}</td>
</tr>
"""
        )

    return f"""
<section>
<h2>{label}</h2>
<table border="1" cellspacing="0" cellpadding="4">
<thead>
<tr>
  <th>#</th>
  <th>Club</th>
  <th>P</th>
  <th>W</th>
  <th>D</th>
  <th>L</th>
  <th>GF/GA</th>
  <th>GD</th>
  <th>PTS</th>
</tr>
</thead>
<tbody>
{''.join(rows_html)}
</tbody>
</table>
</section>
"""


# ---- ENTRY POINT EXPECTED BY main.py ----
async def scrape_all_divisions(*args, **kwargs):
    today = date.today().isoformat()
    sections = []

    async with aiohttp.ClientSession() as session:
        for league_id, label in TOURNAMENTS:
            overview = await fetch_league_overview(session, league_id)
            sections.append(build_table_html(label, overview))

    full_html = f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>YFL U11 Form Guide</title>
</head>
<body>
<h1>YFL U11 Form Guide</h1>
<p>Generated: {today}</p>
{''.join(sections)}
</body>
</html>
"""

    return full_html, None, f"yfl_u11_form_guide_{today}.html"
