
# yfl_scraper.py
# FINAL — API-based data source, ZIP-original visuals and logic preserved
# Mode A: standings + form computed from fixtures only (no API standings)

import os
import aiohttp
from datetime import datetime, date
from collections import defaultdict

# -----------------------------
# Configuration (unchanged)
# -----------------------------

API_BASE = "https://api.sportstack.ai/api/v1"
ORGANIZER = "yfl"
COMPETITION_ID = 4

TOURNAMENTS = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]

# -----------------------------
# Helpers
# -----------------------------

def _require_env():
    if not os.getenv("SPORTSTACK_API_TOKEN"):
        raise RuntimeError("Missing SPORTSTACK_API_TOKEN")

def _headers():
    return {
        "Authorization": f"Bearer {os.getenv('SPORTSTACK_API_TOKEN')}",
        "Accept": "application/json",
    }

# -----------------------------
# API fetch
# -----------------------------

async def fetch_all_fixtures(session, league_id):
    url = (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
        f"?league_id={league_id}&competition_id={COMPETITION_ID}"
    )
    async with session.get(url) as r:
        if r.status != 200:
            return []
        return await r.json()

# -----------------------------
# Core logic (ZIP-compatible)
# -----------------------------

def normalize_fixtures(fixtures):
    teams = defaultdict(lambda: {
        "P": 0, "W": 0, "D": 0, "L": 0,
        "GF": 0, "GA": 0, "PTS": 0,
        "form": []
    })

    for f in fixtures:
        if f.get("is_voided") or f.get("is_canceled"):
            teams[f["home_team_name"]]["form"].append("V")
            teams[f["away_team_name"]]["form"].append("V")
            continue

        ht, at = f["home_team_name"], f["away_team_name"]
        hs, as_ = f["home_team_score"], f["away_team_score"]

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
            **s,
            "GD": s["GF"] - s["GA"],
            "form": s["form"][-5:]
        })

    rows.sort(key=lambda r: (-r["PTS"], -r["GD"], -r["GF"]))
    return rows

# -----------------------------
# HTML rendering (unchanged visuals)
# -----------------------------

def render_table(title, rows):
    body = ""
    for i, r in enumerate(rows, 1):
        body += (
            f"<tr><td>{i}</td><td>{r['club']}</td>"
            f"<td>{r['P']}</td><td>{r['W']}</td><td>{r['D']}</td><td>{r['L']}</td>"
            f"<td>{r['GF']}/{r['GA']}</td><td>{r['GD']}</td><td>{r['PTS']}</td>"
            f"<td>{''.join(r['form'])}</td></tr>"
        )
    return f"<h2>{title}</h2><table>{body}</table>"

# -----------------------------
# Entry point (signature preserved)
# -----------------------------

async def scrape_all_divisions(*_args):
    _require_env()
    today = date.today().isoformat()
    sections = []
    inline_div3 = ""

    async with aiohttp.ClientSession(headers=_headers()) as session:
        for league_id, label in TOURNAMENTS:
            fixtures = await fetch_all_fixtures(session, league_id)
            rows = normalize_fixtures(fixtures)
            html = render_table(label, rows)
            sections.append(html)
            if label.endswith("Division 3"):
                inline_div3 = html

    full_html = (
        "<html><body>"
        f"<h1>YFL Weekly Form Guide — U11</h1><p>{today}</p>"
        f"{''.join(sections)}"
        "</body></html>"
    )

    return full_html, inline_div3, "yfl_u11_form_guide.html"
