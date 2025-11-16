# ============================================================
# YFL Dubai – U11 Div 1 / Div 2 / Div 3
# Enhanced League Table with Weekly Form (W/L/D/N/V) + Logos
# Single HTML with tabbed divisions + Gmail Email (OAuth2)
# ============================================================

# --- One-time installs (safe to re-run) ---
!pip install -U playwright nest_asyncio bs4 python-dateutil pandas \
  google-auth google-auth-oauthlib google-api-python-client
!playwright install chromium
!playwright install-deps

import nest_asyncio
nest_asyncio.apply()

from google.colab import userdata
from datetime import date
from pathlib import Path
import pandas as pd
import re
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

import os
import base64
from email.message import EmailMessage
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ============================================================
# 0) CONSTANTS
# ============================================================

BASE = "https://leaguehub-yfl.sportstack.ai"
LOGIN_URL = f"{BASE}/re/login"
CHROME_EXECUTABLE = "/root/.cache/ms-playwright/chromium-1194/chrome-linux/chrome"

# Tournament IDs
TOURNAMENTS = [
    (90, "U11 Division 1", "panel-div1"),
    (91, "U11 Division 2", "panel-div2"),
    (92, "U11 Division 3", "panel-div3"),
]

# Gmail scopes + OOB redirect
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
OOB_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"


# ============================================================
# 1) GMAIL OAUTH + EMAIL SENDER
# ============================================================

def get_gmail_creds(json_path="client_secret.json", token_path="gmail_token.json"):
    """
    Manual Gmail OAuth flow that works in Colab:
      - If gmail_token.json exists, reuse it
      - Else:
          * Print URL
          * You open it in browser
          * Copy-paste auth code back into Colab
    Uses the OOB redirect URI fix to avoid `redirect_uri` errors.
    """
    # Try existing token first
    if os.path.exists(token_path):
        try:
            print("🔐 Using existing Gmail token…")
            return Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception:
            print("⚠ Existing token invalid. Deleting and re-authorizing…")
            os.remove(token_path)

    print("🔐 Starting manual Gmail OAuth (Colab-compatible)…")

    # Build flow from client_secret.json
    flow = InstalledAppFlow.from_client_secrets_file(json_path, SCOPES)

    # CRITICAL: inject OOB redirect URI so Google accepts it
    flow.oauth2session.redirect_uri = OOB_REDIRECT_URI

    # Create auth URL
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    # Show URL
    print("\n👉 Open this URL in a NEW browser tab:")
    print(auth_url)

    # User copies code
    code = input("\n✏️ Paste the authorization code here:\n> ").strip()

    # Exchange code for token
    flow.fetch_token(code=code)
    creds = flow.credentials

    # Save token to reuse later
    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print("✅ Gmail authorization complete. Token saved as", token_path)
    return creds


def send_email_with_attachments(
    creds,
    receiver,
    subject,
    body,
    attachments=None,
):
    """
    Send an email with HTML attachment(s) using Gmail API.
    """
    if attachments is None:
        attachments = []

    service = build("gmail", "v1", credentials=creds)

    msg = EmailMessage()
    msg["To"] = receiver
    msg["Subject"] = subject
    msg.set_content(body)

    for path in attachments:
        with open(path, "rb") as f:
            data = f.read()
        filename = os.path.basename(path)
        # We attach as text/html; browsers will open it nicely
        msg.add_attachment(
            data,
            maintype="text",
            subtype="html",
            filename=filename,
        )

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    body = {"raw": raw}
    sent = service.users().messages().send(userId="me", body=body).execute()
    print("📨 Email sent. Message ID:", sent.get("id"))


# ============================================================
# 2) SCRAPER FOR ONE DIVISION
# ============================================================

