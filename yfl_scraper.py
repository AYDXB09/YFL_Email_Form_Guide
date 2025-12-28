"""
yfl_scraper.py — API-based (CI-safe) scraper that reproduces the legacy HTML attachment format.

Key points:
- Uses Sportstack JSON API (fixtures endpoint) with Bearer token (SPORTSTACK_API_TOKEN).
- Computes standings from fixtures (ignores void/canceled fixtures in points/GD/GF/GA).
- Builds the SAME attachment structure + styling as the previously working version:
  tabs + 3 division panels + standings table + form bubbles + next fixture column.
- Returns (full_html, inline_div3_html, output_filename) to match main.py expectations.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import aiohttp


# -----------------------------
# Config
# -----------------------------

API_BASE = "https://api.sportstack.ai/api/v1"
ORGANIZER = "yfl"
PARENT_COMPETITION_ID = 4

# (league_id, label, panel_id)
TOURNAMENTS: List[Tuple[int, str, str]] = [
    (90, "U11 Division 1", "panel-div1"),
    (91, "U11 Division 2", "panel-div2"),
    (92, "U11 Division 3", "panel-div3"),
]


# -----------------------------
# Helpers
# -----------------------------

def _require_env() -> None:
    if not os.environ.get("SPORTSTACK_API_TOKEN"):
        raise RuntimeError("Missing SPORTSTACK_API_TOKEN (set as GitHub repo secret).")


def _auth_headers() -> Dict[str, str]:
    token = os.environ.get("SPORTSTACK_API_TOKEN", "").strip()
    return {
        "accept": "application/json, text/plain, */*",
        "authorization": f"Bearer {token}",
        "origin": "https://leaguehub-yfl.sportstack.ai",
        "referer": "https://leaguehub-yfl.sportstack.ai/",
        "user-agent": "Mozilla/5.0 (compatible; YFL_Email_Form_Guide/1.0)",
    }


def _parse_api_payload(payload: Any) -> List[Dict[str, Any]]:
    """
    Sportstack endpoints sometimes return:
      - a list
      - {"data": [...]}
      - {"data": {"data": [...]}}
    Normalize to a list[dict].
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        d = payload.get("data")
        if isinstance(d, list):
            return [x for x in d if isinstance(x, dict)]
        if isinstance(d, dict):
            d2 = d.get("data")
            if isinstance(d2, list):
                return [x for x in d2 if isinstance(x, dict)]
    return []


_WEEK_RE = re.compile(r"Week\s+(\d+)", re.IGNORECASE)

def _week_number(week_name: str) -> Optional[int]:
    if not week_name:
        return None
    m = _WEEK_RE.search(week_name)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _parse_iso_date(d: str) -> Optional[date]:
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None


def _format_dd_mmm_yyyy(d: Optional[date]) -> str:
    if not d:
        return "—"
    return d.strftime("%d %b %Y")


def _safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None


def _team_key(team_name: str) -> str:
    return (team_name or "").strip().lower()


@dataclass
class TeamMeta:
    name: str
    logo: str = ""


@dataclass
class Fixture:
    week_id: int
    week_name: str
    week_num: int
    date: date
    start_at: str
    home: str
    away: str
    home_score: Optional[int]
    away_score: Optional[int]
    is_finished: bool
    is_voided: bool
    is_canceled: bool
    is_scheduled: bool
    league_name: str
    league_id: int
    home_logo: str
    away_logo: str


def _is_void_like(f: Dict[str, Any]) -> bool:
    # Use multiple flags (seen in your JSON sample)
    return bool(
        f.get("is_voided")
        or f.get("home_is_voided")
        or f.get("away_is_voided")
        or f.get("is_voided")  # some payloads
    )


def _is_canceled_like(f: Dict[str, Any]) -> bool:
    return bool(f.get("is_canceled"))


def _fixture_from_api_row(row: Dict[str, Any]) -> Optional[Fixture]:
    week_id = _safe_int(row.get("week_id"))
    week_name = (row.get("week_name") or "").strip()
    week_num = _week_number(week_name) or 0

    d = _parse_iso_date((row.get("date") or "").strip())
    if week_id is None or not d or not week_name or week_num == 0:
        return None

    home = (row.get("home_team_name") or "").strip()
    away = (row.get("away_team_name") or "").strip()
    if not home or not away:
        return None

    hs = _safe_int(row.get("home_team_score"))
    as_ = _safe_int(row.get("away_team_score"))

    is_finished = bool(row.get("has_finished") or row.get("is_finished"))
    is_scheduled = bool(row.get("is_scheduled"))
    is_voided = _is_void_like(row)
    is_canceled = _is_canceled_like(row)

    return Fixture(
        week_id=week_id,
        week_name=week_name,
        week_num=week_num,
        date=d,
        start_at=(row.get("start_at") or "").strip(),
        home=home,
        away=away,
        home_score=hs,
        away_score=as_,
        is_finished=is_finished,
        is_voided=is_voided,
        is_canceled=is_canceled,
        is_scheduled=is_scheduled,
        league_name=(row.get("league_name") or "").strip(),
        league_id=_safe_int(row.get("league_id")) or 0,
        home_logo=(row.get("home_team_club_logo") or "").strip(),
        away_logo=(row.get("away_team_club_logo") or "").strip(),
    )


