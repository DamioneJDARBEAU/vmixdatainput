# vMix Lottery Title Data (Date + Next Draw ID)

Fills two fields in each game's vMix title:

| Field          | Example                | Where it comes from                                   |
|----------------|------------------------|-------------------------------------------------------|
| `Date.Text`    | `Mon. 9th Sept. 2026`  | PC clock, formatted by the script                     |
| `DRAW_ID.Text` | `Draw ID:  10452`      | today's draw number (`draw_format`, two spaces)       |

**Step-by-step setup guide (PDF): [`docs/vMix_Lotto_Setup_Guide.pdf`](docs/vMix_Lotto_Setup_Guide.pdf)**

vMix cannot build ordinals ("9th", "12th") or fetch draw numbers by itself, so a
small Python script runs on the vMix PC. It works out the values and passes them
to vMix in two ways. Use either one or both:

1. **Data Source files (recommended).** One CSV per game/time period in `output\`.
   Each preset binds its title to its own file, so no row selection is needed.
2. **vMix Web API push.** The script asks vMix which preset is loaded
   (for example `Pick 3 Morning.vmix`) and sets the title fields directly.

```
 Supabase (email blast results) ─┐                       ┌─> output\pick3_morning.csv ─> vMix Data Source
 about.nla.gd (backup)          ─┼─> vmix_lotto_data.py ─┤
 overrides.json                 ─┘   (every 5 min)       └─> http://127.0.0.1:8088/api SetText (loaded preset)
```

## Games covered (13 entries in `config.json`)

| Key                                         | vMix preset it serves            |
|---------------------------------------------|----------------------------------|
| `pick3_morning` / `_midday` / `_afternoon` / `_night`        | Pick 3 (also called Daily 3 / Daily Pick 3) Morning … Night |
| `playway_morning` / `_midday` / `_afternoon` / `_night`      | Play Way Morning … Night     |
| `cash4_morning` / `_midday` / `_afternoon` / `_night`        | Cash 4 (also called Daily Cash 4) Morning … Night |
| `lotto`                                     | Lotto                            |

Super 6 is left out on purpose. Rename or add games by editing `config.json`;
the code does not need to change.

---

## 1. Install on the vMix PC

1. Install Python 3 from python.org and tick **"Add python.exe to PATH"**.
2. Copy this folder to e.g. `C:\vMixLotto\`.
3. Double-click `run_once.bat`. It creates `C:\vMixLotto\output\` with one CSV per game.

## 2. Point it at the draw numbers

Open `config.json`. Each game has a list of `sources`, tried in order. The first
one that returns a number wins, and the result is that number plus `increment` (1).
Each game tries **Supabase** first and the **website** second.

### a) Supabase (email blast results database) – main source

`config.json` is already mapped to the results tables:

| vMix presets                 | Supabase column                    | period values                                       |
|------------------------------|------------------------------------|-----------------------------------------------------|
| Pick 3 / Daily 3 / Daily Pick 3 … | `daily_results.pick3_draw_no` | Morning `mid_morning`, Midday `midday`,        |
| Play Way …                   | `daily_results.play_way_draw_no`   | Afternoon `mid_afternoon`, Night `evening`          |
| Cash 4 / Daily Cash 4 …      | `daily_results.cash4_draw_no`      |                                                     |
| Lotto                        | `lotto_results.draw_no`            | one draw per `draw_date`                            |

These use the `supabase_slot` source. Draw numbers run in one sequence through
the day (mid_morning → midday → mid_afternoon → evening → next day), so for each
preset it:

1. uses **today's row for that period** if it already has a draw number;
2. otherwise takes the **latest** draw number (rows dated after today are ignored)
   and counts forward one per draw slot to today's period. For example, if
   yesterday's evening was 504, today's draws are 505 / 506 / 507 / 508.

Lotto: today's row if present, otherwise the latest `draw_no` + 1. On a disrupted
or cancelled day, use an override (c).

Setup:

1. In the Supabase dashboard open **Project Settings → API** (newer dashboards:
   **Data API** / **API Keys**). Put the **Project URL** in `settings.supabase.url`.
2. Copy the **anon / publishable** key into `supabase_key.txt` next to the script
   (git-ignored), or set the `SUPABASE_KEY` environment variable.
   **Never use the service_role / secret key.**
3. Run `check_sources.bat`. It shows the latest rows of both tables and the draw
   ID every preset would get right now.
4. If a table "returned no rows", run `supabase/vmix_read_access.sql` in the
   Supabase SQL editor. It lets the public key read **published** results only
   (`published_at is not null`), so results awaiting approval stay hidden.

There's also a generic `supabase` source for other tables (latest value + 1,
with `table`, `draw_column`, `order_column` and `filters`).

### b) Website (`about.nla.gd`) – backup source

The URL is in one place, `settings.website_url`. When the site moves, change that
line. A single game can also have its own `"url"` inside its source.

```json
{ "type": "web", "label_regex": "Daily\\s*3\\W{0,20}Morning", "window": 400 }
```

The script turns the page into plain text, finds the game label (`label_regex`),
and reads the first `Draw … <number>` within `window` characters after it.
The WEBSITE part of `check_sources.bat` prints every draw number it finds along
with the text around it.

* If the page shows e.g. `Draw No: 10450` next to "DAILY 3 – MORNING", the defaults will work.
* If the wording differs (e.g. `Game #10450`), add `"draw_regex": "Game\\s*#\\s*(\\d+)"` to the source.
* If nothing is found, the page is probably built by JavaScript. Use a `json`
  source pointing at the data the page loads (browser DevTools → Network → Fetch/XHR).

Other source types are also supported: `sqlite`, `odbc` (needs `pip install pyodbc`)
and `csv`. See the docstring in `vmix_lotto_data.py`.

