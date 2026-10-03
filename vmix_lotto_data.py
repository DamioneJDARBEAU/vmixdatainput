#!/usr/bin/env python3
"""
vMix lottery title data feeder.

For every game/time-period listed in config.json this script produces:
  * Date      - today's date, e.g. "Mon. 9th Sept. 2026"
  * DRAW_ID   - the NEXT draw number (last published draw number + 1)

The results are written to one small CSV file per game (for vMix Data
Sources) and, optionally, pushed straight into the title that is loaded in
vMix through the vMix Web API.

Draw numbers are looked up from a list of sources, tried in order, per game:
  * "supabase_slot" - NLA results tables in Supabase (daily_results,
                   lotto_results): today's draw number for the game/period
  * "supabase" - generic: latest number in any Supabase table, plus 1
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
  python vmix_lotto_data.py --probe          show what the website and the
                                             Supabase table contain, to help
                                             set up config.json
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
import urllib.error
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
        # utf-8-sig also accepts files saved by Notepad with a BOM
        with open(resolve(path), "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_atomic(path, text, bom=False):
    """Write via a temp file so vMix never reads a half-written file."""
    path = resolve(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
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


def source_web(src, game, settings, today=None):
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


def source_json(src, game, settings, today=None):
    location = src["url"]
    if re.match(r"https?://", location):
        data = json.loads(http_get(location))
    else:
        data = load_json(location)
    # path like "results.daily3.morning.draw" or "games.0.draw"
    for part in src["path"].split("."):
        data = data[int(part)] if isinstance(data, list) else data[part]
    return int(data)


def source_sqlite(src, game, settings, today=None):
    con = sqlite3.connect(resolve(src["database"]))
    try:
        row = con.execute(src["query"], src.get("params", [])).fetchone()
    finally:
        con.close()
    return int(row[0]) if row and row[0] is not None else None


def source_odbc(src, game, settings, today=None):
    import pyodbc  # optional dependency: pip install pyodbc
    con = pyodbc.connect(src["connection_string"], timeout=15)
    try:
        cur = con.cursor()
        cur.execute(src["query"], *src.get("params", []))
        row = cur.fetchone()
    finally:
        con.close()
    return int(row[0]) if row and row[0] is not None else None


def source_csv(src, game, settings, today=None):
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


def supabase_settings(settings):
    sb = dict(settings.get("supabase") or {})
    key = sb.get("key") or os.environ.get("SUPABASE_KEY")
    if not key:
        try:
            with open(resolve(sb.get("key_file", "supabase_key.txt")), "r",
                      encoding="utf-8-sig") as f:
                key = f.read().strip()
        except FileNotFoundError:
            pass
    if not sb.get("url") or not key:
        raise ValueError("Supabase url/key not set (see settings.supabase in "
                         "config.json and supabase_key.txt)")
    sb["key"] = key
    sb["url"] = sb["url"].rstrip("/")
    return sb


def supabase_get(sb, path, params):
    url = "%s/rest/v1/%s" % (sb["url"], path)
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "apikey": sb["key"], "Authorization": "Bearer " + sb["key"],
        "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError("Supabase HTTP %s: %s" % (e.code, detail))


def source_supabase(src, game, settings, today=None):
    sb = supabase_settings(settings)
    table = src.get("table") or sb.get("table", "results")
    col = src.get("draw_column") or sb.get("draw_column", "draw_number")
    order = src.get("order_column") or sb.get("order_column") or col
    params = [("select", col), ("order", order + ".desc.nullslast"), ("limit", "1")]
    for field, value in (src.get("filters") or {}).items():
        op = "ilike" if src.get("ignore_case", True) else "eq"
        params.append((field, "%s.%s" % (op, value)))
    rows = supabase_get(sb, table, params)
    if not rows or rows[0].get(col) in (None, ""):
        return None
    m = re.search(r"\d+", str(rows[0][col]))
    return int(m.group()) if m else None


def source_supabase_slot(src, game, settings, today=None):
    """Draw number for TODAY's draw of this game/period, from a results table
    where draw numbers run in one sequence through the day's periods.

    * If today's row for this period already has a draw number, use it.
    * Otherwise take the latest known draw number and add the number of
      draw slots between it and today's slot for this period.
    Returns {"next": n} - already the final draw ID (no +1 added later).
    """
    sb = supabase_settings(settings)
    today = today or dt.date.today()
    table = src["table"]
    col = src["draw_column"]
    date_col = src.get("date_column", "draw_date")
    period_col = src.get("period_column")
    periods = src.get("periods") or []
    target = src.get("period")

    select = [date_col, col] + ([period_col] if period_col else [])
    params = [("select", ",".join(select)),
              (col, "not.is.null"),
              (date_col, "lte." + today.isoformat()),
              ("order", date_col + ".desc"),
              ("limit", str(max(8, 3 * len(periods))))]
    rows = supabase_get(sb, table, params)

    def slot(row):
        idx = periods.index(row[period_col]) if period_col else 0
        return (str(row[date_col])[:10], idx)

    found = []
    for row in rows:
        if period_col and row.get(period_col) not in periods:
            continue
        found.append((slot(row), int(row[col])))
    if not found:
        return None

    t_idx = periods.index(target) if period_col else 0
    today_s = today.isoformat()
    for (d, idx), draw in found:
        if d == today_s and idx == t_idx:
            return {"next": draw}  # today's draw number is already known

    (l_date, l_idx), l_draw = max(found)
    per_day = max(1, len(periods))
    if l_date == today_s:
        steps = t_idx - l_idx
        if steps <= 0:  # this period already passed today without a number
            return None
    else:
        # remaining slots on the latest day + today's slots up to the target
        steps = (per_day - 1 - l_idx) + t_idx + 1
    return {"next": l_draw + steps}


SOURCES = {
    "supabase_slot": source_supabase_slot,
    "supabase": source_supabase,
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
            last = SOURCES[kind](src, game, settings, today)
        except Exception as e:  # keep going with the next source
            log("  %s: %s source failed: %s" % (key, kind, e))
            continue
        if last is not None:
            nxt = last["next"] if isinstance(last, dict) else last + increment
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
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        log("vMix API returned unreadable XML (%s) - skipped push" % e)
        return
    preset = os.path.basename(root.findtext("preset") or "").lower()
    if not preset:
        log("vMix has no saved preset loaded - skipped push")
        return

    for key, res in results.items():
        match = (res["game"].get("preset_match") or "").lower()
        if not match or match not in preset:
            continue
        title = res["game"].get("title_input") or vm.get("title_input")
        fields = {vm.get("date_field", "Date.Text"): res["Date"],
                  vm.get("draw_field", "DRAW_ID.Text"): res["DRAW_ID"]}
        ok = True
        for field, value in fields.items():
            if value == "":
                continue
            q = urllib.parse.urlencode({"Function": "SetText", "Input": title,
                                        "SelectedName": field, "Value": value})
            try:
                http_get_nocache(base + "?" + q)
            except Exception as e:
                ok = False
                log("vMix: could not set '%s' on input '%s' (%s). Check that the "
                    "title input is named '%s' and has a field called '%s'."
                    % (field, title, e, title, field))
        if ok:
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
        results[key] = {"game": game, "Date": date_text, "DRAW_ID": draw_text}
        if draw is not None:
            state[key] = {"next_draw": draw, "source": origin,
                          "updated": dt.datetime.now().isoformat(timespec="seconds")}
        log("  %-22s next draw %-8s (%s)" % (key, draw_text or "-", origin))

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Game", "Date", "DRAW_ID"])
        w.writerow([game.get("name", key), date_text, draw_text])
        write_atomic(os.path.join(out_dir, key + ".csv"), buf.getvalue(), bom=True)

    # One combined file as well (one row per game) - handy for checking.
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Key", "Game", "Date", "DRAW_ID"])
    for key, res in results.items():
        w.writerow([key, res["game"].get("name", key), res["Date"], res["DRAW_ID"]])
    write_atomic(os.path.join(out_dir, "all_games.csv"), buf.getvalue(), bom=True)

    write_atomic(state_file, json.dumps(state, indent=2))
    try:
        vmix_push(settings, results)
    except Exception as e:  # the CSV files are already written
        log("vMix push failed: %s" % e)


def probe(cfg):
    """Show what the Supabase table and the web page(s) contain."""
    settings = cfg.get("settings", {})
    probe_supabase(settings, cfg.get("games"))
    urls = {settings.get("website_url")}
    for g in cfg["games"].values():
        for s in g.get("sources", []):
            if s.get("type") == "web" and s.get("url"):
                urls.add(s["url"])
    for url in filter(None, urls):
        print("=" * 70 + "\nWEBSITE: " + url)
        try:
            text = html_to_text(http_get(url))
        except Exception as e:
            print("Could not open the page: %s" % e)
            continue
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


def probe_supabase(settings, games=None):
    if not settings.get("supabase"):
        return
    print("=" * 70 + "\nSUPABASE")
    try:
        sb = supabase_settings(settings)
    except Exception as e:
        print(e)
        return
    print("Project: %s" % sb["url"])
    try:  # table list (only works if the key may read the API description)
        spec = supabase_get(sb, "", None)
        names = sorted(k.strip("/") for k in spec.get("paths", {})
                       if k.strip("/") and not k.startswith("/rpc/"))
        print("Tables/views visible to this key: %s" % (", ".join(names) or "-"))
    except Exception as e:
        print("Could not list tables (%s)" % e)

    tables = {}
    for g in (games or {}).values():
        for src in g.get("sources", []):
            if src.get("type") == "supabase_slot":
                tables.setdefault(src["table"], src.get("date_column", "draw_date"))
            elif src.get("type") == "supabase":
                t = src.get("table") or sb.get("table", "results")
                tables.setdefault(t, src.get("order_column") or sb.get("order_column")
                                  or src.get("draw_column") or sb.get("draw_column"))
    if not tables:
        tables[sb.get("table", "results")] = sb.get("order_column") or sb.get("draw_column")

    for table, order in tables.items():
        print("-" * 70)
        params = [("select", "*"), ("limit", "5")]
        if order:
            params.append(("order", order + ".desc.nullslast"))
        try:
            rows = supabase_get(sb, table, params)
        except Exception as e:
            print("Could not read table '%s': %s" % (table, e))
            continue
        if not rows:
            print("Table '%s' returned no rows. If it has data, the key is not "
                  "allowed to read it (Row Level Security) - see the setup guide."
                  % table)
            continue
        print("Columns in '%s': %s" % (table, ", ".join(rows[0].keys())))
        print("Latest rows:")
        for row in rows:
            print("  " + json.dumps(row, default=str)[:300])

    print("-" * 70)
    print("Draw IDs the feeder would use right now:")
    today = dt.date.today()
    for key, g in (games or {}).items():
        for src in g.get("sources", []):
            if src.get("type") not in ("supabase_slot", "supabase"):
                continue
            try:
                r = SOURCES[src["type"]](src, g, settings, today)
                val = r["next"] if isinstance(r, dict) else (
                    None if r is None else r + int(g.get("increment", 1)))
                print("  %-22s %s" % (key, "-" if val is None else val))
            except Exception as e:
                print("  %-22s error: %s" % (key, e))
            break


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
