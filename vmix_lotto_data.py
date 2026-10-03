#!/usr/bin/env python3
"""
vMix lottery title data feeder.

For every game/time-period listed in config.json this script produces:
  * DateText  - today's date, e.g. "Mon. 9th Sept. 2026"
  * DrawID    - the NEXT draw number (last published draw number + 1)

The results are written to one small CSV file per game (for vMix Data
Sources) and, optionally, pushed straight into the title that is loaded in
vMix through the vMix Web API.

Draw numbers are looked up from a list of sources, tried in order, per game:
  * "web"      - scrape a web page (URL + regex patterns live in config.json)
  * "json"     - read a JSON API/file and follow a path to the draw number
  * "sqlite"   - query a SQLite database (e.g. the email blast database)
  * "odbc"     - query any ODBC database (SQL Server, MySQL, Access...)
                 (needs: pip install pyodbc)
  * "csv"      - read the highest number from a column of a CSV export
Manual overrides (overrides.json) always win for the day they are dated.

Only the Python 3.8+ standard library is required.

Usage:
  python vmix_lotto_data.py                  run once
  python vmix_lotto_data.py --loop 300       run every 300 seconds
  python vmix_lotto_data.py --probe          show draw-number candidates
                                             found on the configured web page
  python vmix_lotto_data.py --config other.json
"""

import argparse
import csv
import datetime as dt
import html
import io
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_DAY_NAMES = ["Mon.", "Tue.", "Wed.", "Thu.", "Fri.", "Sat.", "Sun."]
DEFAULT_MONTH_NAMES = ["Jan.", "Feb.", "Mar.", "Apr.", "May", "June",
                       "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."]


# --------------------------------------------------------------------------
# Date text
# --------------------------------------------------------------------------