async def scrape_division(tournament_id: int, label: str):
    """
    Scrape a single division (tournament) and return:
      {
        "label": label,
        "rows_html": "<tr>...</tr>...",
      }
    """

    # --- YFL login secrets from Colab ---
    email = userdata.get("YFLUsername")
    password = userdata.get("YFLPassword")
    if not email or not password:
        raise Exception(
            "❌ Secrets missing.\n"
            "Set YFLUsername and YFLPassword in Colab → Settings → User data."
        )

    all_fixtures = []  # all fixtures: played, scheduled, voided
    all_results = []   # only valid played matches (for stats cross-check)
    seen_weeks = set()
    official_stats = {}

    from playwright.async_api import async_playwright  # local import (already installed)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=CHROME_EXECUTABLE
        )
        page = await browser.new_page()

        print(f"\n==============================")
        print(f"📂 Scraping {label} (tournament {tournament_id})")
        print(f"==============================")

        # ------------------ LOGIN ------------------
        print("➡ Opening login page...")
        await page.goto(LOGIN_URL)
        await page.wait_for_timeout(1500)

        for sel in [
            "input[id='1']",
            "input[placeholder='Enter Email']",
            "input[placeholder*='Email']",
            "input[type='text']",
        ]:
            try:
                await page.fill(sel, email)
                print(f"✔ Email filled via {sel}")
                break
            except Exception:
                continue

        for sel in [
            "input[id='2']",
            "input[placeholder='Enter Password']",
            "input[placeholder*='Password']",
            "input[type='password']",
        ]:
            try:
                await page.fill(sel, password)
                print(f"✔ Password filled via {sel}")
                break
            except Exception:
                continue

        for sel in ["button[type='submit']", "button:has-text('Login')"]:
            try:
                await page.click(sel)
                print(f"✔ Login button clicked via {sel}")
                break
            except Exception:
                continue

        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(2000)
        print("✅ Login successful.")

        # ------------------ OPEN TOURNAMENT ------------------
        tournament_url = f"{BASE}/re/tournament/{tournament_id}"
        print(f"➡ Opening tournament page {tournament_url}...")
        await page.goto(tournament_url)
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(1500)

        # ------------------ OFFICIAL TABLE ------------------
        print("\n📊 Parsing official League Table…")
        league_html = await page.content()
        league_soup = BeautifulSoup(league_html, "html.parser")

        rows = league_soup.select("app-league-group-table tr")
        if not rows:
            rows = league_soup.select("table tr")

        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 9:
                continue
            try:
                pos = int(tds[0].get_text(strip=True))
            except ValueError:
                continue  # probably header

            team_raw = tds[1].get_text(" ", strip=True)
            team_name = re.sub(r"\(D\d+\)", "", team_raw).strip()

            try:
                played = int(tds[2].get_text(strip=True))
                w = int(tds[3].get_text(strip=True))
                d = int(tds[4].get_text(strip=True))
                l = int(tds[5].get_text(strip=True))
            except ValueError:
                continue

            gf_ga_text = tds[6].get_text(strip=True)
            gf_ga_match = re.match(r"(\d+)\s*/\s*(\d+)", gf_ga_text)
            if not gf_ga_match:
                continue
            gf = int(gf_ga_match.group(1))
            ga = int(gf_ga_match.group(2))

            gd_text = tds[7].get_text(strip=True)
            pts_text = tds[8].get_text(strip=True)
            try:
                gd = int(gd_text)
            except ValueError:
                gd = gf - ga
            try:
                pts = int(pts_text)
            except ValueError:
                pts = 0

            official_stats[team_name] = {
                "team": team_name,
                "Pos": pos,
                "P": played,
                "W": w,
                "D": d,
                "L": l,
                "GF": gf,
                "GA": ga,
                "GD": gd,
                "PTS": pts,
            }

        print(f"✅ Parsed official table for {len(official_stats)} teams.")

        # logos per team
        team_logos = {t: None for t in official_stats.keys()}

        # ------------------ FIXTURES (WEEK BY WEEK) ------------------
        print("\n🔍 Week-by-week scrape (fixtures)…\n")

        for _ in range(30):  # safety limit
            try:
                header = await page.locator(
                    "app-fixture-list p.text-xs"
                ).first.inner_text()
                header = header.strip()
            except Exception:
                print("⚠ No Week header found inside app-fixture-list. Stopping.")
                break

            m = re.search(r"Week\s+(\d+)", header)
            if not m:
                print("⚠ Could not parse week number from:", header)
                break
            week_no = int(m.group(1))
            if week_no in seen_weeks:
                print(f"⏹ Week {week_no} already scraped. Stop.")
                break
            seen_weeks.add(week_no)

            parts = header.split("-", 1)
            date_text = parts[1] if len(parts) > 1 else header
            try:
                dt = dateparser.parse(date_text, fuzzy=True).date()
                dt_str = dt.strftime("%d %b %Y")
            except Exception:
                dt = None
                dt_str = ""

            print(f"📅 Week {week_no} — {dt_str}")

            fixtures_loc = page.locator("app-fixture-list app-single-fixture")
            count = await fixtures_loc.count()
            for i in range(count):
                fixture = fixtures_loc.nth(i)
                html = await fixture.inner_html()
                soup = BeautifulSoup(html, "html.parser")

                # team names: look for strings containing "(D1)/(D2)/(D3)"
                names = soup.find_all(string=re.compile(r"\(D\d+\)"))
                if len(names) < 2:
                    continue
                home = re.sub(r"\(D\d+\)", "", names[0]).strip()
                away = re.sub(r"\(D\d+\)", "", names[1]).strip()

                # logos from <img> tags (first = home, last = away)
                imgs = soup.find_all("img")
                if len(imgs) >= 2:
                    home_logo_url = imgs[0].get("src", "").strip()
                    away_logo_url = imgs[-1].get("src", "").strip()
                    if home in team_logos and team_logos[home] is None and home_logo_url:
                        team_logos[home] = home_logo_url
                    if away in team_logos and team_logos[away] is None and away_logo_url:
                        team_logos[away] = away_logo_url

                # detect "Voided"
                is_voided = bool(soup.find(string=re.compile(r"\bVoided\b", re.I)))

                # score: 3 <p> tags (x, "-", y)
                score_div = soup.select_one(
                    "div.flex.flex-row.items-center.justify-center.gap-2"
                )
                score_home = score_away = None
                if score_div:
                    p_tags = score_div.find_all("p")
                    if len(p_tags) >= 3:
                        t0 = p_tags[0].get_text(strip=True)
                        t1 = p_tags[1].get_text(strip=True)
                        t2 = p_tags[2].get_text(strip=True)
                        if t0.isdigit() and t2.isdigit() and t1 in ["-", "–"]:
                            score_home = int(t0)
                            score_away = int(t2)

                if is_voided:
                    status = "voided"
                elif score_home is not None and score_away is not None:
                    status = "played"
                else:
                    status = "scheduled"

                fixture_rec = {
                    "week": week_no,
                    "week_date": dt,
                    "week_date_str": dt_str,
                    "home": home,
                    "away": away,
                    "status": status,
                    "score_home": score_home,
                    "score_away": score_away,
                }
                all_fixtures.append(fixture_rec)

                # Valid played match → for stats cross-check
                if status == "played":
                    sh, sa = score_home, score_away
                    rh = "W" if sh > sa else "L" if sh < sa else "D"
                    ra = "W" if sa > sh else "L" if sa < sh else "D"
                    all_results.append({
                        "week": week_no,
                        "week_date": dt,
                        "week_date_str": dt_str,
                        "home": home,
                        "away": away,
                        "score_home": sh,
                        "score_away": sa,
                        "result_home": rh,
                        "result_away": ra,
                    })

            # previous week button
            prev_btn = page.locator(
                "app-fixture-list button:has(app-icon[name='arrow-left'])"
            ).first
            try:
                if await prev_btn.count():
                    await prev_btn.click()
                    await page.wait_for_timeout(1500)
                    continue
                else:
                    print("⏹ No previous-week button found. Finished.")
                    break
            except Exception:
                print("⏹ Error clicking previous-week button; stopping.")
                break

        await browser.close()

    # ------------------ BUILD FORM TIMELINE ------------------
    today = date.today()

    if not official_stats:
        print("❌ No official league data – cannot build table.")
        return {"label": label, "rows_html": ""}

    teams = list(official_stats.keys())
    if not all_fixtures:
        print("❌ No fixtures scraped – cannot build form.")
        return {"label": label, "rows_html": ""}

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
        & (df_fix_all["match_date"] >= today)
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

    return {"label": label, "rows_html": rows_html}


