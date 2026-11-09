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
  python vmix_lotto_data.py --fix-today      record draws moved to another
                                             time slot or cancelled today
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
import shutil
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

_quiet = False


def log(msg):
    if _quiet:
        return
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

    closing = src.get("closing")
    if src.get("incident"):
        return {"next": incident_number(found, periods, t_idx, today_s,
                                        src.get("cancelled") or [], closing)}

    (l_date, l_idx), l_draw = max(found)
    if l_date == today_s:
        steps = t_idx - l_idx
        if steps <= 0:  # this period already passed today without a number
            return None
        return {"next": l_draw + steps}
    # last number used before today + today's slots up to the target
    return {"next": last_before_today(found, periods, today_s, closing) + t_idx + 1}


def last_before_today(found, periods, today_s, closing=None):
    """Last draw number used before today.

    Normally the latest row, with any draws still missing from that day
    counted as held. After a day with moved or cancelled draws, the number
    used at night that day (remembered in state.json as "closing") is used
    instead, so the next day continues from it.
    """
    before = [f for f in found if f[0][0] < today_s]
    if not before:
        return None
    (l_date, l_idx), l_draw = max(before)
    if closing and today_s > closing["date"] >= l_date:
        same_day = [draw for (d, _), draw in before if d == closing["date"]]
        return max([int(closing["last"])] + same_day)
    return l_draw + (max(1, len(periods)) - 1 - l_idx)


def incident_number(found, periods, t_idx, today_s, cancelled, closing=None):
    """Draw number of today's draw t_idx on a day with changes.

    Counts from the last draw before today (its day's remaining draws are
    assumed held), then one number per draw of today up to t_idx, skipping
    draws that are cancelled with their number not used. Today's rows are
    not used for counting, because a moved draw may have been entered under
    the slot it was held in.
    """
    base = last_before_today(found, periods, today_s, closing)
    if base is None:  # nothing before today: work back from today's earliest row
        (d, idx), draw = min(found)
        base = draw - 1 - sum(1 for i in range(idx) if periods[i] not in cancelled)
    return base + sum(1 for i in range(t_idx + 1) if periods[i] not in cancelled)


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

def supabase_value(src, settings, today):
    """Latest value of a column (e.g. lotto_results.jackpot_amount).

    Returns (value, "today" | "latest") or (None, None). Today's row wins;
    otherwise the most recent earlier row is used if use_latest is true.
    """
    sb = supabase_settings(settings)
    col = src["value_column"]
    date_col = src.get("date_column", "draw_date")
    rows = supabase_get(sb, src["table"], [
        ("select", "%s,%s" % (date_col, col)),
        (col, "not.is.null"),
        (date_col, "lte." + today.isoformat()),
        ("order", date_col + ".desc"),
        ("limit", "1")])
    if not rows:
        return None, None
    row = rows[0]
    if str(row[date_col])[:10] == today.isoformat():
        return row[col], "today"
    if src.get("use_latest", True):
        return row[col], "latest"
    return None, None


def format_value(fmt, value):
    try:
        return fmt.format(float(value))
    except (TypeError, ValueError):
        return fmt.format(value)


def extra_values(key, game, settings, state, overrides, today):
    """Extra title fields for a game (e.g. Lotto JACKPOT): {column: text}."""
    out = {}
    ov = overrides.get(key)
    ov_today = isinstance(ov, dict) and ov.get("date") == today.isoformat()
    for ex in game.get("extras", []):
        name = ex["column"]
        okey = ex.get("override_key", name.lower())
        value, origin = None, None
        if ov_today and ov.get(okey) is not None:
            value, origin = ov[okey], "override"
        else:
            try:
                value, origin = supabase_value(ex["source"], settings, today)
            except Exception as e:
                log("  %s: %s lookup failed: %s" % (key, name, e))
            if value is None:
                value = state.get(key, {}).get(okey)
                origin = "cached" if value is not None else "none"
        if value is not None:
            state.setdefault(key, {})[okey] = value
        text = "" if value is None else format_value(ex.get("format", "{0}"), value)
        out[name] = text
        log("  %-22s %s %s (%s)" % ("", name, text or "-", origin))
    return out


# --------------------------------------------------------------------------
# Today's changes (draws moved to another time slot, or cancelled)
# --------------------------------------------------------------------------

PERIOD_NAMES = {"mid_morning": "Morning", "midday": "Midday",
                "mid_afternoon": "Afternoon", "evening": "Night"}
