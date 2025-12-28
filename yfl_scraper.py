# yfl_scraper.py — FINAL, FIXED FOR main.py
#
# - API only
# - No week_id logic
# - Groups fixtures by week_name
# - Never returns None
# - Compatible with existing main.py (BeautifulSoup usage)
#
# Required secret:
#   SPORTSTACK_API_TOKEN

import os
import re
from datetime import date
from collections import defaultdict
from typing import Dict, List, Any, Tuple

import aiohttp

# -------------------------------------------------
# CONFIG
# -------------------------------------------------

API_BASE = "https://api.sportstack.ai/api/v1"
ORGANIZER = "yfl"
PARENT_COMPETITION_ID = 4

TOURNAMENTS: List[Tuple[int, str]] = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]

TOKEN = os.getenv("SPORTSTACK_API_TOKEN")
if not TOKEN:
    raise RuntimeError("Missing SPORTSTACK_API_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
}

# -------------------------------------------------
# HELPERS
# -------------------------------------------------

def _safe(x: Any) -> str:
    return "" if x is None else str(x)


def _week_sort_key(week_name: str) -> int:
    m = re.search(r"Week\s+(\d+)", week_name)
    return int(m.group(1)) if m else 9999


# -------------------------------------------------
# API
# -------------------------------------------------

async def fetch_all_fixtures(
    session: aiohttp.ClientSession,
    league_id: int,
) -> List[Dict[str, Any]]:
    fixtures: List[Dict[str, Any]] = []

    # Observed valid internal IDs
    for week_id in range(40, 80):
        url = (
            f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
            f"?league_id={league_id}"
            f"&competition_id={PARENT_COMPETITION_ID}"
            f"&week_id={week_id}"
        )

        async with session.get(url, headers=HEADERS) as resp:
            if resp.status != 200:
                continue

            data = await resp.json()
            if isinstance(data, list) and data:
                fixtures.extend(data)

    return fixtures


# -------------------------------------------------
# HTML BUILDERS
# -------------------------------------------------

def build_week_table(week_name: str, matches: List[Dict[str, Any]]) -> str:
    rows = []
    for m in matches:
        rows.append(
            f"""
<tr>
<td>{_safe(m.get('home_team_name'))}</td>
<td>{_safe(m.get('home_team_score'))}</td>
<td>{_safe(m.get('away_team_score'))}</td>
<td>{_safe(m.get('away_team_name'))}</td>
<td>{_safe(m.get('date'))}</td>
<td>{_safe(m.get('start_at'))}</td>
<td>{_safe(m.get('location_name'))}</td>
<td>{_safe(m.get('pitch_name'))}</td>
</tr>
"""
        )

    return f"""
<h3>{week_name}</h3>
<table border="1" cellpadding="6" cellspacing="0">
<thead>
<tr>
<th>Home</th>
<th>H</th>
<th>A</th>
<th>Away</th>
<th>Date</th>
<th>Time</th>
<th>Location</th>
<th>Pitch</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
"""


def build_division_section(label: str, fixtures: List[Dict[str, Any]]) -> str:
    if not fixtures:
        return f"""
<section>
<h2>{label}</h2>
<p>No fixtures available.</p>
</section>
"""

    weeks: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in fixtures:
        weeks[f["week_name"]].append(f)

    ordered_weeks = sorted(weeks.keys(), key=_week_sort_key)

    return f"""
<section>
<h2>{label}</h2>
{''.join(build_week_table(w, weeks[w]) for w in ordered_weeks)}
</section>
"""


# -------------------------------------------------
# ENTRY POINT (main.py compatible)
# -------------------------------------------------

async def scrape_all_divisions(*_args) -> Tuple[str, str, str]:
    today = date.today().isoformat()

    sections: List[str] = []
    inline_div3_html = ""  # MUST be a string

    async with aiohttp.ClientSession() as session:
        for league_id, label in TOURNAMENTS:
            fixtures = await fetch_all_fixtures(session, league_id)
            section_html = build_division_section(label, fixtures)
            sections.append(section_html)

            if league_id == 92:
                inline_div3_html = f"""
<html>
<body>
{section_html}
</body>
</html>
"""

    full_html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>YFL U11 Weekly Form Guide</title>
</head>
<body>
<h1>YFL U11 Weekly Form Guide</h1>
<p>Generated: {today}</p>
{''.join(sections)}
</body>
</html>
"""

    return full_html, inline_div3_html, f"yfl_u11_form_guide_{today}.html"