async def fetch_all_fixtures(session: aiohttp.ClientSession, league_id: int) -> List[Fixture]:
    """
    Prefer the "no week_id" endpoint to avoid week_id mapping issues.
    If it fails or returns empty, fall back to trying a small set of recent week_ids.
    """
    url = (
        f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
        f"?league_id={league_id}&competition_id={PARENT_COMPETITION_ID}"
    )
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=45)) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"Fixtures API failed ({resp.status}) for league {league_id}: {text[:250]}")
        payload = await resp.json()

    rows = _parse_api_payload(payload)
    fixtures: List[Fixture] = []
    for r in rows:
        fx = _fixture_from_api_row(r)
        if fx:
            fixtures.append(fx)

    # If still empty, it might require week_id; attempt a conservative fallback
    if fixtures:
        return fixtures

    # fallback range: try a rolling window (safe default)
    for wid in range(40, 140):
        url2 = (
            f"{API_BASE}/organizer/{ORGANIZER}/parent/fixtures"
            f"?league_id={league_id}&competition_id={PARENT_COMPETITION_ID}&week_id={wid}"
        )
        async with session.get(url2, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 401:
                raise RuntimeError("Unauthenticated (401) — SPORTSTACK_API_TOKEN is missing/invalid.")
            if resp.status != 200:
                continue
            payload = await resp.json()

        rows = _parse_api_payload(payload)
        for r in rows:
            fx = _fixture_from_api_row(r)
            if fx:
                fixtures.append(fx)

    return fixtures


# -----------------------------
# Standings + Form computation
# -----------------------------

@dataclass
class TeamStats:
    team: str
    logo: str = ""
    p: int = 0
    w: int = 0
    d: int = 0
    l: int = 0
    gf: int = 0
    ga: int = 0
    pts: int = 0


def _ensure_team(stats: Dict[str, TeamStats], meta: Dict[str, TeamMeta], name: str, logo: str) -> None:
    k = _team_key(name)
    if k not in stats:
        stats[k] = TeamStats(team=name, logo=logo)
    if k not in meta:
        meta[k] = TeamMeta(name=name, logo=logo)
    # update logo if missing
    if not meta[k].logo and logo:
        meta[k].logo = logo
    if not stats[k].logo and logo:
        stats[k].logo = logo


def _accumulate_from_fixture(stats: Dict[str, TeamStats], meta: Dict[str, TeamMeta], f: Fixture) -> None:
    # Only count finished fixtures that are NOT void/canceled and have scores
    if not f.is_finished:
        return
    if f.is_voided or f.is_canceled:
        return
    if f.home_score is None or f.away_score is None:
        return

    _ensure_team(stats, meta, f.home, f.home_logo)
    _ensure_team(stats, meta, f.away, f.away_logo)

    hs = f.home_score
    as_ = f.away_score

    home = stats[_team_key(f.home)]
    away = stats[_team_key(f.away)]

    home.p += 1
    away.p += 1
    home.gf += hs
    home.ga += as_
    away.gf += as_
    away.ga += hs

    if hs > as_:
        home.w += 1
        away.l += 1
        home.pts += 3
    elif hs < as_:
        away.w += 1
        home.l += 1
        away.pts += 3
    else:
        home.d += 1
        away.d += 1
        home.pts += 1
        away.pts += 1


def _sorted_standings(stats: Dict[str, TeamStats]) -> List[TeamStats]:
    def key(s: TeamStats):
        gd = s.gf - s.ga
        return (-s.pts, -gd, -s.gf, s.team.lower())
    return sorted(stats.values(), key=key)


def _gd_class(gd: int) -> str:
    if gd > 0:
        return "gd gd-pos"
    if gd < 0:
        return "gd gd-neg"
    return "gd gd-zero"


def _bubble(letter: str, color: str, title: str) -> str:
    # Match legacy inline bubble styling in the old attachment HTML fileciteturn6file1L109-L118
    return (
        "<span "
        f"title='{title}' "
        "style='display:inline-flex;align-items:center;justify-content:center;"
        "width:24px;height:24px;border-radius:999px;"
        f"border:2px solid {color};"
        "font-size:11px;font-weight:700;margin-right:4px;"
        f"background:#020617;color:{color};'>"
        f"{letter}</span>"
    )


def _format_score(hs: Optional[int], as_: Optional[int]) -> str:
    if hs is None or as_ is None:
        return "—"
    return f"{hs}–{as_}"


def _build_form_sequence(
    team: str,
    fixtures_by_week_num: Dict[int, List[Fixture]],
    week_dates: Dict[int, date],
    week_nums_sorted: List[int],
) -> str:
    bubbles: List[str] = []
    tkey = _team_key(team)

    for wn in week_nums_sorted:
        played = None  # type: Optional[Fixture]
        for f in fixtures_by_week_num.get(wn, []):
            if _team_key(f.home) == tkey or _team_key(f.away) == tkey:
                # only count finished, non-void, non-canceled with scores as "played"
                if f.is_finished and (not f.is_voided) and (not f.is_canceled) and f.home_score is not None and f.away_score is not None:
                    played = f
                    break

        d = week_dates.get(wn)
        when = _format_dd_mmm_yyyy(d)

        if not played:
            title = f"No match played\nWeek {wn} — {when}"
            bubbles.append(_bubble("N", "#9ca3af", title))
            continue

        # determine W/D/L for this team
        is_home = (_team_key(played.home) == tkey)
        hs = played.home_score or 0
        as_ = played.away_score or 0

        if hs == as_:
            res = ("D", "#eab308", "Draw")
        else:
            team_won = (hs > as_) if is_home else (as_ > hs)
            res = ("W", "#22c55e", "Win") if team_won else ("L", "#ef4444", "Loss")

        opp = played.away if is_home else played.home
        score = _format_score(hs if is_home else as_, as_ if is_home else hs)
        # Title matches legacy format (multi-line)
        title = f"{res[2]}\nvs {opp}\nScore: {score}\nWeek {wn} — {when}"
        bubbles.append(_bubble(res[0], res[1], title))

    return "".join(bubbles)


def _find_next_fixture(team: str, fixtures: List[Fixture]) -> Tuple[str, str]:
    """
    Returns (main_line, meta_line) similar to:
      <span class='next-main'>vs ...</span>
      <span class='next-meta'>DD Mon YYYY • HH:MM • Location • Pitch</span>
    """
    tkey = _team_key(team)
    today = date.today()

    candidates: List[Fixture] = []
    for f in fixtures:
        if f.is_voided or f.is_canceled:
            continue
        if not f.is_scheduled:
            continue
        if f.date < today:
            continue
        if _team_key(f.home) == tkey or _team_key(f.away) == tkey:
            candidates.append(f)

    if not candidates:
        return ("No upcoming fixture", "—")

    candidates.sort(key=lambda x: (x.date, x.start_at or "99:99"))
    nxt = candidates[0]
    is_home = (_team_key(nxt.home) == tkey)
    opp = nxt.away if is_home else nxt.home

    main = f"vs {opp}"
    meta_parts: List[str] = []
    meta_parts.append(_format_dd_mmm_yyyy(nxt.date))
    if nxt.start_at:
        meta_parts.append(nxt.start_at)
    # The fixtures payload usually includes location_name / pitch_name; if missing, keep blank.
    # We do not have those in Fixture dataclass now; leave out to avoid errors.
    meta = " • ".join([p for p in meta_parts if p])

    return (main, meta if meta else "—")


# -----------------------------
# HTML builders (match legacy attachment)
# -----------------------------

_HTML_HEAD = """<!DOCTYPE html>
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
"""

_HTML_FOOT = """
</body>
</html>
"""


def _build_division_panel_html(label: str, panel_id: str, active: bool, standings: List[TeamStats], team_meta: Dict[str, TeamMeta],
                              fixtures: List[Fixture], week_nums_sorted: List[int], fixtures_by_week_num: Dict[int, List[Fixture]],
                              week_dates: Dict[int, date]) -> str:
    display = "block" if active else "none"

    rows_html: List[str] = []
    for idx, s in enumerate(standings, start=1):
        gd = s.gf - s.ga
        gd_cls = _gd_class(gd)
        gd_txt = f"{gd:+d}" if gd != 0 else "0"
        tkey = _team_key(s.team)
        logo = (team_meta.get(tkey).logo if team_meta.get(tkey) else "") or s.logo or ""

        form_html = _build_form_sequence(
            s.team,
            fixtures_by_week_num=fixtures_by_week_num,
            week_dates=week_dates,
            week_nums_sorted=week_nums_sorted,
        )

        next_main, next_meta = _find_next_fixture(s.team, fixtures)

        row = (
            "<tr>"
            f"<td class='pos'>{idx}</td>"
            "<td class='team'>"
            "<div class='team-cell'>"
            f"<img class='team-logo' src='{logo}' alt='{s.team} logo' />"
            f"<span>{s.team}</span>"
            "</div>"
            "</td>"
            f"<td>{s.p}</td>"
            f"<td>{s.w}</td>"
            f"<td>{s.d}</td>"
            f"<td>{s.l}</td>"
            f"<td>{s.gf} / {s.ga}</td>"
            f"<td class='{gd_cls}'>{gd_txt}</td>"
            f"<td class='pts'>{s.pts}</td>"
            f"<td class='form-cell'>{form_html}</td>"
            "<td class='next-cell'>"
            f"<span class='next-main'>{next_main}</span>"
            f"<span class='next-meta'>{next_meta}</span>"
            "</td>"
            "</tr>"
        )
        rows_html.append(row)

    return (
        f"<div id='{panel_id}' class='division-panel' style='display:{display};'>"
        f"<h2>YFL Dubai — {label}</h2>"
        "<table>"
        "<thead><tr>"
        "<th>#</th><th>Club</th><th>P</th><th>W</th><th>D</th><th>L</th>"
        "<th>GF / GA</th><th>GD</th><th>PTS</th><th>Form</th><th>Next Fixture</th>"
        "</tr></thead>"
        "<tbody>"
        + "".join(rows_html) +
        "</tbody></table></div>"
    )


def _build_tabs_html(active_panel_id: str) -> str:
    btns: List[str] = []
    for _league_id, label, panel_id in TOURNAMENTS:
        active = (" active" if panel_id == active_panel_id else "")
        btns.append(
            f"<button class='tab-btn{active}' onclick=\"showDivision('{panel_id}', this)\">{label}</button>"
        )
    return "<div class='tab-bar'>" + "".join(btns) + "</div>"


# -----------------------------
# Public entry point (used by main.py)
# -----------------------------

async def scrape_all_divisions(*_args) -> Tuple[str, str, str]:
    """
    main.py calls: await scrape_all_divisions(TOURNAMENTS, LOGIN_URL) in some versions.
    Accept and ignore positional args so we do not crash on signature mismatch.
    """
    _require_env()

    headers = _auth_headers()

    # Use division 3 as default active tab (matches old attachment) fileciteturn6file1L108-L109
    active_panel_id = "panel-div3"

    panels: List[str] = []
    inline_div3_html: str = ""

    async with aiohttp.ClientSession(headers=headers) as session:
        for league_id, label, panel_id in TOURNAMENTS:
            fixtures = await fetch_all_fixtures(session, league_id)
            if not fixtures:
                raise RuntimeError(f"No fixtures fetched for {label}")

            # Build week list based on finished fixtures only (legacy behavior shows weeks up to last played)
            finished_valid = [
                f for f in fixtures
                if f.is_finished and (not f.is_voided) and (not f.is_canceled) and f.home_score is not None and f.away_score is not None
            ]
            # If no finished games yet, fall back to whatever we have (so file is not blank)
            source_for_weeks = finished_valid if finished_valid else fixtures

            week_dates: Dict[int, date] = {}
            by_week_num: Dict[int, List[Fixture]] = {}
            for f in source_for_weeks:
                by_week_num.setdefault(f.week_num, []).append(f)
                if f.week_num not in week_dates:
                    week_dates[f.week_num] = f.date
                else:
                    week_dates[f.week_num] = min(week_dates[f.week_num], f.date)

            week_nums_sorted = sorted([wn for wn in by_week_num.keys() if wn > 0])

            # Compute standings from ALL finished valid fixtures (ignoring void/canceled) across season-to-date
            stats: Dict[str, TeamStats] = {}
            team_meta: Dict[str, TeamMeta] = {}

            for f in fixtures:
                # Ensure meta exists for teams, even if they have 0 played yet
                _ensure_team(stats, team_meta, f.home, f.home_logo)
                _ensure_team(stats, team_meta, f.away, f.away_logo)
                _accumulate_from_fixture(stats, team_meta, f)

            standings = _sorted_standings(stats)

            panel_html = _build_division_panel_html(
                label=label,
                panel_id=panel_id,
                active=(panel_id == active_panel_id),
                standings=standings,
                team_meta=team_meta,
                fixtures=fixtures,
                week_nums_sorted=week_nums_sorted,
                fixtures_by_week_num=by_week_num,
                week_dates=week_dates,
            )
            panels.append(panel_html)

            if panel_id == "panel-div3":
                # Inline body later (you said we will handle later), but main.py expects a string.
                # Provide the Division 3 table only.
                inline_div3_html = panel_html

    # Attachment filename must be stable (no date) per your requirement.
    output_filename = "yfl_u11_form_guide.html"

    full_html = _HTML_HEAD + _build_tabs_html(active_panel_id) + "".join(panels) + _HTML_FOOT
    return full_html, inline_div3_html, output_filename
