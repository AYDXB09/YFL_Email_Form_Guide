
# yfl_scraper.py — OPTION 1 (API-based, CI-safe)
# Uses Sportstack JSON API instead of UI scraping for league tables.
# Tested pattern: /api/v1/organizer/yfl/parent/competitions/4/leagues/{league_id}/overview

import os
import asyncio
import json
from datetime import date
from typing import List, Tuple, Dict, Any

import aiohttp
from playwright.async_api import async_playwright

BASE_WEB = "https://leaguehub-yfl.sportstack.ai"
LOGIN_URL = f"{BASE_WEB}/re/login"
API_BASE = "https://api.sportstack.ai/api/v1"

# YFL organizer / parent competition (from DevTools)
ORGANIZER = "yfl"
PARENT_COMPETITION_ID = 4

TOURNAMENTS: List[Tuple[int, str]] = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]

async def login_and_get_cookies() -> Dict[str, str]:
    user = os.environ.get("YFL_USERNAME")
    pwd = os.environ.get("YFL_PASSWORD")
    if not user or not pwd:
        raise RuntimeError("Missing YFL_USERNAME / YFL_PASSWORD")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(LOGIN_URL, wait_until="networkidle")
        await page.fill("input[name='email']", user)
        await page.fill("input[name='password']", pwd)
        await page.click("button[type='submit']")
        await page.wait_for_load_state("networkidle")

        cookies = await page.context.cookies()
        await browser.close()

    return {c["name"]: c["value"] for c in cookies}

async def fetch_league_overview(
    session: aiohttp.ClientSession, league_id: int
) -> Dict[str, Any]:
    url = (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/competitions/"
        f"{PARENT_COMPETITION_ID}/leagues/{league_id}/overview"
    )
    async with session.get(url) as resp:
        if resp.status != 200:
            raise RuntimeError(f"API {url} failed with {resp.status}")
        return await resp.json()

def build_table_html(label: str, overview: Dict[str, Any]) -> str:
    standings = overview.get("standings", [])
    if not standings:
        raise RuntimeError(f"No standings data for {label}")

    rows = []
    for row in standings:
        rows.append(f"""<tr>
<td>{row.get('position','')}</td>
<td>{row.get('teamName','')}</td>
<td>{row.get('played','')}</td>
<td>{row.get('won','')}</td>
<td>{row.get('drawn','')}</td>
<td>{row.get('lost','')}</td>
<td>{row.get('goalsFor','')}/{row.get('goalsAgainst','')}</td>
<td>{row.get('goalDifference','')}</td>
<td>{row.get('points','')}</td>
</tr>""")

    return f"""<section>
<h2>{label}</h2>
<table border="1" cellspacing="0" cellpadding="4">
<thead>
<tr>
<th>#</th><th>Club</th><th>P</th><th>W</th><th>D</th><th>L</th>
<th>GF/GA</th><th>GD</th><th>PTS</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</section>"""

async def scrape_all_divisions():
    today = date.today().isoformat()
    cookies = await login_and_get_cookies()

    jar = aiohttp.CookieJar()
    for k, v in cookies.items():
        jar.update_cookies({k: v})

    sections = []
    async with aiohttp.ClientSession(cookie_jar=jar) as session:
        for league_id, label in TOURNAMENTS:
            overview = await fetch_league_overview(session, league_id)
            sections.append(build_table_html(label, overview))

    full_html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>YFL U11 Form Guide</title></head>
<body>
<h1>YFL U11 Form Guide</h1>
<p>Generated: {today}</p>
{''.join(sections)}
</body>
</html>"""

    return full_html, None, f"yfl_u11_form_guide_{today}.html"
