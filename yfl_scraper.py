# yfl_scraper.py
# FINAL CLEAN VERSION
# - API-based (Sportstack)
# - No Playwright
# - No stats_engine
# - Standings + form computed from fixtures only (Option A)
# - Voided games excluded from points, shown as 'V'
# - Compatible with existing main.py

import os
import aiohttp
from datetime import date
from collections import defaultdict
from typing import Tuple

API_BASE = "https://api.sportstack.ai/api/v1"
ORGANIZER = "yfl"
COMPETITION_ID = 4

TOURNAMENTS = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]


def _require_env():
    if not os.getenv("SPORTSTACK_API_TOKEN"):
        raise RuntimeError("Missing SPORTSTACK_API_TOKEN")


def _headers():
    return {
        "Authorization": f"Bearer {os.getenv('SPORTSTACK_API_TOKEN')}",
        "Accept": "application/json",
    }


async def _fetch_fixtures(session, league_id):
    url = (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
        f"?league_id={league_id}&competition_id={COMPETITION_ID}"
    )
    async with session.get(url) as r:
        if r.status != 200:
            return []
        data = await r.json()
        return data if isinstance(data, list) else data.get("data", [])


def _compute_table(fixtures):
    teams = defaultdict(lambda: {
        "P": 0, "W": 0, "D": 0, "L": 0,
        "GF": 0, "GA": 0, "PTS": 0,
        "form": []
    })

    for f in fixtures:
        ht = f.get("home_team_name")
        at = f.get("away_team_name")
        if not ht or not at:
            continue

        if f.get("is_voided") or f.get("is_canceled"):
            teams[ht]["form"].append("V")
            teams[at]["form"].append("V")
            continue

        hs = f.get("home_team_score")
        as_ = f.get("away_team_score")
        if hs is None or as_ is None:
            continue

        teams[ht]["P"] += 1
        teams[at]["P"] += 1
        teams[ht]["GF"] += hs
        teams[ht]["GA"] += as_
        teams[at]["GF"] += as_
        teams[at]["GA"] += hs

        if hs > as_:
            teams[ht]["W"] += 1
            teams[ht]["PTS"] += 3
            teams[ht]["form"].append("W")
            teams[at]["L"] += 1
            teams[at]["form"].append("L")
        elif hs < as_:
            teams[at]["W"] += 1
            teams[at]["PTS"] += 3
            teams[at]["form"].append("W")
            teams[ht]["L"] += 1
            teams[ht]["form"].append("L")
        else:
            teams[ht]["D"] += 1
            teams[at]["D"] += 1
            teams[ht]["PTS"] += 1
            teams[at]["PTS"] += 1
            teams[ht]["form"].append("D")
            teams[at]["form"].append("D")

    rows = []
    for club, s in teams.items():
        rows.append({
            "club": club,
            "P": s["P"],
            "W": s["W"],
            "D": s["D"],
            "L": s["L"],
            "GF": s["GF"],
            "GA": s["GA"],
            "GD": s["GF"] - s["GA"],
            "PTS": s["PTS"],
            "form": s["form"][-5:],
        })

    rows.sort(key=lambda r: (-r["PTS"], -r["GD"], -r["GF"]))
    return rows


def _render_table(title, rows):
    trs = []
    for i, r in enumerate(rows, 1):
        trs.append(
            f"<tr><td>{i}</td><td>{r['club']}</td>"
            f"<td>{r['P']}</td><td>{r['W']}</td><td>{r['D']}</td><td>{r['L']}</td>"
            f"<td>{r['GF']}/{r['GA']}</td><td>{r['GD']}</td><td>{r['PTS']}</td>"
            f"<td>{''.join(r['form'])}</td></tr>"
        )
    return (
        f"<h2>{title}</h2>"
        "<table border='1' cellspacing='0' cellpadding='4'>"
        "<tr><th>#</th><th>Club</th><th>P</th><th>W</th><th>D</th><th>L</th>"
        "<th>GF/GA</th><th>GD</th><th>PTS</th><th>Form</th></tr>"
        f"{''.join(trs)}"
        "</table>"
    )


async def scrape_all_divisions(*_args) -> Tuple[str, str, str]:
    _require_env()
    today = date.today().isoformat()

    sections = []
    inline_div3 = ""

    async with aiohttp.ClientSession(headers=_headers()) as session:
        for league_id, label in TOURNAMENTS:
            fixtures = await _fetch_fixtures(session, league_id)
            rows = _compute_table(fixtures)
            html = _render_table(label, rows)
            sections.append(html)
            if label.endswith("Division 3"):
                inline_div3 = html

    full_html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>YFL Weekly Form Guide — U11</title></head><body>"
        f"<h1>YFL Weekly Form Guide — U11</h1><p>Generated: {today}</p>"
        f"{''.join(sections)}</body></html>"
    )

    return full_html, inline_div3, "yfl_u11_form_guide.html"
