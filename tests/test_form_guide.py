"""Offline tests for the form guide. No network, no credentials:  python -m unittest -v

The scraper's data source is the Sportstack fixtures API; these tests replace it with a fake
session so every number below can be checked by hand.
"""
import asyncio
import datetime as dt
import os
import sys
import unittest
from unittest import mock

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import email_sender  # noqa: E402
import yfl_scraper  # noqa: E402

TODAY = dt.date.today()


def day(offset):
    return (TODAY + dt.timedelta(days=offset)).isoformat()


def fx(week, home, away, hs=None, as_=None, off=0, **extra):
    f = {"week_name": f"Week {week}", "home_team_name": home, "away_team_name": away, "date": day(off),
         "home_team_score": hs, "away_team_score": as_, "has_finished": hs is not None}
    f.update(extra)
    return f


class FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status = data, status

    async def json(self):
        return self._data

    async def text(self):
        return str(self._data)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    def get(self, url):
        return FakeResponse(self.data, self.status)


def build(fixtures, status=200):
    """Run one division through the real scraper code; return its rendered table rows as text cells."""
    result = asyncio.run(yfl_scraper._scrape_division(FakeSession(fixtures, status), 90, "U11 Division 1"))
    soup = BeautifulSoup(f"<table>{result['rows_html']}</table>", "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td")
        if cells:
            rows.append({"pos": cells[0].get_text(strip=True), "team": cells[1].get_text(" ", strip=True),
                         "P": int(cells[2].text), "W": int(cells[3].text), "D": int(cells[4].text), "L": int(cells[5].text),
                         "GF/GA": cells[6].get_text(strip=True), "GD": cells[7].get_text(strip=True), "PTS": int(cells[8].text),
                         "form": [s.text for s in cells[9].find_all("span")], "next": cells[10].get_text(" ", strip=True)})
    return rows


class StandingsTests(unittest.TestCase):
    def test_ordinary_season_matches_a_hand_calculated_table(self):
        # wk1: A 3-0 B, C 1-1 D | wk2: A 2-2 C, B 1-0 D | wk3 still to play: A v D, B v C
        rows = build([fx(1, "A (D1)", "B (D1)", 3, 0, -14), fx(1, "C (D1)", "D (D1)", 1, 1, -14),
                      fx(2, "A (D1)", "C (D1)", 2, 2, -7), fx(2, "B (D1)", "D (D1)", 1, 0, -7),
                      fx(3, "A (D1)", "D (D1)", None, None, 7), fx(3, "B (D1)", "C (D1)", None, None, 7)])
        got = [(r["team"], r["P"], r["W"], r["D"], r["L"], r["GF/GA"], r["GD"], r["PTS"]) for r in rows]
        self.assertEqual(got, [("A", 2, 1, 1, 0, "5 / 2", "+3", 4), ("B", 2, 1, 0, 1, "1 / 3", "-2", 3),
                               ("C", 2, 0, 2, 0, "3 / 3", "0", 2), ("D", 2, 0, 1, 1, "1 / 2", "-1", 1)])
        self.assertEqual([r["pos"] for r in rows], ["1", "2", "3", "4"])

    def test_form_is_oldest_to_newest_and_next_fixture_is_the_earliest_scheduled(self):
        rows = {r["team"]: r for r in build([fx(1, "A", "B", 3, 0, -14), fx(2, "A", "C", 0, 1, -7), fx(3, "A", "D", None, None, 9),
                                              fx(4, "A", "B", None, None, 3)])}
        # Week 4, the last week, has nothing played yet, so it is left out of the form (by design);
        # week 3 (a future fixture in the middle) shows as "N".
        self.assertEqual(rows["A"]["form"], ["W", "L", "N"])
        self.assertIn("v B", rows["A"]["next"])          # week 4 is in 3 days, week 3 in 9: earliest wins
        self.assertIn("Week 4", rows["A"]["next"])

    def test_voided_and_cancelled_matches_never_count_and_show_V(self):
        rows = build([fx(1, "A", "B", 2, 0, -14), fx(2, "A", "C", 5, 0, -7, is_voided=True),
                      fx(2, "B", "D", None, None, -7, is_canceled=True), fx(3, "A", "B", 1, 1, -1)])
        by = {r["team"]: r for r in rows}
        self.assertEqual(set(by), {"A", "B"})            # C and D only have voided games: not in the table
        self.assertEqual((by["A"]["P"], by["A"]["PTS"], by["A"]["GF/GA"]), (2, 4, "3 / 1"))   # win + draw; the voided 5-0 is ignored
        self.assertEqual(by["A"]["form"], ["W", "V", "D"])

    def test_a_team_name_suffix_like_D1_is_removed(self):
        self.assertEqual([r["team"] for r in build([fx(1, "Dubai FC (D3)", "Sharjah (D3)", 1, 0, -7)])], ["Dubai FC", "Sharjah"])

    def test_exact_ties_are_ordered_by_name_and_positions_agree_with_the_display_order(self):
        rows = build([fx(1, "Zed", "Amy", 1, 1, -14), fx(1, "Mid", "Bob", 1, 1, -14)])
        self.assertEqual([(r["pos"], r["team"]) for r in rows], [("1", "Amy"), ("2", "Bob"), ("3", "Mid"), ("4", "Zed")])

    def test_numeric_scores_sent_as_strings_still_compare_as_numbers(self):
        rows = {r["team"]: r for r in build([fx(1, "A", "B", "10", "9", -7)])}
        self.assertEqual((rows["A"]["W"], rows["B"]["L"], rows["A"]["GF/GA"]), (1, 1, "10 / 9"))


