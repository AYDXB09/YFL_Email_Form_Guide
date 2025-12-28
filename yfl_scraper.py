# yfl_scraper.py
#
# RESTORED OUTPUT (inline Division 3 table in email + full attachment with tabs),
# but using Sportstack API (no UI scraping) and NO extra dependencies.
#
# Requirements: none beyond stdlib (keeps existing workflow green).
# Secrets required:
#   - SPORTSTACK_API_TOKEN (Bearer token value WITHOUT the "Bearer " prefix)
#
# Notes:
# - main.py still passes (username, password). We accept but do not use them.
# - We preserve the old HTML/CSS/JS structure so email_sender/main.py keep working.

import os
import json
import re
import asyncio
from datetime import date, datetime
from typing import Dict, Any, List, Tuple, Optional
import urllib.request
import urllib.error

BASE_WEB = "https://leaguehub-yfl.sportstack.ai"
API_BASE = "https://api.sportstack.ai/api/v1"
ORGANIZER = "yfl"
PARENT_COMPETITION_ID = 4

# Tournament IDs (change these for other age groups / divisions)
TOURNAMENTS: List[Tuple[int, str, str]] = [
    (90, "U11 Division 1", "panel-div1"),
    (91, "U11 Division 2", "panel-div2"),
    (92, "U11 Division 3", "panel-div3"),
]

# ------------------ HTTP (stdlib) ------------------