DAILY_GAMES = {"pick3": "Pick 3", "playway": "Play Way", "cash4": "Cash 4"}


def today_changes_file(settings):
    return settings.get("today_changes_file", "today_changes.json")


def load_today_changes(settings, today):
    """Changes recorded for today; an older file is ignored (expires at midnight)."""
    data = load_json(today_changes_file(settings), {}) or {}
    if data.get("date") != today.isoformat():
        return []
    return data.get("changes", [])


def save_today_changes(settings, today, changes):
    write_atomic(today_changes_file(settings),
                 json.dumps({"date": today.isoformat(), "changes": changes}, indent=2))


def describe_change(c):
    who = "all daily games" if c["games"] == "daily" else DAILY_GAMES.get(c["games"], c["games"])
    draw = PERIOD_NAMES.get(c["draw"], c["draw"])
    if c["type"] == "moved":
        return "%s draw held in the %s slot (%s)" % (
            draw, PERIOD_NAMES.get(c["slot"], c["slot"]), who)
    return "%s draw cancelled, number not used (%s)" % (draw, who)


def game_slot(game):
    """(group key e.g. 'pick3', own period e.g. 'mid_morning') or (None, None)."""
    for src in game.get("sources", []):
        if src.get("type") == "supabase_slot" and src.get("period"):
            return game.get("incident_group"), src["period"]
    return None, None


def changes_for(game, changes):
    group, _ = game_slot(game)
    if not group:
        return []
    return [c for c in changes if c["games"] in ("daily", group)]


def next_draw_id(key, game, settings, state, overrides, today, changes=None):
    """Return (next_draw_id, where_it_came_from)."""
    ov = overrides.get(key)
    if (isinstance(ov, dict) and ov.get("date") == today.isoformat()
            and ov.get("next_draw") is not None):
        return int(ov["next_draw"]), "override"

    increment = int(game.get("increment", 1))
    mine = changes_for(game, changes or [])
    group, _ = game_slot(game)
    closing = (state.get("_closing") or {}).get(group) if group else None
    sources = [dict(s, closing=closing) if s.get("type") == "supabase_slot" else s
               for s in game.get("sources", [])]
    if mine:
        _, slot = game_slot(game)
        cancelled = [c["draw"] for c in mine if c["type"] == "cancelled"]
        airs = slot
        for c in mine:
            if c["type"] == "moved" and c["slot"] == slot:
                airs = c["draw"]  # this slot now holds a moved draw
        if airs in cancelled:
            return None, "cancelled"
        # only the database can count around moved/cancelled draws
        sources = [dict(s, period=airs, cancelled=cancelled, incident=True)
                   for s in sources if s.get("type") == "supabase_slot"]
        # no "lower than before" check today: the numbers really do go back
    last = None
    for src in sources:
        kind = src.get("type")
        try:
            last = SOURCES[kind](src, game, settings, today)
        except Exception as e:  # keep going with the next source
            log("  %s: %s source failed: %s" % (key, kind, e))
            continue
        if last is not None:
            nxt = last["next"] if isinstance(last, dict) else last + increment
            prev = state.get(key, {}).get("next_draw")
            if prev and nxt < prev and not mine:
                log("  %s: %s gave %d, lower than previous %d - ignored"
                    % (key, kind, nxt, prev))
                continue
            return nxt, kind
        log("  %s: %s source found no draw number" % (key, kind))

    if mine:  # a stale number would be wrong today: better blank and loud
        log("  %s: CHECK DRAW ID - draws changed today and the database could "
            "not be read. Use an override." % key)
        return None, "none"
    prev = state.get(key, {}).get("next_draw")
    if prev:
        return prev, "cached"
    return None, "none"


def preset_matches(names, preset_file):
    """True if any of the names is part of the preset file name. Case, spaces
    and punctuation are ignored: "Pick 3 Night" matches "Daily Pick-3 Night.vmix"."""
    def squash(text):
        return re.sub(r"[^a-z0-9]", "", text.lower())
    if isinstance(names, str):
        names = [names]
    loaded = squash(preset_file)
    return any(squash(n) and squash(n) in loaded for n in names or [])


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
        if not preset_matches(res["game"].get("preset_match"), preset):
            continue
        title = res["game"].get("title_input") or vm.get("title_input")
        fields = {vm.get("date_field", "Date.Text"): res["Date"],
                  vm.get("draw_field", "DRAW_ID.Text"): res["DRAW_ID"]}
        for ex in res["game"].get("extras", []):
            if ex.get("vmix_field"):
                fields[ex["vmix_field"]] = res.get("extras", {}).get(ex["column"], "")
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


