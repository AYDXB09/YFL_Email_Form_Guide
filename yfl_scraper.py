# -*- coding: utf-8 -*-
"""
yfl_scraper.py — FINAL (API-based, CI-safe)

Features:
- Standings + fixtures via Sportstack API (no UI scraping)
- Week selection via env var YFL_WEEK_ID (required for fixtures)
- Uses SPORTSTACK_API_TOKEN (GitHub Actions repository secret)

Required env vars:
- SPORTSTACK_API_TOKEN
- YFL_WEEK_ID   (example: 69)

Optional env vars:
- YFL_ORGANIZER (default: yfl)
- YFL_COMPETITION_ID (default: 4)

Return signature matches main.py:
  (full_html, inline_div3_html, output_filename)
"""
import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

API_BASE = "https://api.sportstack.ai/api/v1"
WEB_ORIGIN = "https://leaguehub-yfl.sportstack.ai"

ORGANIZER = (os.getenv("YFL_ORGANIZER") or "yfl").strip() or "yfl"
COMPETITION_ID = int(os.getenv("YFL_COMPETITION_ID") or "4")

# Week selection (fixtures)
WEEK_ID_RAW = os.getenv("YFL_WEEK_ID")  # required for fixtures
WEEK_ID: Optional[int] = int(WEEK_ID_RAW) if WEEK_ID_RAW and WEEK_ID_RAW.isdigit() else None

# U11 divisions (league_id, label)
LEAGUES: List[Tuple[int, str]] = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]

TOKEN = os.getenv("SPORTSTACK_API_TOKEN")
if not TOKEN:
    raise RuntimeError("Missing SPORTSTACK_API_TOKEN (add as GitHub Actions repository secret).")

API_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Origin": WEB_ORIGIN,
    "Referer": f"{WEB_ORIGIN}/",
}


def _safe(x: Any) -> str:
    return "" if x is None else str(x)


async def _get_json(session: aiohttp.ClientSession, url: str) -> Dict[str, Any]:
    async with session.get(url, headers=API_HEADERS) as resp:
        if resp.status != 200:
            body = ""
            try:
                body = await resp.text()
            except Exception:
                pass
            raise RuntimeError(f"API call failed ({resp.status}) url={url} body={body[:500]}")
        return await resp.json()


# -------------------- Standings --------------------
def _overview_url(league_id: int) -> str:
    return (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/competitions/"
        f"{COMPETITION_ID}/leagues/{league_id}/overview"
    )


async def fetch_standings(session: aiohttp.ClientSession, league_id: int) -> List[Dict[str, Any]]:
    payload = await _get_json(session, _overview_url(league_id))

    # Try common shapes
    if isinstance(payload.get("standings"), list):
        return payload["standings"]

    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("standings"), list):
        return data["standings"]

    overview = payload.get("overview")
    if isinstance(overview, dict) and isinstance(overview.get("standings"), list):
        return overview["standings"]

    return []


# -------------------- Fixtures --------------------
def _fixtures_url(league_id: int, week_id: int) -> str:
    # From your DevTools:
    # /api/v1/organizer/yfl/parent/fixtures?league_id=92&competition_id=4&week_id=69
    return (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
        f"?league_id={league_id}&competition_id={COMPETITION_ID}&week_id={week_id}"
    )


def _extract_fixtures(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(payload.get("fixtures"), list):
        return payload["fixtures"]
    if isinstance(payload.get("data"), list):
        return payload["data"]
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("fixtures"), list):
        return data["fixtures"]
    return []


async def fetch_fixtures(session: aiohttp.ClientSession, league_id: int, week_id: int) -> List[Dict[str, Any]]:
    payload = await _get_json(session, _fixtures_url(league_id, week_id))
    return _extract_fixtures(payload)


# -------------------- HTML --------------------
def build_standings_table_html(label: str, standings: List[Dict[str, Any]]) -> str:
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


def _fixture_line(fx: Dict[str, Any]) -> str:
    home = fx.get("homeTeamName") or fx.get("homeTeam") or (fx.get("home") or {}).get("name")
    away = fx.get("awayTeamName") or fx.get("awayTeam") or (fx.get("away") or {}).get("name")
    hs = fx.get("homeScore")
    ays = fx.get("awayScore")
    status = fx.get("status") or fx.get("matchStatus") or fx.get("state") or ""
    kickoff = fx.get("kickoff") or fx.get("startTime") or fx.get("date") or fx.get("scheduledAt") or ""

    score = ""
    if hs is not None or ays is not None:
        score = f"{_safe(hs)}-{_safe(ays)}"

    left = f"{_safe(home)} vs {_safe(away)}".strip()
    right = " ".join(x for x in [score, str(kickoff).strip(), str(status).strip()] if x)
    return f"{left} — {right}".strip()


def build_fixtures_html(week_id: int, fixtures: List[Dict[str, Any]]) -> str:
    if not fixtures:
        return f"<h3>Fixtures (Week {week_id})</h3><p>No fixtures returned.</p>"
    items = "".join(f"<li>{_fixture_line(fx)}</li>" for fx in fixtures[:200])
    return f"<h3>Fixtures (Week {week_id})</h3><ul class='fixtures'>{items}</ul>"


def wrap_division(label: str, standings_html: str, fixtures_html: str) -> str:
    return f"<section class='division'><h2>{label}</h2>{standings_html}{fixtures_html}</section>"


def build_page(sections_html: str, generated: str, week_id: Optional[int]) -> str:
    wk = f"Week {week_id}" if week_id is not None else "Week (not set)"
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>YFL Weekly Form Guide - U11</title>
<style>
body {{ font-family: Arial, sans-serif; background: #0b1020; color: #e8eefc; margin: 0; padding: 24px; }}
h1 {{ margin: 0 0 8px 0; }}
h2 {{ margin: 28px 0 10px 0; }}
h3 {{ margin: 14px 0 8px 0; }}
section.division {{ background: rgba(255,255,255,0.04); padding: 16px; border-radius: 12px; margin: 18px 0; }}
table.standings {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
table.standings th, table.standings td {{ border-bottom: 1px solid rgba(255,255,255,0.12); padding: 8px; text-align: left; }}
table.standings th {{ background: rgba(255,255,255,0.06); }}
ul.fixtures {{ margin: 8px 0 0 18px; }}
</style>
</head>
<body>
<h1>YFL Weekly Form Guide - U11</h1>
<p>Generated: {generated} | {wk}</p>
{sections_html}
</body>
</html>"""


# -------------------- Entry point for main.py --------------------
async def scrape_all_divisions(*args, **kwargs):
    if WEEK_ID is None:
        raise RuntimeError("Missing YFL_WEEK_ID (set it in GitHub Actions variables/secrets, e.g. 69).")

    generated = date.today().isoformat()
    sections: List[str] = []
    div3_inline = ""

    async with aiohttp.ClientSession() as session:
        for league_id, label in LEAGUES:
            standings = await fetch_standings(session, league_id)
            if not standings:
                raise RuntimeError(f"No standings returned for {label} (league_id={league_id}).")

            fixtures = await fetch_fixtures(session, league_id, WEEK_ID)

            standings_html = build_standings_table_html(label, standings)
            fixtures_html = build_fixtures_html(WEEK_ID, fixtures)
            section = wrap_division(label, standings_html, fixtures_html)
            sections.append(section)

            if league_id == 92:
                div3_inline = build_page(section, generated, WEEK_ID)

    full_html = build_page("".join(sections), generated, WEEK_ID)
    output_filename = f"yfl_u11_form_guide_{generated}.html"
    return full_html, div3_inline, output_filename
