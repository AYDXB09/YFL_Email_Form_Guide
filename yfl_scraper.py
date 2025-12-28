# yfl_scraper.py
# FINAL – RESTORED FUNCTIONALITY
# - Previous weeks INCLUDED
# - Inline Division 3 HTML for email body
# - Full HTML attachment (Div 1–3)
# - NO YFL_WEEK_ID
# - API-based, CI-safe

import os
import aiohttp
from datetime import date
from typing import List, Dict, Tuple
from collections import defaultdict

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
# ENV / AUTH
# --------------------------------------------------

def _require_env():
    if not os.getenv("SPORTSTACK_API_TOKEN"):
        raise RuntimeError("Missing SPORTSTACK_API_TOKEN")

def _headers():
    return {
        "Authorization": f"Bearer {os.environ['SPORTSTACK_API_TOKEN']}",
        "Accept": "application/json",
    }

# --------------------------------------------------
# API – FETCH ALL FIXTURES (ALL WEEKS)
# --------------------------------------------------

async def fetch_all_fixtures(
    session: aiohttp.ClientSession,
    league_id: int,
) -> List[Dict]:

    # IMPORTANT:
    # Calling WITHOUT week_id returns ALL fixtures
    url = (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
        f"?league_id={league_id}&competition_id={COMPETITION_ID}"
    )

    async with session.get(url) as resp:
        if resp.status != 200:
            return []

        data = await resp.json()
        if not isinstance(data, list):
            return []

        return data

# --------------------------------------------------
# FORM LOGIC (OLD BEHAVIOUR)
# --------------------------------------------------

def result_for_team(f: Dict, team: str) -> str:
    if f["home_team_name"] == team:
        if f["home_team_score"] > f["away_team_score"]:
            return "W"
        if f["home_team_score"] < f["away_team_score"]:
            return "L"
        return "D"
    if f["away_team_name"] == team:
        if f["away_team_score"] > f["home_team_score"]:
            return "W"
        if f["away_team_score"] < f["home_team_score"]:
            return "L"
        return "D"
    return ""

def build_form_map(fixtures: List[Dict], last_n: int = 5) -> Dict[str, List[str]]:
    team_games = defaultdict(list)

    finished = [
        f for f in fixtures
        if f.get("has_finished") and f.get("home_team_score") is not None
    ]

    finished.sort(key=lambda x: (x["date"], x["start_at"]))

    for f in finished:
        team_games[f["home_team_name"]].append(f)
        team_games[f["away_team_name"]].append(f)

    form = {}
    for team, games in team_games.items():
        recent = games[-last_n:]
        form[team] = [result_for_team(g, team) for g in recent]

    return form

# --------------------------------------------------
# HTML BUILDERS
# --------------------------------------------------

def build_division_table(label: str, fixtures: List[Dict]) -> str:
    if not fixtures:
        return f"<h2>{label}</h2><p><em>No fixtures available.</em></p>"

    form_map = build_form_map(fixtures)

    rows = []
    fixtures.sort(key=lambda x: (x["date"], x["start_at"]))

    for f in fixtures:
        rows.append(
            f"""
<tr>
<td>{f['week_name']}</td>
<td>{f['home_team_name']}</td>
<td>{f['away_team_name']}</td>
<td>{f['home_team_score']}–{f['away_team_score']}</td>
<td>{f['date']}</td>
<td>{f['start_at']}</td>
<td>{f['location_name']} – {f['pitch_name']}</td>
</tr>
"""
        )

    return f"""
<h2>{label}</h2>
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

def build_inline_div3(label: str, fixtures: List[Dict]) -> str:
    # INLINE EMAIL CONTENT (Division 3 only)
    if not fixtures:
        return "<p><em>No fixtures available.</em></p>"

    rows = []
    fixtures.sort(key=lambda x: (x["date"], x["start_at"]))

    for f in fixtures:
        rows.append(
            f"""
<tr>
<td>{f['week_name']}</td>
<td>{f['home_team_name']}</td>
<td>{f['away_team_name']}</td>
<td>{f['home_team_score']}–{f['away_team_score']}</td>
</tr>
"""
        )

    return f"""
<h3>{label}</h3>
<table border="1" cellpadding="6" cellspacing="0" width="100%">
<thead>
<tr>
<th>Week</th>
<th>Home</th>
<th>Away</th>
<th>Score</th>
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
    _require_env()
    today = date.today().isoformat()

    sections = []
    inline_div3_html = ""

    async with aiohttp.ClientSession(headers=_headers()) as session:
        for league_id, label in TOURNAMENTS:
            fixtures = await fetch_all_fixtures(session, league_id)

            section_html = build_division_table(label, fixtures)
            sections.append(section_html)

            if label == "U11 Division 3":
                inline_div3_html = build_inline_div3(label, fixtures)

    full_html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>YFL Weekly Form Guide — U11</title>
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
