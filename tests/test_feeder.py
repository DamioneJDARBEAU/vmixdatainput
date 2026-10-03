import datetime as dt
import http.server
import json
import threading
import time
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
            self.assertEqual(g["sources"][0]["type"], "supabase_slot")
        cols = {k: g["sources"][0]["draw_column"] for k, g in cfg["games"].items()}
        self.assertEqual(cols["cash4_morning"], "cash4_draw_no")
        self.assertEqual(cols["playway_night"], "play_way_draw_no")
        self.assertEqual(cols["pick3_midday"], "pick3_draw_no")
        self.assertEqual(cols["lotto"], "draw_no")
        self.assertEqual(cfg["games"]["playway_afternoon"]["sources"][0]["period"],
                         "mid_afternoon")
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


PERIODS = ["mid_morning", "midday", "mid_afternoon", "evening"]


def fake_postgrest(rows):
    """Handler that applies select / not.is.null / lte / order desc / limit."""
    def handler(path, q, headers):
        data = list(rows)
        limit = None
        order = None
        for k, val in q:
            if k == "limit":
                limit = int(val)
            elif k == "order":
                order = val.split(".")[0]
            elif k == "select":
                continue
            elif val == "not.is.null":
                data = [r for r in data if r.get(k) is not None]
            elif val.startswith("lte."):
                data = [r for r in data if str(r[k]) <= val[4:]]
        if order:
            data.sort(key=lambda r: r[order], reverse=True)
        return 200, json.dumps(data[:limit])
    return handler


class SupabaseSlotTests(unittest.TestCase):
    def setUp(self):
        self.rows = []
        self.srv = FakeServer(fake_postgrest(self.rows))
        self.settings = {"supabase": {"url": self.srv.url, "key": "K"}}

    def tearDown(self):
        self.srv.close()

    def daily(self, d, period, pw):
        self.rows.append({"draw_date": d, "period": period, "play_way_draw_no": pw})

    def next_for(self, period, today):
        src = {"type": "supabase_slot", "table": "daily_results",
               "draw_column": "play_way_draw_no", "period_column": "period",
               "period": period, "periods": PERIODS}
        r = v.source_supabase_slot(src, {}, self.settings, dt.date(*today))
        return None if r is None else r["next"]

    def test_counts_slots_through_the_day(self):
        # yesterday fully published: 1001..1004
        for i, per in enumerate(PERIODS):
            self.daily("2026-10-02", per, 1001 + i)
        t = (2026, 10, 3)
        self.assertEqual(self.next_for("mid_morning", t), 1005)
        self.assertEqual(self.next_for("midday", t), 1006)
        self.assertEqual(self.next_for("mid_afternoon", t), 1007)
        self.assertEqual(self.next_for("evening", t), 1008)
        # morning result published today
        self.daily("2026-10-03", "mid_morning", 1005)
        self.assertEqual(self.next_for("mid_morning", t), 1005)  # its own number
        self.assertEqual(self.next_for("evening", t), 1008)

    def test_yesterday_not_fully_entered_and_gap_days(self):
        self.daily("2026-10-02", "mid_morning", 2001)
        self.daily("2026-10-02", "midday", 2002)
        # mid_afternoon / evening of yesterday still to be entered
        self.assertEqual(self.next_for("mid_morning", (2026, 10, 3)), 2005)
        # several days later with no draws in between (e.g. holiday)
        self.rows[:] = [{"draw_date": "2026-10-02", "period": "evening",
                         "play_way_draw_no": 3000}]
        self.assertEqual(self.next_for("midday", (2026, 10, 5)), 3002)

    def test_future_rows_ignored_and_passed_period(self):
        self.daily("2026-10-03", "midday", 4002)
        self.daily("2026-10-04", "mid_morning", 9999)  # pre-entered, future
        self.assertEqual(self.next_for("evening", (2026, 10, 3)), 4004)
        self.assertIsNone(self.next_for("mid_morning", (2026, 10, 3)))

    def test_lotto_no_periods(self):
        self.rows[:] = [{"draw_date": "2026-09-30", "draw_no": 2100},
                        {"draw_date": "2026-09-26", "draw_no": 2099}]
        src = {"type": "supabase_slot", "table": "lotto_results", "draw_column": "draw_no"}
        today = dt.date(2026, 10, 3)
        self.assertEqual(v.source_supabase_slot(src, {}, self.settings, today), {"next": 2101})
        self.rows.append({"draw_date": "2026-10-03", "draw_no": 2101})
        self.assertEqual(v.source_supabase_slot(src, {}, self.settings, today), {"next": 2101})
        # through next_draw_id: no extra +1 on top of the slot result
        game = {"sources": [src], "increment": 1}
        self.assertEqual(v.next_draw_id("lotto", game, self.settings, {}, {}, today),
                         (2101, "supabase_slot"))

    def test_empty_table(self):
        self.assertIsNone(self.next_for("midday", (2026, 10, 3)))


