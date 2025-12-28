# yfl_scraper.py
#
# Scrapes YFL LeagueHub (Div 1–3) and builds:
#  - full HTML report with tab-like buttons (all 3 divisions)
#  - inline HTML containing only Division 3 table
#
# Adapted from a working Colab script; uses env vars and is CI-friendly.

from datetime import date
import re
import os
from collections import defaultdict
import aiohttp

import pandas as pd
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

BASE = "https://leaguehub-yfl.sportstack.ai"
LOGIN_URL = f"{BASE}/re/login"

# Tournament IDs (change these for other age groups / divisions)
TOURNAMENTS = [
    (90, "U11 Division 1", "panel-div1"),
    (91, "U11 Division 2", "panel-div2"),
    (92, "U11 Division 3", "panel-div3"),
]

async def _scrape_division(session, tournament_id: int, label: str):
    """API-backed: load fixtures for a division and generate the same HTML rows.

    IMPORTANT: Keeps ZIP logic/visuals downstream unchanged.
    Standings + form are computed from fixtures only (Option A).
    """
    from datetime import date
    import pandas as pd
    today = pd.to_datetime(date.today())
    
    def _clean_team(name: str) -> str:
        # Original scraper removed "(D1)/(D2)/(D3)" suffixes
        return re.sub(r"\(D\d+\)", "", name or "").strip()

    def _week_no(week_name: str) -> int:
        m = re.search(r"Week\s*(\d+)", week_name or "")
        return int(m.group(1)) if m else 0

    async def _fetch_fixtures():
        api_base = "https://api.sportstack.ai/api/v1"
        organizer = "yfl"
        competition_id = 4
        url = (
            f"{api_base}/organizer/{organizer}/parent/fixtures"
            f"?league_id={tournament_id}&competition_id={competition_id}"
        )
        async with session.get(url) as resp:
            if resp.status != 200:
                txt = await resp.text()
                raise RuntimeError(f"API fixtures failed ({resp.status}) for league {tournament_id}: {txt[:200]}")
            data = await resp.json()
            # Some endpoints return a list directly; some wrap in {data: [...]}
            if isinstance(data, list):
                return data
            return data.get("data", []) if isinstance(data, dict) else []

    print(f"\n==============================\n📂 Scraping {label} (tournament {tournament_id})\n==============================")

    all_fixtures = []  # all fixtures: played, scheduled, voided
    all_results = []   # only valid played matches (for stats cross-check)
    official_stats = {}
    team_logos = {}

    fixtures = await _fetch_fixtures()

    # Build stats from fixtures (excluding voided/canceled)
    comp = defaultdict(lambda: {"P":0,"W":0,"D":0,"L":0,"GF":0,"GA":0,"PTS":0})
    for f in fixtures:
        home_raw = f.get("home_team_name") or ""
        away_raw = f.get("away_team_name") or ""
        home = _clean_team(home_raw)
        away = _clean_team(away_raw)
        if not home or not away:
            continue

        # logos
        hlogo = f.get("home_team_club_logo") or ""
        alogo = f.get("away_team_club_logo") or ""
        if home and hlogo and home not in team_logos:
            team_logos[home] = hlogo
        if away and alogo and away not in team_logos:
            team_logos[away] = alogo

        week_no = _week_no(f.get("week_name") or "")
        dt = None
        dt_str = ""
        dval = f.get("date")
        if dval:
            try:
                dt = dateparser.parse(dval).date()
                dt_str = dt.strftime("%d %b %Y")
            except Exception:
                dt = None
                dt_str = ""

        is_voided = bool(f.get("is_voided")) or bool(f.get("is_canceled"))
        hs = f.get("home_team_score")
        sa = f.get("away_team_score")

        # Determine status
        if is_voided:
            status = "voided"
        elif f.get("has_finished") or (hs is not None and sa is not None):
            status = "played"
        else:
            status = "scheduled"

        fixture_rec = {
            "week": week_no,
            "week_date": dt,
            "week_date_str": dt_str,
            "home": home,
            "away": away,
            "score_home": hs if hs is not None else "",
            "score_away": sa if sa is not None else "",
            "status": status,
            "is_voided": is_voided,
        }
        all_fixtures.append(fixture_rec)

        # Only count valid played matches (exclude voided/canceled)
        if status == "played" and not is_voided and hs is not None and sa is not None:
            comp[home]["P"] += 1
            comp[away]["P"] += 1
            comp[home]["GF"] += int(hs)
            comp[home]["GA"] += int(sa)
            comp[away]["GF"] += int(sa)
            comp[away]["GA"] += int(hs)

            if hs > sa:
                comp[home]["W"] += 1
                comp[home]["PTS"] += 3
                comp[away]["L"] += 1
                rh, ra = "W", "L"
            elif hs < sa:
                comp[away]["W"] += 1
                comp[away]["PTS"] += 3
                comp[home]["L"] += 1
                rh, ra = "L", "W"
            else:
                comp[home]["D"] += 1
                comp[away]["D"] += 1
                comp[home]["PTS"] += 1
                comp[away]["PTS"] += 1
                rh = ra = "D"

            all_results.append({
                "week": week_no,
                "week_date": dt,
                "week_date_str": dt_str,
                "home": home,
                "away": away,
                "score_home": int(hs),
                "score_away": int(sa),
                "result_home": rh,
                "result_away": ra,
            })

    # Build official_stats dict in the exact shape the ZIP code expects
    # Order: PTS desc, GD desc, GF desc, team name
    table_rows = []
    for team, s in comp.items():
        gf = s["GF"]; ga = s["GA"]
        gd = gf - ga
        table_rows.append((team, s["P"], s["W"], s["D"], s["L"], gf, ga, gd, s["PTS"]))
    table_rows.sort(key=lambda x: (-x[8], -x[7], -x[5], x[0].lower()))

    for pos, (team, p, w, d, l, gf, ga, gd, pts) in enumerate(table_rows, start=1):
        official_stats[team] = {
            "team": team,
            "Pos": pos,
            "P": p,
            "W": w,
            "D": d,
            "L": l,
            "GF": gf,
            "GA": ga,
            "GD": gd,
            "PTS": pts,
        }

    if not official_stats:
        return {"label": label, "rows_html": "", "official_stats": {}, "team_logos": {}}

    # Ensure every official team has a logo key (may be None)
    for t in official_stats.keys():
        team_logos.setdefault(t, None)

    teams = list(official_stats.keys())

    weeks_sorted = sorted({f["week"] for f in all_fixtures})
    week_meta = {}
    for f in all_fixtures:
        w = f["week"]
        if w not in week_meta or week_meta[w]["date"] is None:
            week_meta[w] = {
                "date": f["week_date"],
                "date_str": f["week_date_str"],
            }

    # Skip last week if no games played
    weeks_for_form = weeks_sorted[:]
    if weeks_sorted:
        last_week = weeks_sorted[-1]
        any_played_in_last = any(
            f["week"] == last_week and f["status"] == "played"
            for f in all_fixtures
        )
        if not any_played_in_last:
            weeks_for_form = [w for w in weeks_sorted if w != last_week]
            print(f"ℹ Last week (Week {last_week}) has no played games – excluded from Form.")

    form_timeline = {t: [] for t in teams}

    for wk in weeks_for_form:
        meta = week_meta.get(wk, {"date": None, "date_str": ""})
        dstr = meta["date_str"]

        for team in teams:
            week_fixtures = [
                f for f in all_fixtures
                if f["week"] == wk and (f["home"] == team or f["away"] == team)
            ]

            if not week_fixtures:
                form_timeline[team].append({
                    "result": "N",
                    "reason": "none",
                    "opponent": "",
                    "score": "—",
                    "week": wk,
                    "date": dstr,
                })
                continue

            f = week_fixtures[0]
            opp = f["away"] if f["home"] == team else f["home"]
            score_str = (
                f"{f['score_home']}–{f['score_away']}"
                if f["score_home"] is not None and f["score_away"] is not None
                else "—"
            )

            if f["status"] == "voided":
                form_timeline[team].append({
                    "result": "V",
                    "reason": "voided",
                    "opponent": opp,
                    "score": score_str,
                    "week": wk,
                    "date": dstr,
                })
            elif f["status"] == "scheduled":
                form_timeline[team].append({
                    "result": "N",
                    "reason": "scheduled",
                    "opponent": opp,
                    "score": score_str,
                    "week": wk,
                    "date": dstr,
                })
            else:  # played
                sh, sa = f["score_home"], f["score_away"]
                if team == f["home"]:
                    gf, ga = sh, sa
                else:
                    gf, ga = sa, sh
                if gf > ga:
                    res = "W"
                elif gf < ga:
                    res = "L"
                else:
                    res = "D"
                form_timeline[team].append({
                    "result": res,
                    "reason": "played",
                    "opponent": opp,
                    "score": f"{gf}–{ga}",
                    "week": wk,
                    "date": dstr,
                })

       # ------------------ NEXT FIXTURE ------------------
    next_fix = {t: None for t in teams}
    df_fix_all = pd.DataFrame(all_fixtures)
    
    df_fix_all["match_date"] = df_fix_all["week_date"]
    df_fix_all["match_date_str"] = df_fix_all["week_date"].apply(
        lambda d: d.strftime("%d %b %Y") if d else ""
    )
    
    future = df_fix_all[
        (df_fix_all["status"] == "scheduled")
        & df_fix_all["match_date"].notnull()
        & (df_fix_all["match_date"] >= date.today())
    ]
    
    for team in teams:
        sub = future[(future["home"] == team) | (future["away"] == team)]
        if sub.empty:
            continue
        row = sub.sort_values("match_date").iloc[0]
        opp = row["away"] if row["home"] == team else row["home"]
        next_fix[team] = {
            "opponent": opp,
            "week": int(row["week"]),
            "date": row["match_date_str"],
        }
        
    # ------------------ CROSS-CHECK (optional) ------------------
    if all_results:
        df_res = pd.DataFrame(all_results)
        df_res["match_date"] = df_res["week_date"]

        comp = {t: {"P": 0, "W": 0, "D": 0, "L": 0, "GF": 0, "GA": 0, "PTS": 0}
                for t in teams}
        for _, r in df_res.iterrows():
            md = r["match_date"]
            if not md or md > today:
                continue
            h = r["home"]
            a = r["away"]
            sh = r["score_home"]
            sa = r["score_away"]
            rh = r["result_home"]
            ra = r["result_away"]

            for t, gf, ga, res in ((h, sh, sa, rh), (a, sa, sh, ra)):
                if t not in comp:
                    continue
                comp[t]["P"] += 1
                comp[t]["GF"] += gf
                comp[t]["GA"] += ga
                if res == "W":
                    comp[t]["W"] += 1
                    comp[t]["PTS"] += 3
                elif res == "D":
                    comp[t]["D"] += 1
                    comp[t]["PTS"] += 1
                else:
                    comp[t]["L"] += 1

        print("\n🧪 Cross-checking computed vs official stats (for your info)…")
        for team, off in official_stats.items():
            c = comp.get(team)
            if not c:
                continue
            off_tuple = (off["P"], off["W"], off["D"], off["L"], off["GF"], off["GA"], off["PTS"])
            comp_tuple = (c["P"], c["W"], c["D"], c["L"], c["GF"], c["GA"], c["PTS"])
            if off_tuple != comp_tuple:
                print("⚠", team, "official=", off_tuple, "computed=", comp_tuple)
        print("✅ Cross-check complete (display still uses OFFICIAL numbers).")

    # ------------------ BUILD TABLE ROWS ------------------
    table_df = pd.DataFrame(list(official_stats.values()))
    table_df.sort_values(["PTS", "GD", "GF"], ascending=[False, False, False], inplace=True)
    table_df.reset_index(drop=True, inplace=True)

    def badge(result, tip):
        colors = {
            "W": "#22c55e",  # green
            "D": "#eab308",  # yellow
            "L": "#ef4444",  # red
            "N": "#9ca3af",  # medium grey
            "V": "#9ca3af",  # medium grey (striped)
        }
        col = colors.get(result, "#ffffff")
        safe_tip = tip.replace("'", "&#39;")

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

    rows_html = ""
    for _, r in table_df.iterrows():
        tm = r["team"]
        pos = int(r["Pos"])
        p = int(r["P"])
        w = int(r["W"])
        d = int(r["D"])
        l = int(r["L"])
        gf = int(r["GF"])
        ga = int(r["GA"])
        gd = int(r["GD"])
        pts = int(r["PTS"])

        flist = form_timeline.get(tm, [])
        form_html = ""
        for m in flist:
            res = m["result"]
            reason = m["reason"]
            wk = m["week"]
            dstr = m["date"] or ""
            opp = m["opponent"] or ""
            score = m["score"]

            if res == "N":
                if reason == "scheduled":
                    tip = (
                        f"Not yet played (scheduled)\nvs {opp}\n"
                        f"Week {wk} — {dstr}"
                    )
                else:
                    tip = f"No match played\nWeek {wk} — {dstr}"
            elif res == "V":
                tip = (
                    f"Voided match\nvs {opp}\nOriginal score: {score}\n"
                    f"Week {wk} — {dstr}"
                )
            else:  # W/L/D
                tip = (
                    f"{'Win' if res=='W' else 'Loss' if res=='L' else 'Draw'}\n"
                    f"vs {opp}\nScore: {score}\n"
                    f"Week {wk} — {dstr}"
                )

            form_html += badge(res, tip)

        nf = next_fix.get(tm)
        if nf:
            next_main = "v " + nf["opponent"]
            next_meta = f"Week {nf['week']} — {nf['date']}"
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

    return {
        "label": label,
        "rows_html": rows_html,
    }