class AwkwardDataTests(unittest.TestCase):
    def test_a_finished_match_with_no_score_is_not_invented_as_a_draw(self):
        # has_finished but no score recorded (walkover / data lag). The table can't count it, so the
        # form guide must not show a result for it either; it used to show a draw ("D").
        result = asyncio.run(yfl_scraper._scrape_division(
            FakeSession([fx(1, "A", "B", 2, 0, -14), fx(2, "A", "B", None, None, -7, has_finished=True),
                         fx(3, "C", "D", 1, 0, -1)]), 90, "U11 Division 1"))      # a later played week keeps week 2 in the form
        soup = BeautifulSoup(f"<table>{result['rows_html']}</table>", "html.parser")
        row_a = next(tr for tr in soup.find_all("tr") if tr.find_all("td")[1].get_text(strip=True) == "A")
        badges = row_a.find_all("td")[9].find_all("span")
        self.assertEqual(int(row_a.find_all("td")[2].text), 1)                      # only the scored match is counted
        self.assertEqual([b.text for b in badges], ["W", "N", "N"])                  # never "D"
        self.assertIn("no score was recorded", badges[1]["title"])

    def test_no_fixture_has_a_date_yet_does_not_crash(self):
        # start of season, dates still TBC: this used to raise a pandas TypeError and kill the whole run
        rows = build([{**fx(1, "A", "B", 1, 0), "date": None}])
        self.assertEqual([r["team"] for r in rows], ["A", "B"])

    def test_some_fixtures_undated_or_unparseable(self):
        for bad in (None, "TBC", "not-a-date"):
            rows = build([fx(1, "A", "B", 1, 0, -7), {**fx(2, "A", "B", None, None, 7), "date": bad}])
            self.assertEqual(len(rows), 2, bad)

    def test_a_team_with_two_matches_in_one_week_still_counts_both_in_the_table(self):
        rows = {r["team"]: r for r in build([fx(1, "A", "B", 1, 0, -7), fx(1, "A", "C", 0, 3, -6)])}
        self.assertEqual((rows["A"]["P"], rows["A"]["W"], rows["A"]["L"]), (2, 1, 1))

    def test_empty_or_future_only_divisions_give_an_empty_table_without_error(self):
        self.assertEqual(build([]), [])
        self.assertEqual(build([fx(1, "A", "B", None, None, 7)]), [])    # nothing played yet: no teams appear

    def test_an_api_error_stops_the_run_loudly(self):
        with self.assertRaises(RuntimeError):
            build([fx(1, "A", "B", 1, 0, -7)], status=401)

    def test_missing_week_name_or_team_name_does_not_crash(self):
        self.assertEqual(len(build([{**fx(1, "A", "B", 1, 0, -7), "week_name": None}])), 2)
        self.assertEqual(len(build([fx(1, None, "B", 1, 0, -7), fx(1, "C", "D", 2, 1, -7)])), 2)


