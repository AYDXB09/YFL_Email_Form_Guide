# yfl_scraper.py — FINAL, STABLE, API-ONLY
#
# - No UI scraping
# - Auto-resolves current week_id
# - Uses Sportstack API exactly like the web UI
# - CI-safe (GitHub Actions)
#
# REQUIRED ENV VAR:
#   SPORTSTACK_API_TOKEN   (GitHub repository secret)
#
# RETURNS:
#   (full_html, inline_div3_html, output_filename)

import os
from datetime import date
from typing import Any, Dict, List, Tuple

import aiohttp

# ---------------- CONFIG ----------------

API_BASE = "https://api.sportstack.ai/api/v1"
WEB_ORIGIN = "https://leaguehub-yfl.sportstack.ai"

ORGANIZER = "yfl"
COMPETITION_ID = 4

LEAGUES: List[Tuple[int, str]] = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]

TOKEN = os.getenv("SPORTSTACK_API_TOKEN")
if not TOKEN:
    raise RuntimeError("Missing SPORTSTACK_API_TOKEN (set as GitHub repo secret).")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Origin": WEB_ORIGIN,
    "Referer": f"{WEB_ORIGIN}/",
}

# ---------------- HELPERS ----------------

def _safe(x: Any) -> str:
    return "" if x is None else str(x)

async def _get_json(session: aiohttp.ClientSession, url: str) -> Dict[str, Any]:
    async with session.get(url, headers=HEADERS) as resp:
        if resp.status != 200:
            body = await resp.text()
            raise RuntimeError(f"API {resp.status} for {url}: {body[:300]}")
        return await resp.json()

# ---------------- WEEK RESOLUTION ----------------

async def resolve_current_week_id(session: aiohttp.ClientSession, league_id: int) -> int:
    """
    Calls fixtures endpoint WITHOUT week_id and extracts current week_id,
    exactly how the UI does it.
    """
    url = (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
        f"?league_id={league_id}&competition_id={COMPETITION_ID}"
    )
    payload = await _get_json(session, url)

    # Preferred: explicit currentWeekId
    if isinstance(payload.get("currentWeekId"), int):
        return payload["currentWeekId"]

    # Fallback: weeks list with isCurrent flag
    weeks = payload.get("weeks")
    if isinstance(weeks, list):
        for w in weeks:
            if w.get("isCurrent") is True and isinstance(w.get("id"), int):
                return w["id"]

    raise RuntimeError("Unable to auto-resolve current week_id")

# ---------------- STANDINGS ----------------

async def fetch_standings(session: aiohttp.ClientSession, league_id: int) -> List[Dict[str, Any]]:
    url = (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/competitions/"
        f"{COMPETITION_ID}/leagues/{league_id}/overview"
    )
    payload = await _get_json(session, url)

    if isinstance(payload.get("standings"), list):
        return payload["standings"]

    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("standings"), list):
        return data["standings"]

    raise RuntimeError(f"No standings returned for league {league_id}")

# ---------------- FIXTURES ----------------

async def fetch_fixtures(
    session: aiohttp.ClientSession, league_id: int, week_id: int
) -> List[Dict[str, Any]]:
    url = (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
        f"?league_id={league_id}&competition_id={COMPETITION_ID}&week_id={week_id}"
    )
    payload = await _get_json(session, url)

    if isinstance(payload.get("fixtures"), list):
        return payload["fixtures"]

    if isinstance(payload.get("data"), list):
        return payload["data"]

    return []

# ---------------- HTML BUILDERS ----------------

def build_standings_html(standings: List[Dict[str, Any]]) -> str:
    rows = []
    for r in standings:
        rows.append(
            "<tr>"
            f"<td>{_safe(r.get('position'))}</td>"
            f"<td>{_safe(r.get('teamName') or r.get('team') or r.get('name'))}</td>"
            f"<td>{_safe(r.get('played'))}</td>"
            f"<td>{_safe(r.get('won'))}</td>"
            f"<td>{_safe(r.get('drawn'))}</td>"
            f"<td>{_safe(r.get('lost'))}</td>"
            f"<td>{_safe(r.get('goalsFor'))}/{_safe(r.get('goalsAgainst'))}</td>"
            f"<td>{_safe(r.get('goalDifference'))}</td>"
            f"<td>{_safe(r.get('points'))}</td>"
            "</tr>"
        )

    return (
        "<table class='standings'>"
        "<thead><tr>"
        "<th>#</th><th>Club</th><th>P</th><th>W</th><th>D</th><th>L</th>"
        "<th>GF/GA</th><th>GD</th><th>PTS</th>"
        "</tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )

def build_fixtures_html(week_id: int, fixtures: List[Dict[str, Any]]) -> str:
    if not fixtures:
        return f"<h3>Fixtures (Week {week_id})</h3><p>No fixtures</p>"

    items = []
    for fx in fixtures:
        home = fx.get("homeTeamName")
        away = fx.get("awayTeamName")
        hs = fx.get("homeScore")
        as_ = fx.get("awayScore")
        score = f"{hs}-{as_}" if hs is not None else ""
        items.append(f"<li>{home} vs {away} {score}</li>")

    return f"<h3>Fixtures (Week {week_id})</h3><ul>{''.join(items)}</ul>"

def wrap_division(label: str, standings: str, fixtures: str) -> str:
    return f"<section><h2>{label}</h2>{standings}{fixtures}</section>"

def build_page(body: str, generated: str, week_id: int) -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>YFL Weekly Form Guide - U11</title>
</head>
<body>
<h1>YFL Weekly Form Guide - U11</h1>
<p>Generated {generated} | Week ID {week_id}</p>
{body}
</body>
</html>"""

# ---------------- ENTRY POINT ----------------

async def scrape_all_divisions(*args, **kwargs):
    today = date.today().isoformat()
    sections = []
    div3_inline = ""

    async with aiohttp.ClientSession() as session:
        for league_id, label in LEAGUES:
            week_id = await resolve_current_week_id(session, league_id)
            standings = await fetch_standings(session, league_id)
            fixtures = await fetch_fixtures(session, league_id, week_id)

            section = wrap_division(
                label,
                build_standings_html(standings),
                build_fixtures_html(week_id, fixtures),
            )
            sections.append(section)

            if league_id == 92:
                div3_inline = build_page(section, today, week_id)

    full_html = build_page("".join(sections), today, week_id)
    return full_html, div3_inline, f"yfl_u11_form_guide_{today}.html"
