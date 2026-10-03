import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import vmix_lotto_data as v  # noqa: E402


class DateTextTests(unittest.TestCase):
    def test_ordinals(self):
        cases = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 9: "9th", 11: "11th",
                 12: "12th", 13: "13th", 21: "21st", 22: "22nd", 23: "23rd", 31: "31st"}
        for n, want in cases.items():
            self.assertEqual(v.ordinal(n), want)

    def test_example_format(self):
        self.assertEqual(v.format_date(dt.date(2026, 9, 7)), "Mon. 7th Sept. 2026")
        self.assertEqual(v.format_date(dt.date(2026, 10, 3)), "Sat. 3rd Oct. 2026")
        self.assertEqual(v.format_date(dt.date(2026, 5, 12)), "Tue. 12th May 2026")


class DrawSourceTests(unittest.TestCase):
    PAGE = """<html><body>
      <div class="game"><h3>Daily 3 - Morning</h3><p>Draw # 10450</p><p>1 2 3</p></div>
      <div class="game"><h3>Daily 3 - Midday</h3><p>Draw No. 10451</p></div>
      <div class="game"><h3>Lotto</h3><span>Draw Number: 2100</span></div>
    </body></html>"""

    def setUp(self):
        v._page_cache.clear()
        v._page_cache["http://test/"] = self.PAGE

    def test_web_label(self):
        src = {"type": "web", "url": "http://test/",
               "label_regex": r"Daily\s*3\W{0,20}Midday"}
        self.assertEqual(v.source_web(src, {}, {}), 10451)
        src["label_regex"] = r"\bLotto\b"
        self.assertEqual(v.source_web(src, {}, {}), 2100)

    def test_next_draw_and_fallbacks(self):
        today = dt.date(2026, 10, 3)
        game = {"sources": [{"type": "web", "url": "http://test/",
                             "label_regex": r"Daily\s*3\W{0,20}Morning"}]}
        self.assertEqual(v.next_draw_id("d3m", game, {}, {}, {}, today), (10451, "web"))
        # override for today wins
        ov = {"d3m": {"date": "2026-10-03", "next_draw": 999}}
        self.assertEqual(v.next_draw_id("d3m", game, {}, {}, ov, today), (999, "override"))
        # failing source falls back to the cached value
        bad = {"sources": [{"type": "web", "url": "http://test/", "label_regex": "Nope"}]}
        state = {"d3m": {"next_draw": 10451}}
        self.assertEqual(v.next_draw_id("d3m", bad, {}, state, {}, today), (10451, "cached"))

    def test_sqlite_source(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "r.db")
            con = sqlite3.connect(path)
            con.execute("create table results(game, period, draw_number int)")
            con.executemany("insert into results values (?,?,?)",
                            [("Daily 3", "Night", 500), ("Daily 3", "Night", 501),
                             ("Daily 3", "Morning", 700)])
            con.commit()
            con.close()
            src = {"database": path, "params": ["Daily 3", "Night"],
                   "query": "SELECT MAX(draw_number) FROM results WHERE game=? AND period=?"}
            self.assertEqual(v.source_sqlite(src, {}, {}), 501)

    def test_shipped_config_is_valid(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "config.json")) as f:
            cfg = json.load(f)
        self.assertEqual(len(cfg["games"]), 13)
        for g in cfg["games"].values():
            for s in g["sources"]:
                self.assertIn(s["type"], v.SOURCES)


if __name__ == "__main__":
    unittest.main()