def vmix_status(settings):
    """(preset file name, is_recording) from the vMix API, or None."""
    vm = settings.get("vmix_api") or {}
    base = vm.get("url", "http://127.0.0.1:8088/api/").rstrip("/") + "/"
    try:
        root = ET.fromstring(http_get_nocache(base))
    except Exception:
        return None
    preset = os.path.basename(root.findtext("preset") or "")
    recording = (root.findtext("recording") or "").strip().lower() == "true"
    return preset, recording


def game_for_preset(games, preset_file):
    for key, game in games.items():
        if preset_matches(game.get("preset_match"), preset_file):
            return key
    return None


def clean_name(text, space="_"):
    text = re.sub(r'[<>:"/\\|?*]', "", str(text)).strip()
    return re.sub(r"\s+", space, text) if space is not None else text


def recording_target(rc, game, draw, day, ext):
    """Folder and file name for a finished recording."""
    space = rc.get("space_replacement", "_")
    values = {
        "date": day.strftime(rc.get("date_format", "%Y-%m-%d")),
        "game": clean_name(game.get("game_label") or game.get("name", ""), space),
        "period": clean_name(game.get("period_label", ""), space),
        "draw": draw if draw is not None else "NoDraw",
        "ext": ext,
    }
    folder = rc.get("folder", r"C:\Users\user\Documents\vmixstorage\{date}\{game}").format(**values)
    name = rc.get("filename", "{game}_{draw}_{period}_{date}{ext}").format(**values)
    sep = space or ""
    if sep:  # a game without a period (Lotto) would leave "__"
        name = re.sub(re.escape(sep) + "{2,}", sep, name)
        name = name.replace(sep + ext, ext).strip(sep)
    return folder, name


class RecordingFiler:
    """Moves finished vMix recordings to <date>\\<game>\\<game>_<draw>_<period>_<date>.mp4.

    vMix records into rc["watch_folder"]. When a recording starts, the loaded
    preset tells us the game; the draw number is taken from the current
    results. When vMix stops recording, settled files are moved and renamed.
    """

    def __init__(self):
        self.active = None  # {"key", "draw", "date", "started"}

    def tick(self, cfg, results):
        settings = cfg.get("settings", {})
        rc = settings.get("recordings") or {}
        if not rc.get("enabled"):
            return
        status = vmix_status(settings)
        if status is None:
            return  # vMix not reachable: never move files we cannot judge
        preset, recording = status
        games = cfg["games"]
        if recording:
            if self.active is None or self.active.get("stopped"):
                key = game_for_preset(games, preset)
                draw = (results or {}).get(key, {}).get("draw") if key else None
                self.active = {"key": key, "draw": draw, "date": dt.date.today(),
                               "started": time.time()}
                log("Recording started: %s (preset %s, draw %s)"
                    % (key or "unknown game", preset or "-", draw))
            return
        if self.active:  # keep it: files may still be settling after the stop
            self.active["stopped"] = True
        self.file_finished(rc, games, results, preset)

    def file_finished(self, rc, games, results, preset):
        watch = resolve(rc.get("watch_folder", r"C:\Users\user\Documents\vmixstorage\_incoming"))
        if not os.path.isdir(watch):
            return
        exts = [e.lower() for e in rc.get("extensions", [".mp4", ".mov", ".mkv", ".avi"])]
        settle = float(rc.get("settle_seconds", 5))
        now = time.time()
        for name in sorted(os.listdir(watch)):
            src = os.path.join(watch, name)
            ext = os.path.splitext(name)[1].lower()
            if not os.path.isfile(src) or ext not in exts:
                continue
            st = os.stat(src)
            if st.st_size == 0 or now - st.st_mtime < settle:
                continue  # still being written
            info = self.active
            if not info or not info.get("key") or st.st_mtime < info["started"] - 60:
                key = game_for_preset(games, preset)  # file from before we watched
                info = {"key": key,
                        "draw": (results or {}).get(key, {}).get("draw") if key else None,
                        "date": dt.datetime.fromtimestamp(st.st_mtime).date()}
            if not info.get("key"):
                log("Recording %s: no game matches preset '%s' - left in %s"
                    % (name, preset, watch))
                continue
            folder, new_name = recording_target(rc, games[info["key"]], info["draw"],
                                                info["date"], ext)
            os.makedirs(folder, exist_ok=True)
            dest = os.path.join(folder, new_name)
            stem, n = os.path.splitext(dest)[0], 2
            while os.path.exists(dest):  # never overwrite an earlier take
                dest = "%s_%d%s" % (stem, n, ext)
                n += 1
            try:
                shutil.move(src, dest)
            except OSError as e:  # e.g. still locked by vMix - try next tick
                log("Recording %s not moved yet: %s" % (name, e))
                continue
            log("Recording saved: %s" % dest)


