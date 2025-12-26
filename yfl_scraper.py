# yfl_scraper.py
#
# Scrapes YFL LeagueHub (Div 1–3) and builds:
#  - full HTML report with tab-like buttons (all 3 divisions)
#  - inline HTML containing only Division 3 table
#
# Adapted from a working Colab script; uses env vars and is CI-friendly.

from datetime import date
import re

import pandas as pd
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

BASE = "https://leaguehub-yfl.sportstack.ai"
LOGIN_URL = f"{BASE}/re/login"

# Tournament IDs (change these for other age groups / divisions)
# Only IDs and labels are needed; panel IDs are derived from labels.
TOURNAMENTS = [
    (90, "U11 Division 1"),
    (91, "U11 Division 2"),
    (92, "U11 Division 3"),
]


def _panel_id_from_label(label: str) -> str:
    """Generate a safe HTML ID from a division label."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return slug or "panel"


async def _scrape_division(page, tournament_id: int, label: str):
    """Scrape a single division and return rows_html + metadata."""

    all_fixtures = []  # all fixtures: played, scheduled, voided
    all_results = []   # only valid played matches (for stats cross-check)
    seen_weeks = set()
    official_stats = {}

    print(f"\n==============================\n📂 Scraping {label} (tournament {tournament_id})\n==============================")

    def _clean_team_name(raw: str) -> str:
        return re.sub(r"\(D\d+\)", "", raw).strip()

    def _extract_league_rows(soup: BeautifulSoup):
        """Return the best-guess collection of rows for the league table.

        The LeagueHub UI recently changed markup; this helper tries multiple
        selectors (table-based and div/role-based) so we don't break when the
        structure moves away from <table>.
        """

        selectors = [
            "app-league-group-table tr",
            "app-league-table tr",
            "table tr",
            "[role='row']",
            ".table-row",
        ]

        for sel in selectors:
            rows = soup.select(sel)
            if rows:
                return rows
        return []

    def _extract_cells(tr):
        """Get cell-like elements for a row regardless of markup."""
        tds = tr.find_all("td")
        if len(tds) >= 9:
            return tds

        # New layout might use div/span rows instead of <td>.
        divs = tr.find_all(["div", "span"], recursive=False)
        if len(divs) >= 9:
            return divs

        # Fall back to any descendants to avoid hard failure.
        return tr.find_all(["td", "div", "span"])

    def _extract_team_names_from_fixture(soup: BeautifulSoup, known_teams):
        """Parse home/away names even if the layout changed."""
        def _unique(seq):
            out = []
            for item in seq:
                if item not in out:
                    out.append(item)
            return out

        candidates = []
        name_selectors = [
            "[data-testid='home-team-name']",
            "[data-testid='away-team-name']",
            "[data-testid='home-team']",
            "[data-testid='away-team']",
            ".team-name",
            ".club-name",
            ".team",
            "p.font-semibold",
            "span.font-semibold",
            "p.text-sm",
            "span.text-sm",
        ]

        for sel in name_selectors:
            for el in soup.select(sel):
                txt = el.get_text(" ", strip=True)
                if not txt:
                    continue
                candidates.append(_clean_team_name(txt))

        if len(candidates) < 2:
            # Fallback: look for known team names in the card text
            card_text = soup.get_text(" ", strip=True)
            for team in known_teams:
                if re.search(rf"\b{re.escape(team)}\b", card_text, re.I):
                    candidates.append(team)

        uniq = _unique(candidates)
        if len(uniq) >= 2:
            return uniq[0], uniq[1]
        return None, None

    async def _read_week_header():
        """Return (week_no, header_text) if present."""
        header_text = None
        header_loc = page.locator("app-fixture-list").locator("text=/Week\\s+\\d+/i").first
        if await header_loc.count():
            header_text = (await header_loc.inner_text()).strip()
        else:
            header_loc = page.locator("text=/Week\\s+\\d+/i").first
            if await header_loc.count():
                header_text = (await header_loc.inner_text()).strip()

        if not header_text:
            return None, None

        m = re.search(r"Week\s+(\d+)", header_text, re.I)
        if not m:
            return None, header_text
        return int(m.group(1)), header_text

    async def _go_to_previous_week():
        """Click the previous-week control if present."""
        selectors = [
            "app-fixture-list button:has(app-icon[name='arrow-left'])",
            "app-fixture-list button:has(app-icon[name='chevron-left'])",
            "button:has(app-icon[name='arrow-left'])",
            "button:has-text('Previous')",
            "button:has-text('Prev')",
        ]

        for sel in selectors:
            btn = page.locator(sel).first
            try:
                if await btn.count():
                    await btn.click()
                    await page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue
        return False

    async def _open_week_dropdown():
        """Try to open the Week dropdown."""
        triggers = [
            "app-fixture-list button:has-text('Week')",
            "button:has-text('Week')",
            "[role='combobox']",
            "div[role='button']:has-text('Week')",
        ]
        for sel in triggers:
            btn = page.locator(sel).first
            try:
                if await btn.count():
                    await btn.click()
                    await page.wait_for_timeout(500)
                    return True
            except Exception:
                continue
        return False

    async def _get_week_options():
        """Collect week labels from the dropdown."""
        if not await _open_week_dropdown():
            return []

        option_sets = [
            page.locator("div[role='option']"),
            page.locator("li[role='option']"),
            page.locator("app-fixture-list [role='option']"),
            page.locator(".mat-option"),
        ]
        options = []
        for loc in option_sets:
            try:
                count = await loc.count()
            except Exception:
                continue
            for i in range(count):
                try:
                    txt = (await loc.nth(i).inner_text()).strip()
                except Exception:
                    continue
                if txt:
                    options.append(txt)
            if options:
                break

        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

        # De-duplicate, preserve order
        seen = set()
        uniq = []
        for opt in options:
            if opt not in seen:
                seen.add(opt)
                uniq.append(opt)
        return uniq

    async def _select_week_option(label: str):
        """Open the dropdown and select the given label."""
        if not await _open_week_dropdown():
            raise RuntimeError(f"Cannot open Week dropdown to select '{label}'")

        option_selectors = [
            f"div[role='option']:has-text('{label}')",
            f"li[role='option']:has-text('{label}')",
            f".mat-option:has-text('{label}')",
            f"[role='option']:has-text('{label}')",
        ]
        for sel in option_selectors:
            opt = page.locator(sel).first
            try:
                if await opt.count():
                    await opt.click()
                    await page.wait_for_timeout(1200)
                    return
            except Exception:
                continue
        raise RuntimeError(f"Week option '{label}' not found in dropdown")

    # ------------------ OPEN TOURNAMENT ------------------
    tournament_url = f"{BASE}/re/tournament/{tournament_id}"
    print(f"➡ Opening tournament page {tournament_url}...")
    await page.goto(tournament_url)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1500)
    # Debug screenshot before waiting for rows (helps CI artifacts)
    try:
        await page.screenshot(path=f"debug_{tournament_id}_before_rows.png", full_page=True)
    except Exception:
        pass

    # Wait for league rows to be injected (headers render first, rows async)
    league_row_selectors = [
        "tr[role='row']",
        "table tbody tr",
    ]
    try:
        await page.wait_for_selector(
            ",".join(league_row_selectors),
            timeout=15000,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Timeout waiting for league rows for {label} using selectors {league_row_selectors}"
        ) from exc
        "app-league-group-table tr",
        "app-league-table tr",
    ]
    for sel in league_row_selectors:
        try:
            await page.wait_for_selector(sel, timeout=15000)
            break
        except Exception:
            continue

    # ------------------ OFFICIAL TABLE ------------------
    print("\n📊 Parsing official League Table…")
    league_html = await page.content()
    league_soup = BeautifulSoup(league_html, "html.parser")
    rows = _extract_league_rows(league_soup)
    if not rows:
        raise RuntimeError(f"No league rows found for {label} after page load.")

    for tr in rows:
        cells = _extract_cells(tr)
        if len(cells) < 6:
            continue

        texts = [c.get_text(" ", strip=True) for c in cells]
        try:
            pos = int(texts[0])
        except (ValueError, IndexError):
            continue  # header row or malformed

        team_raw = texts[1] if len(texts) > 1 else ""
        team_name = _clean_team_name(team_raw)

        try:
            played = int(texts[2])
            w = int(texts[3])
            d = int(texts[4])
            l = int(texts[5])
        except (ValueError, IndexError):
            continue

        gf_ga_idx = 6
        gd_idx = 7
        pts_idx = 8

        gf = ga = None
        gf_ga_text = texts[gf_ga_idx] if len(texts) > gf_ga_idx else ""
        gf_ga_match = re.match(r"(\d+)\s*/\s*(\d+)", gf_ga_text)
        if gf_ga_match:
            gf = int(gf_ga_match.group(1))
            ga = int(gf_ga_match.group(2))
        elif len(texts) >= 10:
            try:
                gf = int(texts[6])
                ga = int(texts[7])
                gd_idx = 8
                pts_idx = 9
            except ValueError:
                continue
        else:
            continue

        gd_text = texts[gd_idx] if len(texts) > gd_idx else ""
        pts_text = texts[pts_idx] if len(texts) > pts_idx else ""
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
    if not official_stats:
        raise RuntimeError(f"No official league data found for {label} — aborting.")

    # logos per team
    team_logos = {t: None for t in official_stats.keys()}

    # ------------------ FIXTURES (WEEK BY WEEK) ------------------
    print("\n🔍 Week-by-week scrape (fixtures)…\n")

    week_options = await _get_week_options()
    if not week_options:
        print("⚠ Could not read Week dropdown options; falling back to pagination buttons.")
        week_iter = None
    else:
        # scrape latest first
        week_iter = list(reversed(week_options))

    if week_iter is not None:
        for opt in week_iter:
            try:
                await _select_week_option(opt)
            except Exception as exc:
                print(f"⚠ Failed to select week '{opt}': {exc}")
                continue
    for _ in range(30):  # safety limit
        week_no, header = await _read_week_header()
        if week_no is None:
            print("⚠ No Week header found. Stopping.")
            break

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

            week_no, header = await _read_week_header()
            if week_no is None:
                print(f"⚠ No Week header after selecting '{opt}'. Skipping.")
                continue
            if week_no in seen_weeks:
                print(f"⏹ Week {week_no} already scraped. Skip duplicate.")
                continue
            seen_weeks.add(week_no)

            parts = header.split("-", 1)
            date_text = parts[1] if len(parts) > 1 else header
            try:
                dt = dateparser.parse(date_text, fuzzy=True).date()
                dt_str = dt.strftime("%d %b %Y")
            except Exception:
                dt = None
                dt_str = ""

            print(f"📅 Week {week_no} — {dt_str} (selected '{opt}')")

            fixtures_loc = page.locator("app-fixture-list app-single-fixture")
            count = await fixtures_loc.count()
            for i in range(count):
                fixture = fixtures_loc.nth(i)
                html = await fixture.inner_html()
                soup = BeautifulSoup(html, "html.parser")

                # team names: try explicit selectors first, then fallback to regex
                home, away = _extract_team_names_from_fixture(soup, official_stats.keys())
                if not home or not away:
                    names = soup.find_all(string=re.compile(r"\(D\d+\)"))
                    if len(names) < 2:
                        continue
                    home = _clean_team_name(names[0])
                    away = _clean_team_name(names[1])

                # logos from <img>
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
            # team names: try explicit selectors first, then fallback to regex
            home, away = _extract_team_names_from_fixture(soup, official_stats.keys())
            if not home or not away:
                names = soup.find_all(string=re.compile(r"\(D\d+\)"))
                if len(names) < 2:
                    continue
                home = _clean_team_name(names[0])
                away = _clean_team_name(names[1])

            # logos from <img>
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
    else:
        for _ in range(30):  # safety limit
            week_no, header = await _read_week_header()
            if week_no is None:
                print("⚠ No Week header found. Stopping.")
                break

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

                # team names: try explicit selectors first, then fallback to regex
                home, away = _extract_team_names_from_fixture(soup, official_stats.keys())
                if not home or not away:
                    names = soup.find_all(string=re.compile(r"\(D\d+\)"))
                    if len(names) < 2:
                        continue
                    home = _clean_team_name(names[0])
                    away = _clean_team_name(names[1])

                # logos from <img>
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
            moved = await _go_to_previous_week()
            if not moved:
                print("⏹ No previous-week button found. Finished.")
                break
        # previous week button
        moved = await _go_to_previous_week()
        if not moved:
            print("⏹ No previous-week button found. Finished.")
            break

    # ------------------ BUILD FORM TIMELINE ------------------
    today = date.today()

    if not all_fixtures:
        print("❌ No fixtures scraped – cannot build form.")
        return {"label": label, "rows_html": "", "official_stats": official_stats, "team_logos": team_logos}

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

    return {
        "label": label,
        "rows_html": rows_html,
    }


async def scrape_all_divisions(username: str, password: str):
    """Top-level scraper used by main.py.

    Returns:
        full_html (str): HTML for all 3 divisions with tab buttons.
        inline_div3_html (str): HTML section for Division 3 only (for inline email).
        output_filename (str): Suggested filename for the full HTML.
    """
    print("🔐 Using provided YFL credentials for login.")

    divisions_data = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # ------------------ LOGIN ONCE ------------------
        print("➡ Opening login page...")
        await page.goto(LOGIN_URL)
        await page.wait_for_timeout(1500)

        # email
        for sel in [
            "input[id='1']",
            "input[placeholder='Enter Email']",
            "input[placeholder*='Email']",
            "input[type='text']",
        ]:
            try:
                await page.fill(sel, username)
                print(f"✔ Email filled via {sel}")
                break
            except Exception:
                continue

        # password
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

        # login button
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

        # ------------------ SCRAPE EACH DIVISION ------------------
        for tid, label in TOURNAMENTS:
            panel_id = _panel_id_from_label(label)
            div_data = await _scrape_division(page, tid, label)
            div_data["panel_id"] = panel_id
            divisions_data.append(div_data)

        await browser.close()

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