def ordinal(n):
    """1 -> 1st, 2 -> 2nd, 3 -> 3rd, 11 -> 11th, 22 -> 22nd ..."""
    if 11 <= n % 100 <= 13:
        return "%dth" % n
    return "%d%s" % (n, {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def format_date(day, date_cfg=None):
    """Return e.g. 'Mon. 9th Sept. 2026'. Pattern tokens: {day} {date} {month} {year}."""
    date_cfg = date_cfg or {}
    days = date_cfg.get("day_names", DEFAULT_DAY_NAMES)
    months = date_cfg.get("month_names", DEFAULT_MONTH_NAMES)
    pattern = date_cfg.get("pattern", "{day} {date} {month} {year}")
    return pattern.format(day=days[day.weekday()],
                          date=ordinal(day.day),
                          month=months[day.month - 1],
                          year=day.year)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def log(msg):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("[%s] %s" % (stamp, msg), flush=True)


def resolve(path):
    return path if os.path.isabs(path) else os.path.join(HERE, path)


def load_json(path, default=None):
    try:
        with open(resolve(path), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_atomic(path, text):
    """Write via a temp file so vMix never reads a half-written file."""
    path = resolve(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        f.write(text)
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # vMix may be reading the file right now
            time.sleep(0.5 * (attempt + 1))
    raise PermissionError("Could not replace %s (file locked)" % path)


_page_cache = {}


def http_get(url, timeout=20):
    if url in _page_cache:
        cached = _page_cache[url]
        if isinstance(cached, Exception):  # already failed this run
            raise cached
        return cached
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (vMix lotto data feeder)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            charset = r.headers.get_content_charset() or "utf-8"
            body = r.read().decode(charset, errors="replace")
    except Exception as e:
        _page_cache[url] = e
        raise
    _page_cache[url] = body
    return body


def html_to_text(page):
    page = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    page = html.unescape(page)
    return re.sub(r"\s+", " ", page)


# --------------------------------------------------------------------------
# Draw-number sources. Each returns the LAST published draw number or None.
# --------------------------------------------------------------------------

DEFAULT_DRAW_REGEX = r"Draw\s*(?:No\.?|Number|#|ID)?\s*[:#]?\s*(\d{3,})"


def source_web(src, game, settings):
    url = src.get("url") or settings.get("website_url")
    page = http_get(url)
    text = page if src.get("raw_html") else html_to_text(page)
    draw_re = re.compile(src.get("draw_regex", DEFAULT_DRAW_REGEX), re.I)
    label = src.get("label_regex")
    window = int(src.get("window", 400))

    found = []
    if label:
        # Look for the draw number in the text just after each game label.
        for m in re.finditer(label, text, re.I):
            chunk = text[m.end():m.end() + window]
            d = draw_re.search(chunk)
            if d:
                found.append(int(d.group(1)))
    else:
        found = [int(d.group(1)) for d in draw_re.finditer(text)]
    if not found:
        return None
    return max(found)


def source_json(src, game, settings):
    location = src["url"]
    if re.match(r"https?://", location):
        data = json.loads(http_get(location))
    else:
        data = load_json(location)
    # path like "results.daily3.morning.draw" or "games.0.draw"
    for part in src["path"].split("."):
        data = data[int(part)] if isinstance(data, list) else data[part]
    return int(data)


def source_sqlite(src, game, settings):
    con = sqlite3.connect(resolve(src["database"]))
    try:
        row = con.execute(src["query"], src.get("params", [])).fetchone()
    finally:
        con.close()
    return int(row[0]) if row and row[0] is not None else None


def source_odbc(src, game, settings):
    import pyodbc  # optional dependency: pip install pyodbc
    con = pyodbc.connect(src["connection_string"], timeout=15)
    try:
        cur = con.cursor()
        cur.execute(src["query"], *src.get("params", []))
        row = cur.fetchone()
    finally:
        con.close()
    return int(row[0]) if row and row[0] is not None else None


def source_csv(src, game, settings):
    with open(resolve(src["file"]), "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    flt = src.get("filter", {})  # e.g. {"Game": "Daily 3", "Period": "Morning"}
    nums = []
    for row in rows:
        if all(str(row.get(k, "")).strip().lower() == str(v).lower()
               for k, v in flt.items()):
            m = re.search(r"\d+", row.get(src["column"], "") or "")
            if m:
                nums.append(int(m.group()))
    return max(nums) if nums else None


SOURCES = {
    "web": source_web,
    "json": source_json,
    "sqlite": source_sqlite,
    "odbc": source_odbc,
    "csv": source_csv,
}


# --------------------------------------------------------------------------
# Main logic
# --------------------------------------------------------------------------

def next_draw_id(key, game, settings, state, overrides, today):
    """Return (next_draw_id, where_it_came_from)."""
    ov = overrides.get(key)
    if isinstance(ov, dict) and ov.get("date") == today.isoformat():
        return int(ov["next_draw"]), "override"

    increment = int(game.get("increment", 1))
    last = None
    for src in game.get("sources", []):
        kind = src.get("type")
        try:
            last = SOURCES[kind](src, game, settings)
        except Exception as e:  # keep going with the next source
            log("  %s: %s source failed: %s" % (key, kind, e))
            continue
        if last is not None:
            nxt = last + increment
            prev = state.get(key, {}).get("next_draw")
            if prev and nxt < prev:
                log("  %s: %s gave %d, lower than previous %d - ignored"
                    % (key, kind, nxt, prev))
                continue
            return nxt, kind
        log("  %s: %s source found no draw number" % (key, kind))

    prev = state.get(key, {}).get("next_draw")
    if prev:
        return prev, "cached"
    return None, "none"


def vmix_push(settings, results):
    """Push values into the title of whichever preset is loaded in vMix."""
    vm = settings.get("vmix_api") or {}
    if not vm.get("enabled"):
        return
    base = vm.get("url", "http://127.0.0.1:8088/api/").rstrip("/") + "/"
    try:
        xml_text = http_get_nocache(base)
    except Exception as e:
        log("vMix API not reachable (%s) - skipped push" % e)
        return
    root = ET.fromstring(xml_text)
    preset = os.path.basename(root.findtext("preset") or "").lower()
    if not preset:
        log("vMix has no saved preset loaded - skipped push")
        return

    for key, res in results.items():
        match = (res["game"].get("preset_match") or "").lower()
        if not match or match not in preset:
            continue
        title = res["game"].get("title_input") or vm.get("title_input")
        fields = {vm.get("date_field", "DateText.Text"): res["DateText"],
                  vm.get("draw_field", "DrawID.Text"): res["DrawID"]}
        for field, value in fields.items():
            if value == "":
                continue
            q = urllib.parse.urlencode({"Function": "SetText", "Input": title,
                                        "SelectedName": field, "Value": value})
            http_get_nocache(base + "?" + q)
        log("vMix: pushed %s into '%s' (preset %s)" % (key, title, preset))
        return
    log("vMix: no game matches loaded preset '%s'" % preset)


def http_get_nocache(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read().decode("utf-8", errors="replace")


def run_once(cfg):
    _page_cache.clear()
    settings = cfg.get("settings", {})
    games = cfg["games"]
    out_dir = settings.get("output_folder", "output")
    state_file = settings.get("state_file", "state.json")
    state = load_json(state_file, {}) or {}
    overrides = load_json(settings.get("overrides_file", "overrides.json"), {}) or {}

    today = dt.date.today()
    date_text = format_date(today, cfg.get("date_format"))
    log("Date text: %s" % date_text)

    results = {}
    for key, game in games.items():
        draw, origin = next_draw_id(key, game, settings, state, overrides, today)
        draw_text = "" if draw is None else (
            game.get("draw_format", "{0}").format(draw))
        results[key] = {"game": game, "DateText": date_text, "DrawID": draw_text}
        if draw is not None:
            state[key] = {"next_draw": draw, "source": origin,
                          "updated": dt.datetime.now().isoformat(timespec="seconds")}
        log("  %-22s next draw %-8s (%s)" % (key, draw_text or "-", origin))

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Game", "DateText", "DrawID"])
        w.writerow([game.get("name", key), date_text, draw_text])
        write_atomic(os.path.join(out_dir, key + ".csv"), buf.getvalue())

    # One combined file as well (one row per game) - handy for checking.
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Key", "Game", "DateText", "DrawID"])
    for key, res in results.items():
        w.writerow([key, res["game"].get("name", key), res["DateText"], res["DrawID"]])
    write_atomic(os.path.join(out_dir, "all_games.csv"), buf.getvalue())

    write_atomic(state_file, json.dumps(state, indent=2))
    vmix_push(settings, results)


def probe(cfg):
    """Print every draw-number-looking match on the configured web page(s)."""
    settings = cfg.get("settings", {})
    urls = {settings.get("website_url")}
    for g in cfg["games"].values():
        for s in g.get("sources", []):
            if s.get("type") == "web" and s.get("url"):
                urls.add(s["url"])
    for url in filter(None, urls):
        print("=" * 70 + "\n" + url)
        text = html_to_text(http_get(url))
        hits = list(re.finditer(DEFAULT_DRAW_REGEX, text, re.I))
        if not hits:
            print("No 'Draw ...<number>' text found. The page may be built by "
                  "JavaScript - use your browser's DevTools > Network tab to "
                  "find the JSON it loads and use a \"json\" source instead.")
        for m in hits:
            s = max(0, m.start() - 120)
            print("...%s[[%s]]%s..." % (text[s:m.start()], m.group(0),
                                        text[m.end():m.end() + 60]))
            print("-" * 70)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--loop", type=int, default=0,
                    help="repeat every N seconds (0 = run once)")
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()

    cfg = load_json(args.config)
    if cfg is None:
        sys.exit("Config file not found: %s" % resolve(args.config))

    if args.probe:
        probe(cfg)
        return
    while True:
        try:
            run_once(cfg)
        except Exception as e:
            log("ERROR: %s" % e)
            if not args.loop:
                sys.exit(1)
        if not args.loop:
            break
        time.sleep(args.loop)
        cfg = load_json(args.config) or cfg  # pick up config edits live


if __name__ == "__main__":
    main()