# ============================================================
# 3) MASTER: SCRAPE ALL DIVISIONS, BUILD HTML, SEND EMAIL
# ============================================================

async def scrape_all_divisions():
    # Quick check so error message is nicer if secrets missing
    _email = userdata.get("YFLUsername")
    _password = userdata.get("YFLPassword")
    if not _email or not _password:
        raise Exception(
            "❌ Secrets missing.\n"
            "Set YFLUsername and YFLPassword in Colab → Settings → User data."
        )

    print("🔐 Loaded YFL credentials from Colab.")

    # Scrape each division sequentially
    div1 = await scrape_division(90, "U11 Division 1")
    div2 = await scrape_division(91, "U11 Division 2")
    div3 = await scrape_division(92, "U11 Division 3")

    divisions = [
        {"panel_id": "panel-div1", "label": div1["label"], "rows_html": div1["rows_html"], "default": False},
        {"panel_id": "panel-div2", "label": div2["label"], "rows_html": div2["rows_html"], "default": False},
        {"panel_id": "panel-div3", "label": div3["label"], "rows_html": div3["rows_html"], "default": True},  # default = Div 3
    ]

    # Build tab buttons
    tabs_html = "<div class='tab-bar'>"
    for d in divisions:
        active_class = " active" if d["default"] else ""
        tabs_html += (
            f"<button class='tab-btn{active_class}' "
            f"onclick=\"showDivision('{d['panel_id']}', this)\">"
            f"{d['label']}</button>"
        )
    tabs_html += "</div>"

    # Build panels
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

    # Final HTML template with big button-style tabs
    html_template = """
<!DOCTYPE html>
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
    html_output = (
        html_template
        .replace("{{TABS}}", tabs_html)
        .replace("{{PANELS}}", panels_html)
    )

    out_path = Path("yfl_u11_form_guide.html")
    out_path.write_text(html_output, encoding="utf-8")
    print("\n🎉 DONE! Saved yfl_u11_form_guide.html")
    print("➡ You can download it from the Files panel (folder icon on the left).")

    # ================== GMAIL STEP ==================
    print("\n📧 Preparing to send email with HTML attached…")
    creds = get_gmail_creds("client_secret.json", "gmail_token.json")
    send_email_with_attachments(
        creds=creds,
        receiver="yalama@gmail.com",  # change if you want
        subject="YFL Weekly U11 Form Guide (All Divisions)",
        body=(
            "Hi,\n\n"
            "Attached is the latest YFL Dubai U11 Form Guide (Divisions 1, 2, and 3) "
            "as an HTML file.\n\n"
            "Open it in a browser and hover over the form circles to see per-week details.\n\n"
            "— Your automated YFL bot 🤖"
        ),
        attachments=[str(out_path)],
    )
    print("✅ All done: scraped, built HTML, emailed.")


# ============================================================
# 4) HOW TO RUN (in a separate cell)
# ============================================================

# In a NEW cell, run:
await scrape_all_divisions()