### c) Manual override

Copy `overrides.example.json` to `overrides.json` and set the draw number to show.
An override only applies on the date it carries, so a stale one cannot leak into
the next day:

```json
{ "pick3_morning": { "date": "2026-10-03", "next_draw": 12345 } }
```

### Safety nets

* If every source fails, the last good value from `state.json` is kept.
* A value lower than the previous one is treated as a glitch and ignored.
* Errors are printed with the game name and source, so you can see what broke.

## 3. Keep it running

| File                    | What it does                                                        |
|-------------------------|---------------------------------------------------------------------|
| `run_once.bat`          | Updates everything once and shows the result. Use it to test.       |
| `run_loop.bat`          | Updates every 5 minutes and restarts itself if it stops. Leave it open (minimised). |
| `install_autostart.bat` | Right-click → *Run as administrator*. Starts `run_loop.bat` at every log-on. |
| `remove_autostart.bat`  | Right-click → *Run as administrator*. Removes the auto-start.       |
| `check_sources.bat`     | Shows the Supabase tables/columns/latest rows and the draw numbers found on the website; saves them to `check_result.txt`. |

Run it every few minutes, not just once a day. After each draw's result is
published, that game's next draw ID moves up on its own.

## 4. vMix setup (once per preset)

Do this in each game's `.vmix` file (Pick 3 Morning, Pick 3 Midday, …, Lotto).

### Title

1. The title's fields are `Date.Text` and `DRAW_ID.Text` (exact spelling and case).
   If a title uses other names, change `vmix_api.date_field` / `vmix_api.draw_field`.
2. Give the title input the same name in every preset, e.g. **`LottoTitle`**
   (right-click the input → *Input Settings → General → Title*). The API push
   uses this name.

### Option 1: Data Source (recommended)

1. **Settings → Data Sources → Add → Excel/CSV** (in older vMix: the
   **Data Sources** button at the bottom).
2. Pick that preset's own file, e.g. `C:\vMixLotto\output\pick3_morning.csv`.
3. Tick **Auto Refresh** and set the interval to about 10 seconds.
4. Open the title's input settings (cog → **Data Source** tab). Bind
   `Date.Text` → column **Date** and `DRAW_ID.Text` → column **DRAW_ID**.
5. **Save the preset.** The binding is stored in the `.vmix` file.

| Preset file        | Data Source file           |
|--------------------|----------------------------|
| Pick 3 Morning     | `pick3_morning.csv`        |
| Pick 3 Midday      | `pick3_midday.csv`         |
| Pick 3 Afternoon   | `pick3_afternoon.csv`      |
| Pick 3 Night       | `pick3_night.csv`          |
| Play Way …         | `playway_<period>.csv`     |
| Cash 4 …           | `cash4_<period>.csv`       |
| Lotto              | `lotto.csv`                |

### Option 2: Web API push (no binding needed)

1. Turn on **Settings → Web Controller** (port 8088).
2. Each game's `preset_match` lists the names its preset file may have. Pick 3
   accepts `Daily Pick 3 <period>`, `Pick 3 <period>` and `Daily 3 <period>`;
   Cash 4 accepts `Daily Cash 4 <period>` and `Cash 4 <period>`. Upper/lower case,
   spaces and dashes are ignored. If a file has another name (e.g.
   `Dail3 Morning.vmix`), add that name to the game's list.
3. If vMix rejects a field (wrong input or field name), the script logs
   `vMix: could not set ...` and carries on. The CSV files are always written first.

If both options are on, they write the same values, so they don't conflict.

### Date only, without Python (fallback)

`vmix_scripts/SetDateText.vb` is a vMix script (**Settings → Scripting**, VB.NET;
needs vMix 4K/Pro). It sets only the date. Run it from a shortcut or trigger.

## Changing formats

In `config.json` → `date_format`:

* `month_names` – e.g. use `"Sep."` instead of `"Sept."`
* `pattern` – e.g. `"{day} {date} {month}, {year}"` gives `Mon. 9th Sept., 2026`

The draw text comes from `settings.draw_format`, currently `"Draw ID:  {0}"`
(two spaces before the number). A game can have its own `draw_format`.
Other examples: `"Draw #{0}"`, or `"{0:06d}"` for leading zeros.

## Recordings: automatic folder and file name

vMix can't name a recording after the draw, so the feeder files it. vMix records
into `C:\Users\user\vmixstorage\_incoming`. When recording stops, the file is
moved and renamed to:

```
C:\Users\user\vmixstorage\<date>\<game>\<game>_<draw>_<period>_<date>.mp4
e.g. C:\Users\user\vmixstorage\2026-10-03\Pick_3\Pick_3_7930_Night_2026-10-03.mp4
     C:\Users\user\vmixstorage\2026-10-03\Lotto\Lotto_2101_2026-10-03.mp4
```

* The game and period come from the preset loaded when recording **started**
  (each game's `game_label` / `period_label`). The draw number is the one in the
  title. Loading the next preset right after stopping is fine.
* vMix setup: **Settings → Recording**, set the folder to `…\vmixstorage\_incoming`
  and choose an MP4 format. The **Web Controller** must be enabled, and
  `run_loop.bat` must be running (it checks vMix every `poll_seconds`).
* Paths, the date format and the name pattern are in `settings.recordings`
  (`watch_folder`, `folder`, `filename`, `date_format`, `space_replacement`).
  Change `user` if the Windows user name is different.
* Takes are never overwritten (`_2`, `_3` …). Unknown draw → `NoDraw`. If no game
  matches the preset, the file stays in `_incoming` and the log says so.

## Tests

```
python -m unittest discover -s tests
```
