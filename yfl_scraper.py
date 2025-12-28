# yfl_scraper.py — FINAL (fixtures-based, week_name driven)
# CI-safe, no UI scraping, no week_id logic

import os
import re
import asyncio
from datetime import date
from collections import defaultdict
from typing import Dict, List, Any, Tuple

import aiohttp

API_BASE = "https://api.sportstack.ai/api/v1"
ORGANIZER = "yfl"
PARENT_COMPETITION_ID = 4

TOURNAMENTS = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]

REQUIRED_ENV = ["SPORTSTACK_API_TOKEN"]


# -------------------------
# Helpers
# -------------------------

def _require_env():
    for k in REQUIRED_ENV:
        if not os.getenv(k):
            raise RuntimeError(f"Missing {k} (set as GitHub repo secret)")


def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['SPORTSTACK_API_TOKEN']}",
        "Accept": "application/json",
    }


def _week_sort_key(week_name: str) -> int:
    """
    Extract numeric week index from strings like:
    'Week 1', 'Week 9 (Sunday)'
    """
    m = re.search(r"Week\s+(\d+)", week_name)
    return int(m.group(1)) if m else 9999


# -------------------------
# API calls
# -------------------------

async def fetch_all_fixtures(
    session: aiohttp.ClientSession,
    league_id: int,
) -> List[Dict[str, Any]]:
    """
    Sportstack does NOT expose a clean 'all weeks' endpoint.
    We iterate over observed week_id ranges until responses dry up.
    """
    fixtures: List[Dict[str, Any]] = []

    # Empirically observed valid IDs (stable across UI + CSV)
    candidate_week_ids = range(40, 80)

    for week_id in candidate_week_ids:
        url = (
            f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
            f"?league_id={league_id}"
            f"&competition_id={PARENT_COMPETITION_ID}"
            f"&week_id={week_id}"
        )

        async with session.get(url) as resp:
            if resp.status != 200:
                continue

            data = await resp.json()
            if isinstance(data, list) and data:
                fixtures.extend(data)

    return fixtures


# -------------------------
# HTML builders
# -------------------------

def build_week_table(week_name: str, matches: List[Dict[str, Any]]) -> str:
    rows = []
    for m in matches:
        rows.append(
            f"""
<tr>
<td>{m['home_team_name']}</td>
<td>{m['home_team_score']}</td>
<td>{m['away_team_score']}</td>
<td>{m['away_team_name']}</td>
<td>{m['date']}</td>
<td>{m['start_at']}</td>
<td>{m['location_name']}</td>
<td>{m['pitch_name']}</td>
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


# -------------------------
# Public entrypoint
# -------------------------

async def scrape_all_divisions() -> Tuple[str, None, str]:
    _require_env()

    today = date.today().isoformat()
    headers = _auth_headers()

    sections = []

    async with aiohttp.ClientSession(headers=headers) as session:
        for league_id, label in TOURNAMENTS:
            fixtures = await fetch_all_fixtures(session, league_id)

            if not fixtures:
                raise RuntimeError(f"No fixtures found for {label}")

            sections.append(build_division_section(label, fixtures))

    html = f"""<!doctype html>
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

    return html, None, f"yfl_u11_form_guide_{today}.html"