class EmailTests(unittest.TestCase):
    def test_report_email_uses_the_smtp_credentials_and_attaches_the_report(self):
        report = os.path.join(os.path.dirname(__file__), "_report.html")
        with open(report, "w") as fh:
            fh.write("<html>full report</html>")
        self.addCleanup(os.remove, report)
        with mock.patch.dict(os.environ, {"SMTP_USER": "sender@example.invalid", "SMTP_PASS": "pw"}), \
             mock.patch("email_sender.smtplib.SMTP") as smtp:
            email_sender.send_report_email(["a@example.invalid", "b@example.invalid"], "Subject", "<p>hi</p>", report)
        server = smtp.return_value.__enter__.return_value
        smtp.assert_called_once_with("smtp.gmail.com", 587)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("sender@example.invalid", "pw")
        _from, to, message = server.sendmail.call_args[0]
        self.assertEqual(to, ["a@example.invalid", "b@example.invalid"])
        self.assertIn('filename="_report.html"', message)

    def test_missing_credentials_are_reported_before_anything_is_sent(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch("email_sender.smtplib.SMTP") as smtp:
            with self.assertRaises(RuntimeError):
                email_sender.send_report_email(["a@example.invalid"], "s", "<p>x</p>")
        smtp.assert_not_called()


class MainEndToEndTests(unittest.TestCase):
    """The weekly job's real entry point (main.py) with a fake API and a mocked mailer."""

    def test_main_builds_the_report_and_emails_it_without_any_website_credentials(self):
        import asyncio as _asyncio
        import tempfile
        import main as main_module

        class FakeClientSession(FakeSession):
            def __init__(self, headers=None):
                super().__init__([fx(1, "A (D3)", "B (D3)", 3, 0, -14), fx(2, "A (D3)", "B (D3)", None, None, 5)])
                self.headers = headers

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

        env = {"SPORTSTACK_API_TOKEN": "tok", "EMAIL_RECEIVER": "x@example.invalid, y@example.invalid",
               "SMTP_USER": "s@example.invalid", "SMTP_PASS": "pw",       # note: no YFL_USERNAME / YFL_PASSWORD
               "EMAIL_SUBJECT": "Weekly guide"}
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("yfl_scraper.aiohttp.ClientSession", FakeClientSession), \
             mock.patch("main.send_report_email") as send:
            os.chdir(tmp)
            try:
                _asyncio.run(main_module.main())
                report = open("yfl_u11_form_guide.html", encoding="utf-8").read()   # the attachment really was written
            finally:
                os.chdir(cwd)
        send.assert_called_once()
        kw = send.call_args.kwargs
        self.assertEqual(kw["receivers"], ["x@example.invalid", "y@example.invalid"])
        self.assertEqual(kw["subject"], "Weekly guide")
        self.assertTrue(kw["attachment_path"].endswith("yfl_u11_form_guide.html"))
        # the inline email body carries the Division 3 table; the attachment carries all three divisions
        self.assertIn("<table", kw["body_html"])
        self.assertIn(">A<", kw["body_html"].replace(" ", "").replace("\n", ""))
        for label in ("U11 Division 1", "U11 Division 2", "U11 Division 3"):
            self.assertIn(label, report)

    def test_main_stops_with_a_clear_message_when_the_api_token_or_receiver_is_missing(self):
        import asyncio as _asyncio
        import main as main_module
        with mock.patch.dict(os.environ, {"EMAIL_RECEIVER": "x@example.invalid"}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                _asyncio.run(main_module.main())
        self.assertIn("SPORTSTACK_API_TOKEN", str(ctx.exception))
        with mock.patch.dict(os.environ, {"SPORTSTACK_API_TOKEN": "t"}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                _asyncio.run(main_module.main())
        self.assertIn("EMAIL_RECEIVER", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
