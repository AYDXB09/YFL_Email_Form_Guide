# yfl_scraper.py
# Final restored version – API-based, auto-week discovery, legacy-compatible

import os
import aiohttp
from datetime import date
from collections import defaultdict
from typing import List, Tuple, Dict, Any


# ---------------- CONFIG ----------------

API_BASE = "https://api.sportstack.ai/api/v1"
ORGANIZER = "yfl"
COMPETITION_ID = 4

TOURNAMENTS: List[Tuple[int, str]] = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]

FORM_DEPTH = 8  # same visual depth as old UI


# ---------------- AUTH ----------------

def _auth_headers() -> Dict[str, str]:
    token = os.environ.get("SPORTSTACK_API_TOKEN")
    if not token:
        raise RuntimeError("Missing SPORTSTACK_API_TOKEN")

    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Origin": "https://leaguehub-yfl.sportstack.ai",
        "Referer": "https://leaguehub-yfl.sportstack.ai/",
    }


# ---------------- API ----------------

async def fetch_fixtures_for_week(
    session: aiohttp.ClientSession, league_id: int, week_id: int
) -> List[Dict[str, Any]]:
    url = (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
        f"?league_id={league_id}&competition_id={COMPETITION_ID}&week_id={week_id}"
    )
    async with session.get(url) as r:
        if r.status != 200:
            return []
        data = await r.json()
        return data.get("data", data)


async def discover_week_ids(
    session: aiohttp.ClientSession, league_id: int
) -> List[int]:
    # brute-force discovery exactly like the UI
    discovered = set()
    for wid in range(40, 90):
        fixtures = await fetch_fixtures_for_week(session, league_id, wid)
        if fixtures:
            discovered.add(wid)
    return sorted(discovered)


async def fetch_all_fixtures(
    session: aiohttp.ClientSession, league_id: int
) -> List[Dict[str, Any]]:
    week_ids = await discover_week_ids(session, league_id)
    all_fixtures = []

    for wid in week_ids:
        fixtures = await fetch_fixtures_for_week(session, league_id, wid)
        all_fixtures.extend(fixtures)

    return all_fixtures


# ---------------- FORM LOGIC ----------------

def result_for_team(f: Dict[str, Any], team: str) -> str:
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


def build_team_form(fixtures: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    per_team = defaultdict(list)

    fixtures = sorted(
        fixtures,
        key=lambda f: (f["date"], f["start_at"]),
    )

    for f in fixtures:
        if not f.get("has_finished"):
            continue

        home = f["home_team_name"]
        away = f["away_team_name"]

        per_team[home].append(result_for_team(f, home))
        per_team[away].append(result_for_team(f, away))

    return {
        team: results[-FORM_DEPTH:]
        for team, results in per_team.items()
    }


# ---------------- HTML ----------------

def build_division_section(label: str, fixtures: List[Dict[str, Any]]) -> str:
    if not fixtures:
        return f"<h2>{label}</h2><p><em>No fixtures available.</em></p>"

    form = build_team_form(fixtures)

    rows = []
    for team, results in sorted(form.items()):
        bubbles = "".join(
            f"<span class='f {r}'>{r}</span>" for r in results
        )
        rows.append(
            f"<tr><td>{team}</td><td>{bubbles}</td></tr>"
        )

    return f"""
    <section>
      <h2>{label}</h2>
      <table>
        <tr><th>Club</th><th>Form</th></tr>
        {''.join(rows)}
      </table>
    </section>
    """


def build_inline_division_section(label: str, fixtures: List[Dict[str, Any]]) -> str:
    # email-safe minimal table (Division 3 only)
    if not fixtures:
        return f"<h2>{label}</h2><p>No fixtures available.</p>"

    form = build_team_form(fixtures)

    rows = []
    for team, results in sorted(form.items()):
        rows.append(
            f"<tr><td>{team}</td><td>{''.join(results)}</td></tr>"
        )

    return f"""
    <h2>{label}</h2>
    <table border="1" cellpadding="4" cellspacing="0">
      <tr><th>Club</th><th>Form</th></tr>
      {''.join(rows)}
    </table>
    """


# ---------------- MAIN ENTRY ----------------

async def scrape_all_divisions(*_args):
    headers = _auth_headers()
    today = date.today().isoformat()

    full_sections = []
    inline_div3_html = None

    async with aiohttp.ClientSession(headers=headers) as session:
        for league_id, label in TOURNAMENTS:
            fixtures = await fetch_all_fixtures(session, league_id)

            section = build_division_section(label, fixtures)
            full_sections.append(section)

            if label == "U11 Division 3":
                inline_div3_html = build_inline_division_section(label, fixtures)

    full_html = f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>YFL Weekly Form Guide — U11</title>
      <style>
        body {{ font-family: Arial; background:#0b1220; color:#fff }}
        table {{ width:100%; border-collapse:collapse }}
        td,th {{ padding:6px }}
        .f.W {{ color:#3fb950 }}
        .f.D {{ color:#d29922 }}
        .f.L {{ color:#f85149 }}
      </style>
    </head>
    <body>
      <h1>YFL Weekly Form Guide — U11</h1>
      <p>Generated: {today}</p>
      {''.join(full_sections)}
    </body>
    </html>
    """

    return full_html, inline_div3_html, f"yfl_u11_form_guide_{today}.html"
