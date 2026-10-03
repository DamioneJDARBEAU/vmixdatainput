import datetime as dt
import http.server
import json
import threading
import urllib.parse
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
            self.assertEqual(g["sources"][0]["type"], "supabase")
        self.assertEqual(cfg["settings"]["vmix_api"]["date_field"], "Date.Text")
        self.assertEqual(cfg["settings"]["vmix_api"]["draw_field"], "DRAW_ID.Text")


class RunTwiceTests(unittest.TestCase):
    def test_second_run_reads_its_own_state_and_bom_config(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {"settings": {"output_folder": os.path.join(d, "out"),
                                "state_file": os.path.join(d, "state.json"),
                                "overrides_file": os.path.join(d, "ov.json")},
                   "games": {"lotto": {"name": "Lotto", "sources": []}}}
            today = dt.date.today().isoformat()
            with open(os.path.join(d, "ov.json"), "w", encoding="utf-8-sig") as f:
                json.dump({"lotto": {"date": today, "next_draw": 77}}, f)
            v.run_once(cfg)
            v.run_once(cfg)  # used to fail: state.json had a BOM
            with open(os.path.join(d, "out", "lotto.csv"), encoding="utf-8-sig") as f:
                self.assertTrue(f.read().splitlines()[1].endswith(",77"))
            self.assertEqual(v.load_json(os.path.join(d, "state.json"))["lotto"]["next_draw"], 77)


class FakeServer:
    """Tiny local HTTP server; handler(path, query, headers) -> (code, body)."""

    def __init__(self, handler):
        outer = self
        self.requests = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                u = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qsl(u.query)
                outer.requests.append((u.path, q, dict(self.headers)))
                code, body = handler(u.path, q, self.headers)
                self.send_response(code)
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *a):
                pass

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_port
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class SupabaseTests(unittest.TestCase):
    def test_reads_latest_draw(self):
        def handler(path, q, headers):
            self.assertEqual(path, "/rest/v1/results")
            self.assertEqual(headers["apikey"], "KEY")
            self.assertEqual(headers["Authorization"], "Bearer KEY")
            qd = dict(q)
            self.assertEqual(qd["select"], "draw_number")
            self.assertEqual(qd["order"], "draw_number.desc.nullslast")
            self.assertEqual(qd["limit"], "1")
            self.assertEqual(qd["game"], "ilike.Play Way")
            self.assertEqual(qd["period"], "ilike.Night")
            return 200, json.dumps([{"draw_number": 3512}])

        srv = FakeServer(handler)
        try:
            settings = {"supabase": {"url": srv.url + "/", "key": "KEY",
                                     "table": "results", "draw_column": "draw_number"}}
            src = {"type": "supabase", "filters": {"game": "Play Way", "period": "Night"}}
            self.assertEqual(v.source_supabase(src, {}, settings), 3512)
            nxt = v.next_draw_id("playway_night", {"sources": [src]}, settings,
                                 {}, {}, dt.date(2026, 10, 3))
            self.assertEqual(nxt, (3513, "supabase"))
        finally:
            srv.close()

    def test_text_draw_and_empty(self):
        rows = {"n": [{"draw": "PW-0042"}]}
        srv = FakeServer(lambda p, q, h: (200, json.dumps(rows["n"])))
        try:
            settings = {"supabase": {"url": srv.url, "key": "K", "draw_column": "draw"}}
            self.assertEqual(v.source_supabase({"type": "supabase"}, {}, settings), 42)
            rows["n"] = []
            self.assertIsNone(v.source_supabase({"type": "supabase"}, {}, settings))
        finally:
            srv.close()

    def test_http_error_is_readable(self):
        srv = FakeServer(lambda p, q, h: (401, '{"message":"Invalid API key"}'))
        try:
            settings = {"supabase": {"url": srv.url, "key": "bad"}}
            with self.assertRaisesRegex(RuntimeError, "401.*Invalid API key"):
                v.source_supabase({"type": "supabase"}, {}, settings)
        finally:
            srv.close()

    def test_missing_key(self):
        with tempfile.TemporaryDirectory() as d:
            settings = {"supabase": {"url": "https://x.supabase.co",
                                     "key_file": os.path.join(d, "none.txt")}}
            old = os.environ.pop("SUPABASE_KEY", None)
            try:
                with self.assertRaisesRegex(ValueError, "key not set"):
                    v.supabase_settings(settings)
            finally:
                if old is not None:
                    os.environ["SUPABASE_KEY"] = old


class VmixPushTests(unittest.TestCase):
    XML = "<vmix><preset>C:\\Shows\\Play Way Night.vmix</preset></vmix>"

    def run_push(self, known_fields):
        def handler(path, q, headers):
            qd = dict(q)
            if not qd:
                return 200, self.XML
            if qd.get("SelectedName") in known_fields:
                return 200, "Function completed successfully."
            return 500, "Error"
        srv = FakeServer(handler)
        try:
            settings = {"vmix_api": {"enabled": True, "url": srv.url + "/api/",
                                     "title_input": "LottoTitle",
                                     "date_field": "Date.Text",
                                     "draw_field": "DRAW_ID.Text"}}
            results = {
                "daily3_night": {"game": {"preset_match": "Daily 3 Night"},
                                 "Date": "x", "DRAW_ID": "1"},
                "playway_night": {"game": {"preset_match": "Play Way Night"},
                                  "Date": "Sat. 3rd Oct. 2026", "DRAW_ID": "3513"},
            }
            v.vmix_push(settings, results)  # must never raise
            return [dict(q) for _, q, _ in srv.requests if q]
        finally:
            srv.close()

    def test_sets_both_fields_on_matching_preset(self):
        calls = self.run_push({"Date.Text", "DRAW_ID.Text"})
        self.assertEqual(
            [(c["SelectedName"], c["Value"], c["Input"]) for c in calls],
            [("Date.Text", "Sat. 3rd Oct. 2026", "LottoTitle"),
             ("DRAW_ID.Text", "3513", "LottoTitle")])

    def test_wrong_field_name_does_not_crash(self):
        calls = self.run_push(set())
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