def remember_closing(state, games, results, changes, today):
    """On a day with changes, store each game's last draw number of the day
    (the highest number used, normally the Night draw) so tomorrow continues
    from it. Cleared again if today's changes are removed."""
    closing = state.setdefault("_closing", {})
    day = today.isoformat()
    groups = {game_slot(g)[0] for g in games.values()} - {None}
    for group in groups:
        keys = [k for k, g in games.items() if game_slot(g)[0] == group]
        if any(changes_for(games[k], changes) for k in keys):
            used = [results[k]["draw"] for k in keys
                    if results.get(k, {}).get("draw") is not None]
            if used:
                closing[group] = {"date": day, "last": max(used)}
        elif closing.get(group, {}).get("date") == day:
            del closing[group]


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
    changes = load_today_changes(settings, today)
    for c in changes:
        log("TODAY'S CHANGE: " + describe_change(c))

    results = {}
    for key, game in games.items():
        draw, origin = next_draw_id(key, game, settings, state, overrides, today,
                                    changes)
        fmt = game.get("draw_format") or settings.get("draw_format") or "{0}"
        draw_text = "" if draw is None else fmt.format(draw)
        results[key] = {"game": game, "Date": date_text, "DRAW_ID": draw_text,
                        "draw": draw}
        if draw is not None:
            state.setdefault(key, {}).update({
                "next_draw": draw, "source": origin,
                "updated": dt.datetime.now().isoformat(timespec="seconds")})
        log("  %-22s next draw %-8s (%s)" % (key, "-" if draw is None else draw, origin))
        extras = extra_values(key, game, settings, state, overrides, today)
        results[key]["extras"] = extras

        buf = io.StringIO()
        w = csv.writer(buf, quoting=csv.QUOTE_ALL)  # keeps leading spaces
        w.writerow(["Game", "Date", "DRAW_ID"] + list(extras))
        w.writerow([game.get("name", key), date_text, draw_text] + list(extras.values()))
        write_atomic(os.path.join(out_dir, key + ".csv"), buf.getvalue(), bom=True)

    # One combined file as well (one row per game) - handy for checking.
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    extra_cols = []
    for res in results.values():
        extra_cols += [c for c in res["extras"] if c not in extra_cols]
    w.writerow(["Key", "Game", "Date", "DRAW_ID"] + extra_cols)
    for key, res in results.items():
        w.writerow([key, res["game"].get("name", key), res["Date"], res["DRAW_ID"]]
                   + [res["extras"].get(c, "") for c in extra_cols])
    write_atomic(os.path.join(out_dir, "all_games.csv"), buf.getvalue(), bom=True)

    remember_closing(state, games, results, changes, today)
    write_atomic(state_file, json.dumps(state, indent=2))
    try:
        vmix_push(settings, results)
    except Exception as e:  # the CSV files are already written
        log("vMix push failed: %s" % e)
    return results


def _pick(ask, out, question, options, default=None):
    """Numbered menu; returns the chosen value. options: [(label, value)]."""
    while True:
        out("")
        out(question)
        for i, (label, _) in enumerate(options, 1):
            out("  %d  %s" % (i, label))
        hint = " [Enter = %d]" % default if default else ""
        answer = ask("Choose 1-%d%s: " % (len(options), hint)).strip()
        if not answer and default:
            answer = str(default)
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][1]
        out("Please type a number from the list.")


def _draw_table(cfg, results, out):
    out("")
    out("Draw IDs now:        Morning   Midday    Afternoon Night")
    for group, name in DAILY_GAMES.items():
        cells = []
        for per in ("morning", "midday", "afternoon", "night"):
            draw = (results.get("%s_%s" % (group, per)) or {}).get("draw")
            cells.append("%-9s" % ("-" if draw is None else draw))
        out("  %-18s %s" % (name, " ".join(cells)))