def _bearer_token() -> str:
    tok = os.environ.get("SPORTSTACK_API_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("Missing SPORTSTACK_API_TOKEN (set as GitHub repo secret).")
    return tok

def _http_get_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {_bearer_token()}",
            "Accept": "application/json",
            "User-Agent": "YFL-Form-Guide/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = ""
        raise RuntimeError(f"API call failed ({e.code}) for URL: {url} {detail[:200]}") from e

async def api_get_json(url: str) -> Any:
    return await asyncio.to_thread(_http_get_json, url)

# ------------------ Data fetch ------------------

async def fetch_league_overview(league_id: int) -> Dict[str, Any]:
    url = f"{API_BASE}/organizer/{ORGANIZER}/parent/competitions/{PARENT_COMPETITION_ID}/leagues/{league_id}/overview"
    data = await api_get_json(url)
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected overview payload for league {league_id}")
    return data

def _parse_week_num(week_name: str) -> Optional[int]:
    m = re.search(r"Week\s+(\d+)", week_name or "")
    return int(m.group(1)) if m else None

async def fetch_all_fixtures_for_league(league_id: int) -> List[Dict[str, Any]]:
    # The fixtures endpoint needs week_id, but week_id is NOT the UI week number.
    # We brute-scan a safe range and deduplicate by fixture id.
    seen: Dict[int, Dict[str, Any]] = {}

    # This range covers observed IDs (you showed ~52..69). Keep it wide but bounded.
    for week_id in range(40, 90):
        url = (
            f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
            f"?league_id={league_id}&competition_id={PARENT_COMPETITION_ID}&week_id={week_id}"
        )
        try:
            data = await api_get_json(url)
        except RuntimeError:
            continue

        if isinstance(data, list):
            for fx in data:
                if isinstance(fx, dict) and "id" in fx:
                    seen[int(fx["id"])] = fx

    return list(seen.values())

# ------------------ HTML helpers (copied style/structure from the working version) ------------------

def _badge(result: str, tip: str) -> str:
    colors = {
        "W": "#22c55e",  # green
        "D": "#eab308",  # yellow
        "L": "#ef4444",  # red
        "N": "#9ca3af",  # medium grey
        "V": "#9ca3af",  # medium grey (striped)
    }
    col = colors.get(result, "#ffffff")
    safe_tip = (tip or "").replace("'", "&#39;")

    base_style = (
        "display:inline-flex;align-items:center;justify-content:center;"
        "width:24px;height:24px;border-radius:999px;"
        f"border:2px solid {col};"
        "font-size:11px;font-weight:700;margin-right:4px;"
    )

    if result == "V":
        bg_style = (
            "background:repeating-linear-gradient(45deg,"
            "#9ca3af 0,#9ca3af 4px,#e5e7eb 4px,#e5e7eb 8px);"
            "color:#020617;"
        )
    else:
        bg_style = f"background:#020617;color:{col};"

    return f"<span title='{safe_tip}' style='{base_style}{bg_style}'>{result}</span>"

def _iso_to_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _build_team_logo_map(fixtures: List[Dict[str, Any]]) -> Dict[str, str]:
    logos: Dict[str, str] = {}
    for f in fixtures:
        ht = f.get("home_team_name")
        at = f.get("away_team_name")
        hl = f.get("home_team_club_logo")
        al = f.get("away_team_club_logo")
        if ht and hl and ht not in logos:
            logos[str(ht)] = str(hl)
        if at and al and at not in logos:
            logos[str(at)] = str(al)
    return logos

def _compute_form_and_next(
    fixtures: List[Dict[str, Any]],
    team_names: List[str],
) -> Tuple[Dict[str, List[str]], Dict[int, Dict[str, str]], Dict[str, Dict[str, Any]]]:
    """
    Returns:
      - form_map[team] -> list of results aligned to selected weeks (last up to 9)
      - week_meta[week_num] -> {"date": ..., "date_str": ...}
      - next_fix[team] -> {"opponent":..., "week":..., "date":...}
    """
    # Build week meta
    week_meta: Dict[int, Dict[str, str]] = {}
    for f in fixtures:
        wk_name = str(f.get("week_name") or "")
        wk_num = _parse_week_num(wk_name)
        if wk_num is None:
            continue
        d = _iso_to_date(str(f.get("date") or ""))
        if wk_num not in week_meta:
            week_meta[wk_num] = {
                "date": d.isoformat() if d else "",
                "date_str": d.strftime("%d/%m/%Y") if d else "",
            }
        else:
            # keep earliest date string if missing
            if not week_meta[wk_num].get("date_str") and d:
                week_meta[wk_num]["date"] = d.isoformat()
                week_meta[wk_num]["date_str"] = d.strftime("%d/%m/%Y")

    weeks_sorted = sorted(week_meta.keys())
    # Show last 9 weeks like the old UI
    weeks_shown = weeks_sorted[-9:] if len(weeks_sorted) > 9 else weeks_sorted

    # Index fixtures by (team, week_num) for played results
    played_map: Dict[Tuple[str, int], str] = {}
    today = date.today()

    # For next fixture
    next_fix: Dict[str, Dict[str, Any]] = {}

    for f in fixtures:
        wk_num = _parse_week_num(str(f.get("week_name") or ""))
        if wk_num is None:
            continue

        d = _iso_to_date(str(f.get("date") or ""))
        has_finished = bool(f.get("has_finished"))
        has_started = bool(f.get("has_started"))
        is_scheduled = bool(f.get("is_scheduled", True))

        home = str(f.get("home_team_name") or "")
        away = str(f.get("away_team_name") or "")

        # Next fixture logic: earliest future/non-finished fixture per team
        if d and is_scheduled and (not has_finished) and (d >= today):
            for team, opp in [(home, away), (away, home)]:
                if not team:
                    continue
                curr = next_fix.get(team)
                if curr is None or d < curr["date_obj"]:
                    next_fix[team] = {
                        "opponent": opp,
                        "week": wk_num,
                        "date": d.strftime("%d/%m/%Y"),
                        "date_obj": d,
                    }

        # Form logic: only completed matches with scores
        if has_finished:
            hs = f.get("home_team_score")
            as_ = f.get("away_team_score")
            try:
                hs_i = int(hs)
                as_i = int(as_)
            except Exception:
                continue

            if home:
                if hs_i > as_i:
                    played_map[(home, wk_num)] = "W"
                elif hs_i < as_i:
                    played_map[(home, wk_num)] = "L"
                else:
                    played_map[(home, wk_num)] = "D"
            if away:
                if as_i > hs_i:
                    played_map[(away, wk_num)] = "W"
                elif as_i < hs_i:
                    played_map[(away, wk_num)] = "L"
                else:
                    played_map[(away, wk_num)] = "D"

    form_map: Dict[str, List[str]] = {}
    for tm in team_names:
        seq: List[str] = []
        for wk in weeks_shown:
            seq.append(played_map.get((tm, wk), "N"))
        form_map[tm] = seq

    # strip helper field
    for k in list(next_fix.keys()):
        next_fix[k].pop("date_obj", None)

    return form_map, {wk: week_meta[wk] for wk in weeks_shown}, next_fix

def _build_rows_html(
    label: str,
    standings: List[Dict[str, Any]],
    fixtures: List[Dict[str, Any]],
) -> str:
    # Map team -> logo from fixtures (works even when standings lacks logos)
    team_logos = _build_team_logo_map(fixtures)

    # Extract team names from standings in table order
    # Sort by position if present
    def _pos(row):
        try:
            return int(row.get("position", 9999))
        except Exception:
            return 9999

    standings_sorted = sorted(standings, key=_pos)

    team_names = [str(r.get("teamName") or r.get("team_name") or "") for r in standings_sorted]
    team_names = [t for t in team_names if t]

    form_map, week_meta, next_fix = _compute_form_and_next(fixtures, team_names)

    rows_html = ""
    for row in standings_sorted:
        tm = str(row.get("teamName") or row.get("team_name") or "")
        if not tm:
            continue

        pos = _safe_int(row.get("position"))
        p = _safe_int(row.get("played"))
        w = _safe_int(row.get("won"))
        d = _safe_int(row.get("drawn"))
        l = _safe_int(row.get("lost"))
        gf = _safe_int(row.get("goalsFor"))
        ga = _safe_int(row.get("goalsAgainst"))
        gd = _safe_int(row.get("goalDifference"))
        pts = _safe_int(row.get("points"))

        # Form badges
        seq = form_map.get(tm, [])
        weeks = list(week_meta.keys())
        form_html = ""
        for i, res in enumerate(seq):
            wk = weeks[i] if i < len(weeks) else ""
            dstr = week_meta.get(wk, {}).get("date_str", "")
            tip = f"Week {wk} — {dstr}" if wk else ""
            form_html += _badge(res, tip)

        # Next fixture
        nf = next_fix.get(tm)
        if nf:
            next_main = "v " + str(nf.get("opponent") or "")
            next_meta = f"Week {nf.get('week','')} — {nf.get('date','')}"
        else:
            next_main = "No upcoming fixture"
            next_meta = "—"

        gd_class = "gd-pos" if gd > 0 else "gd-neg" if gd < 0 else "gd-zero"
        gd_text = f"+{gd}" if gd > 0 else str(gd)

        logo_url = team_logos.get(tm)
        if logo_url:
            team_cell_html = (
                "<div class='team-cell'>"
                f"<img class='team-logo' src='{logo_url}' alt='{tm} logo' />"
                f"<span>{tm}</span>"
                "</div>"
            )
        else:
            team_cell_html = f"<div class='team-cell'><span>{tm}</span></div>"

        rows_html += (
            f"<tr>"
            f"<td class='pos'>{pos}</td>"
            f"<td class='team'>{team_cell_html}</td>"
            f"<td>{p}</td>"
            f"<td>{w}</td>"
            f"<td>{d}</td>"
            f"<td>{l}</td>"
            f"<td>{gf} / {ga}</td>"
            f"<td class='gd {gd_class}'>{gd_text}</td>"
            f"<td class='pts'>{pts}</td>"
            f"<td class='form-cell'>{form_html}</td>"
            f"<td class='next-cell'><span class='next-main'>{next_main}</span>"
            f"<span class='next-meta'>{next_meta}</span></td>"
            f"</tr>"
        )

    return rows_html

def _safe_int(x: Any) -> int:
    try:
        return int(x)
    except Exception:
        return 0

# ------------------ Main entrypoint (matches old behaviour) ------------------

async def scrape_all_divisions(username: str, password: str):
    """Top-level scraper used by main.py.

    Returns:
        full_html (str): HTML for all 3 divisions with tab buttons.
        inline_div3_html (str): HTML section for Division 3 only (for inline email).
        output_filename (str): Suggested filename for the full HTML.
    """
    # We keep the old print so logs look familiar
    print("🔐 Using provided YFL credentials for login.")
    if not username or not password:
        raise RuntimeError("Missing YFL_USERNAME / YFL_PASSWORD (main.py requires them).")

    # ------------------ Fetch all divisions via API ------------------
    divisions: List[Dict[str, Any]] = []
    for league_id, label, panel_id in TOURNAMENTS:
        print("\n==============================")
        print(f"📂 Fetching {label} (league {league_id}) via API")
        print("==============================")

        overview = await fetch_league_overview(league_id)
        standings = overview.get("standings") or overview.get("data", {}).get("standings") or []
        if not isinstance(standings, list):
            standings = []

        fixtures = await fetch_all_fixtures_for_league(league_id)

        rows_html = _build_rows_html(label, standings, fixtures) if standings else ""
        divisions.append({"id": panel_id, "label": label, "rows_html": rows_html})

    # ------------------ Build tabs + panels (same structure as the working version) ------------------

    tabs_html = ""
    panels_html = ""
    for i, div in enumerate(divisions):
        active = "active" if i == 0 else ""
        tabs_html += f"<button class='tab-btn {active}' data-target='{div['id']}'>{div['label']}</button>"

        panels_html += (
            f"<div id='{div['id']}' class='panel {active}'>"
            f"<h2>YFL Dubai — {div['label']}</h2>"
            "<table class='league-table'>"
            "<thead><tr>"
            "<th class='pos'>#</th>"
            "<th class='club'>Club</th>"
            "<th>P</th><th>W</th><th>D</th><th>L</th>"
            "<th>GF / GA</th><th>GD</th><th>PTS</th>"
            "<th>Form</th>"
            "<th>Next Fixture</th>"
            "</tr></thead>"
            f"<tbody>{div['rows_html']}</tbody>"
            "</table>"
            "</div>"
        )

    html_template = """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8" />
<title>YFL Dubai — U11 Form Guide</title>
<style>
body {
  background:#020617;
  color:#e5e7eb;
  font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  padding:20px;
}
h1 { margin:0 0 8px 0; }
h2 { margin:16px 0 10px 0; font-size:20px; }

.league-table {
  width:100%;
  border-collapse:collapse;
  font-size:14px;
  background:#020617;
  color:#e5e7eb;
}
.league-table thead { background:#0f172a; }
.league-table th, .league-table td {
  padding:8px 10px;
  border-bottom:1px solid #334155;
  vertical-align:middle;
}
.league-table td.pos { width:34px; font-weight:700; }
.league-table td.pts { font-weight:800; }
.team-cell { display:flex; align-items:center; gap:10px; }
.team-logo { width:28px; height:28px; border-radius:50%; object-fit:cover; background:#0f172a; }

.gd-pos { color:#22c55e; font-weight:700; }
.gd-neg { color:#ef4444; font-weight:700; }
.gd-zero { color:#e5e7eb; font-weight:700; }

.form-cell { white-space:nowrap; }
.next-cell { white-space:nowrap; }
.next-main { display:block; font-weight:700; }
.next-meta { display:block; font-size:12px; opacity:0.8; }

.tab-bar { display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap; }
.tab-btn {
  border:1px solid #334155;
  background:#0f172a;
  color:#e5e7eb;
  padding:6px 10px;
  border-radius:10px;
  cursor:pointer;
  font-weight:700;
}
.tab-btn.active { background:#111827; border-color:#64748b; }
.panel { display:none; }
.panel.active { display:block; }
</style>
</head>
<body>
<h1>YFL Dubai — Under 11 Form Guide</h1>
<div class="tab-bar">{{TABS}}</div>
{{PANELS}}
<script>
(function(){
  const btns = document.querySelectorAll('.tab-btn');
  const panels = document.querySelectorAll('.panel');
  function activate(targetId){
    btns.forEach(b => b.classList.toggle('active', b.dataset.target === targetId));
    panels.forEach(p => p.classList.toggle('active', p.id === targetId));
  }
  btns.forEach(b => b.addEventListener('click', () => activate(b.dataset.target)));
})();
</script>
</body>
</html>
"""

    full_html = (
        html_template
        .replace("{{TABS}}", tabs_html)
        .replace("{{PANELS}}", panels_html)
    )

    # ------------------ INLINE DIVISION 3 ONLY (no JS, same as working version) ------------------
    div3 = next((d for d in divisions if d["label"] == "U11 Division 3"), None)
    if div3 is None or not div3.get("rows_html"):
        inline_div3_html = "<p><strong>Division 3 data unavailable.</strong></p>"
    else:
        inline_div3_html = f"""
<h2>YFL Dubai — {div3['label']}</h2>
<table style="width:100%;border-collapse:collapse;font-size:14px;background:#020617;color:#e5e7eb;">
  <thead style="background:#0f172a;">
    <tr>
      <th style="padding:6px 8px;border-bottom:1px solid #334155;">#</th>
      <th style="padding:6px 8px;border-bottom:1px solid #334155;">Club</th>
      <th style="padding:6px 8px;border-bottom:1px solid #334155;">P</th>
      <th style="padding:6px 8px;border-bottom:1px solid #334155;">W</th>
      <th style="padding:6px 8px;border-bottom:1px solid #334155;">D</th>
      <th style="padding:6px 8px;border-bottom:1px solid #334155;">L</th>
      <th style="padding:6px 8px;border-bottom:1px solid #334155;">GF / GA</th>
      <th style="padding:6px 8px;border-bottom:1px solid #334155;">GD</th>
      <th style="padding:6px 8px;border-bottom:1px solid #334155;">PTS</th>
      <th style="padding:6px 8px;border-bottom:1px solid #334155;">Form</th>
      <th style="padding:6px 8px;border-bottom:1px solid #334155;">Next Fixture</th>
    </tr>
  </thead>
  <tbody>
    {div3['rows_html']}
  </tbody>
</table>
"""

    output_filename = "yfl_u11_form_guide.html"
    return full_html, inline_div3_html, output_filename