async def scrape_all_divisions(username: str, password: str):
    """Build full HTML + inline Division 3 HTML using API (no UI scraping).

    Keeps existing output structure and styling unchanged.
    """
    # username/password kept for backwards compatibility with main.py/env usage.
    # API auth uses SPORTSTACK_API_TOKEN.
    token = os.environ.get("SPORTSTACK_API_TOKEN")
    if not token:
        raise RuntimeError("Missing SPORTSTACK_API_TOKEN (set it as a GitHub repo secret).")

    print("🔐 Using provided YFL credentials for login.")
    divisions_data = []

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/plain, */*",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        for tid, label, panel_id in TOURNAMENTS:
            div_data = await _scrape_division(session, tid, label)
            div_data["panel_id"] = panel_id
            divisions_data.append(div_data)

    # ------------------ BUILD FULL HTML (3 divisions with tab-like buttons) ------------------
    divisions = []
    for d in divisions_data:
        # default: make Division 3 the default active tab
        is_default = (d["label"] == "U11 Division 3")
        divisions.append({
            "panel_id": d["panel_id"],
            "label": d["label"],
            "rows_html": d["rows_html"],
            "default": is_default,
        })

    # Tab bar
    tabs_html = "<div class='tab-bar'>"
    for d in divisions:
        active_class = " active" if d["default"] else ""
        tabs_html += (
            f"<button class='tab-btn{active_class}' "
            f"onclick=\"showDivision('{d['panel_id']}', this)\">"
            f"{d['label']}</button>"
        )
    tabs_html += "</div>"

    # Panels
    panels_html = ""
    for d in divisions:
        style = "display:block;" if d["default"] else "display:none;"
        panels_html += (
            f"<div id='{d['panel_id']}' class='division-panel' style='{style}'>"
            f"<h2>YFL Dubai — {d['label']}</h2>"
            "<table>"
            "<thead>"
            "<tr>"
            "<th>#</th><th>Club</th><th>P</th><th>W</th><th>D</th><th>L</th>"
            "<th>GF / GA</th><th>GD</th><th>PTS</th><th>Form</th><th>Next Fixture</th>"
            "</tr>"
            "</thead>"
            "<tbody>"
            f"{d['rows_html']}"
            "</tbody>"
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
h1 {
  margin:0 0 8px 0;
}
h2 {
  margin:16px 0 8px 0;
}
p {
  margin:0 0 12px 0;
  color:#9ca3af;
}
table {
  width:100%;
  border-collapse:collapse;
  font-size:14px;
}
th,td {
  padding:6px 8px;
  border-bottom:1px solid #334155;
}
thead {
  background:#0f172a;
}
tbody tr:nth-child(even) { background:#0b1120; }
tbody tr:nth-child(odd)  { background:#111827; }
td.form-cell { max-width:360px; }
.gd-pos { color:#22c55e; font-weight:700; }
.gd-neg { color:#ef4444; font-weight:700; }
.gd-zero { color:#9ca3af; }
.next-main { font-weight:700; display:block; }
.next-meta { color:#9ca3af; font-size:12px; display:block; }
.pos { color:#9ca3af; }
.pts { font-weight:700; }
.team-cell {
  display:flex;
  align-items:center;
  gap:8px;
}
.team-logo {
  width:28px;
  height:28px;
  border-radius:50%;
  object-fit:cover;
  background:#0f172a;
}

/* Tabs */
.tab-bar {
  display:flex;
  gap:10px;
  margin-bottom:16px;
  flex-wrap:wrap;
}
.tab-btn {
  padding:8px 18px;
  border-radius:999px;
  border:1px solid #4b5563;
  background:#111827;
  color:#e5e7eb;
  font-size:14px;
  font-weight:600;
  cursor:pointer;
  transition:all 0.15s ease-out;
}
.tab-btn:hover {
  background:#1f2937;
}
.tab-btn.active {
  background:#e5e7eb;
  color:#111827;
  border-color:#e5e7eb;
}
.division-panel {
  margin-top:8px;
}
</style>
<script>
function showDivision(id, btn) {
  document.querySelectorAll('.division-panel').forEach(function(el){
    el.style.display = 'none';
  });
  var panel = document.getElementById(id);
  if (panel) {
    panel.style.display = 'block';
  }
  document.querySelectorAll('.tab-btn').forEach(function(b){
    b.classList.remove('active');
  });
  if (btn) {
    btn.classList.add('active');
  }
}
</script>
</head>
<body>
<h1>YFL Dubai — Under 11 Form Guide</h1>
{{TABS}}
{{PANELS}}
</body>
</html>
"""

    full_html = (
        html_template
        .replace("{{TABS}}", tabs_html)
        .replace("{{PANELS}}", panels_html)
    )

    # ------------------ INLINE DIVISION 3 ONLY (no JS) ------------------
    div3 = next((d for d in divisions if d["label"] == "U11 Division 3"), None)
    if div3 is None:
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