def fix_today(cfg, ask=input, out=print):
    """Interactive prompt to record today's moved / cancelled draws."""
    global _quiet
    settings = cfg.get("settings", {})
    today = dt.date.today()
    slots = [(PERIOD_NAMES[p], p) for p in ("mid_morning", "midday", "mid_afternoon", "evening")]
    games = [("All daily games (Pick 3, Play Way, Cash 4)", "daily")] + [
        (name, key) for key, name in DAILY_GAMES.items()]

    def refresh():
        global _quiet
        _quiet = True
        try:
            results = run_once(cfg)
        except Exception as e:
            out("Could not update the titles now: %s" % e)
            return
        finally:
            _quiet = False
        _draw_table(cfg, results, out)

    out("=" * 62)
    out("TODAY'S DRAW CHANGES - %s" % format_date(today, cfg.get("date_format")))
    out("=" * 62)
    try:
        while True:
            changes = load_today_changes(settings, today)
            out("")
            out("Changes recorded for today:")
            for i, c in enumerate(changes, 1):
                out("  %d. %s" % (i, describe_change(c)))
            if not changes:
                out("  none - a normal day")
            action = _pick(ask, out, "What do you want to do?", [
                ("A draw is being held in a different time slot", "move"),
                ("A draw is cancelled (its number is not used)", "cancel"),
                ("Remove one of the changes above", "remove"),
                ("Clear all changes (back to a normal day)", "clear"),
                ("Done", "done")], default=5)
            if action == "done":
                break
            if action == "clear":
                changes = []
            elif action == "remove":
                if not changes:
                    out("There is nothing to remove.")
                    continue
                gone = _pick(ask, out, "Which change should be removed?",
                             [(describe_change(c), i) for i, c in enumerate(changes)])
                changes.pop(gone)
            else:
                who = _pick(ask, out, "Which games?", games, default=1)
                if action == "move":
                    draw = _pick(ask, out, "Which draw is being held late (or early)?", slots)
                    slot = _pick(ask, out, "In which time slot is it being held now?", slots)
                else:
                    draw = _pick(ask, out, "Which draw is cancelled?", slots)
                    slot = None
                # one entry per draw and per slot: a new answer replaces older ones
                changes = [c for c in changes if not (
                    c["games"] == who and (c["draw"] == draw or
                                           (slot and c.get("slot") == slot)))]
                if action == "move" and slot != draw:
                    changes.append({"games": who, "type": "moved", "draw": draw, "slot": slot})
                elif action == "cancel":
                    changes.append({"games": who, "type": "cancelled", "draw": draw})
                else:
                    out("That draw is back in its own slot.")
            save_today_changes(settings, today, changes)
            out("Saved. The running feeder picks this up within a few seconds.")
            refresh()
    except (EOFError, KeyboardInterrupt):
        out("")
    finally:
        _quiet = False
    out("Load the preset for the time slot you are airing in; its title and "
        "recording name follow these changes.")


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
        for ex in g.get("extras", []):
            try:
                value, origin = supabase_value(ex["source"], settings, today)
                text = "-" if value is None else format_value(ex.get("format", "{0}"), value)
                print("  %-22s %s %s (%s)" % ("", ex["column"], text, origin or "none"))
            except Exception as e:
                print("  %-22s %s error: %s" % ("", ex["column"], e))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--loop", type=int, default=0,
                    help="repeat every N seconds (0 = run once)")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--fix-today", action="store_true",
                    help="record draws moved to another slot or cancelled today")
    args = ap.parse_args()

    cfg = load_json(args.config)
    if cfg is None:
        sys.exit("Config file not found: %s" % resolve(args.config))

    if args.probe:
        probe(cfg)
        return
    if args.fix_today:
        fix_today(cfg)
        return
    filer = RecordingFiler()
    results = {}
    next_refresh = 0.0
    changes_seen = None
    while True:
        try:  # refresh at once when today's changes are edited
            stamp = os.path.getmtime(resolve(today_changes_file(cfg.get("settings", {}))))
        except OSError:
            stamp = None
        if stamp != changes_seen:
            changes_seen, next_refresh = stamp, 0.0
        if time.time() >= next_refresh:
            try:
                results = run_once(cfg) or results
            except Exception as e:
                log("ERROR: %s" % e)
                if not args.loop:
                    sys.exit(1)
            next_refresh = time.time() + args.loop
        try:
            filer.tick(cfg, results)
        except Exception as e:
            log("Recording filing error: %s" % e)
        if not args.loop:
            break
        rc = cfg.get("settings", {}).get("recordings") or {}
        poll = float(rc.get("poll_seconds", 5))
        time.sleep(max(1.0, min(poll, next_refresh - time.time())))
        cfg = load_json(args.config) or cfg  # pick up config edits live


if __name__ == "__main__":
    main()