class DrawTextTests(unittest.TestCase):
    def test_draw_id_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {"settings": {"output_folder": os.path.join(d, "out"),
                                "state_file": os.path.join(d, "state.json"),
                                "overrides_file": os.path.join(d, "ov.json"),
                                "draw_format": "Draw ID:  {0}"},
                   "games": {"lotto": {"name": "Lotto", "sources": []}}}
            with open(os.path.join(d, "ov.json"), "w") as f:
                json.dump({"lotto": {"date": dt.date.today().isoformat(),
                                     "next_draw": 7930}}, f)
            res = v.run_once(cfg)
            self.assertEqual(res["lotto"]["DRAW_ID"], "Draw ID:  7930")
            self.assertEqual(res["lotto"]["draw"], 7930)
            with open(os.path.join(d, "out", "lotto.csv"), encoding="utf-8-sig") as f:
                self.assertIn(",Draw ID:  7930", f.read())

    def test_shipped_config_format(self):
        cfg = v.load_json(os.path.join(os.path.dirname(__file__), "..", "config.json"))
        self.assertEqual(cfg["settings"]["draw_format"].format(7930), "Draw ID:  7930")


class RecordingTests(unittest.TestCase):
    RC = {"folder": "{date}/{game}", "filename": "{game}_{draw}_{period}_{date}{ext}"}

    def test_names(self):
        day = dt.date(2026, 10, 3)
        g = {"game_label": "Pick 3", "period_label": "Night"}
        self.assertEqual(v.recording_target(self.RC, g, 7930, day, ".mp4"),
                         ("2026-10-03/Pick_3", "Pick_3_7930_Night_2026-10-03.mp4"))
        lotto = {"game_label": "Lotto", "period_label": ""}
        self.assertEqual(v.recording_target(self.RC, lotto, 2101, day, ".mp4")[1],
                         "Lotto_2101_2026-10-03.mp4")
        self.assertEqual(v.recording_target(self.RC, g, None, day, ".mp4")[1],
                         "Pick_3_NoDraw_Night_2026-10-03.mp4")

    def test_shipped_config_labels(self):
        cfg = v.load_json(os.path.join(os.path.dirname(__file__), "..", "config.json"))
        rc = cfg["settings"]["recordings"]
        folder, name = v.recording_target(rc, cfg["games"]["cash4_afternoon"], 7930,
                                          dt.date(2026, 10, 3), ".mp4")
        self.assertEqual(folder, r"C:\Users\user\Documents\vmixstorage\2026-10-03\Cash_4")
        self.assertEqual(name, "Cash_4_7930_Afternoon_2026-10-03.mp4")

    def test_filer_moves_recording_after_stop(self):
        state = {"preset": "C:\\Shows\\Pick 3 Night.vmix", "rec": "True"}

        def handler(path, q, h):
            return 200, ("<vmix><preset>%s</preset><recording>%s</recording></vmix>"
                         % (state["preset"], state["rec"]))
        srv = FakeServer(handler)
        try:
            with tempfile.TemporaryDirectory() as d:
                watch = os.path.join(d, "incoming")
                os.makedirs(watch)
                rc = {"enabled": True, "watch_folder": watch, "settle_seconds": 0,
                      "folder": os.path.join(d, "store", "{date}", "{game}"),
                      "filename": "{game}_{draw}_{period}_{date}{ext}"}
                games = {
                    "pick3_night": {"game_label": "Pick 3", "period_label": "Night",
                                    "preset_match": ["Pick 3 Night", "Daily 3 Night"]},
                    "cash4_morning": {"game_label": "Cash 4", "period_label": "Morning",
                                      "preset_match": ["Cash 4 Morning"]}}
                cfg = {"settings": {"vmix_api": {"url": srv.url + "/api/"},
                                    "recordings": rc}, "games": games}
                results = {"pick3_night": {"draw": 7930}, "cash4_morning": {"draw": 100}}
                filer = v.RecordingFiler()
                filer.tick(cfg, results)                 # recording starts
                f = os.path.join(watch, "capture 1.mp4")
                with open(f, "wb") as fh:
                    fh.write(b"video")
                filer.tick(cfg, results)                 # still recording: untouched
                self.assertTrue(os.path.exists(f))
                old = time.time() - 30
                os.utime(f, (old, old))
                filer.active["started"] = old - 5
                state["rec"] = "False"
                state["preset"] = "C:\\Shows\\Cash 4 Morning.vmix"  # next show loaded
                filer.tick(cfg, results)
                day = dt.date.today().isoformat()
                dest = os.path.join(d, "store", day, "Pick_3",
                                    "Pick_3_7930_Night_%s.mp4" % day)
                self.assertTrue(os.path.exists(dest), os.listdir(d))
                self.assertFalse(os.path.exists(f))
                # a second take of the same draw is not overwritten
                state["rec"] = "True"
                state["preset"] = "C:\\Shows\\Pick 3 Night.vmix"
                filer.tick(cfg, results)
                with open(f, "wb") as fh:
                    fh.write(b"take2")
                os.utime(f, (time.time() - 30,) * 2)
                filer.active["started"] = time.time() - 40
                state["rec"] = "False"
                filer.tick(cfg, results)
                self.assertTrue(os.path.exists(dest[:-4] + "_2.mp4"))
        finally:
            srv.close()

    def test_filer_does_nothing_without_vmix(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "x.mp4")
            open(f, "wb").write(b"1")
            cfg = {"settings": {"vmix_api": {"url": "http://127.0.0.1:9/api/"},
                                "recordings": {"enabled": True, "watch_folder": d,
                                               "settle_seconds": 0}},
                   "games": {}}
            v.RecordingFiler().tick(cfg, {})
            self.assertTrue(os.path.exists(f))


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
                "pick3_night": {"game": {"preset_match": ["Pick 3 Night", "Daily 3 Night"]},
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

    def test_preset_names_from_config(self):
        cfg = v.load_json(os.path.join(os.path.dirname(__file__), "..", "config.json"))

        def which(filename):
            hits = [k for k, g in cfg["games"].items()
                    if v.preset_matches(g["preset_match"], filename)]
            self.assertLessEqual(len(hits), 1, hits)  # never ambiguous
            return hits[0] if hits else None

        self.assertEqual(which("Daily 3 Morning.vmix"), "pick3_morning")
        self.assertEqual(which("Pick 3 Midday.vmix"), "pick3_midday")
        self.assertEqual(which("Daily Pick-3 Night.vmix"), "pick3_night")
        self.assertEqual(which("Cash 4 Afternoon.vmix"), "cash4_afternoon")
        self.assertEqual(which("Daily Cash 4 Night.vmix"), "cash4_night")
        self.assertEqual(which("Play Way Morning.vmix"), "playway_morning")
        self.assertEqual(which("Lotto.vmix"), "lotto")

    def test_wrong_field_name_does_not_crash(self):
        calls = self.run_push(set())
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
