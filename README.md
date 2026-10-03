# vMix Lottery Title Data (Date + Next Draw ID)

Fills two fields in each game's vMix title:

| Field          | Example                | Where it comes from                                   |
|----------------|------------------------|-------------------------------------------------------|
| `Date.Text`    | `Mon. 9th Sept. 2026`  | PC clock, formatted by the script                     |
| `DRAW_ID.Text` | `10452`                | last published draw number **+ 1**                    |

**Step-by-step setup guide (PDF): [`docs/vMix_Lotto_Setup_Guide.pdf`](docs/vMix_Lotto_Setup_Guide.pdf)**

vMix cannot build ordinals ("9th", "12th") or fetch draw numbers by itself, so a
small Python script runs on the vMix PC. It works out the values and passes them
to vMix in two ways. Use either one or both:

1. **Data Source files (recommended).** One CSV per game/time period in `output\`.
   Each preset binds its title to its own file, so no row selection is needed.
2. **vMix Web API push.** The script asks vMix which preset is loaded
   (for example `Daily 3 Morning.vmix`) and sets the title fields directly.

```
 Supabase (email blast results) ─┐                       ┌─> output\daily3_morning.csv ─> vMix Data Source
 about.nla.gd (backup)          ─┼─> vmix_lotto_data.py ─┤
 overrides.json                 ─┘   (every 5 min)       └─> http://127.0.0.1:8088/api SetText (loaded preset)
```

## Games covered (13 entries in `config.json`)

| Key                                         | vMix preset it serves            |
|---------------------------------------------|----------------------------------|
| `daily3_morning` / `_midday` / `_afternoon` / `_night`       | Daily 3 Morning … Night      |
| `playway_morning` / `_midday` / `_afternoon` / `_night`      | Play Way Morning … Night     |
| `dailypick3_morning` / `_midday` / `_afternoon` / `_night`   | Daily Pick 3 Morning … Night |
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

1. In the Supabase dashboard open **Project Settings → API** (newer dashboards:
   **Data API** / **API Keys**).
2. Put the **Project URL** in `config.json` → `settings.supabase.url`.
3. Copy the **anon / publishable** key into a new file `supabase_key.txt` next to
   the script. That file is git-ignored. The key can also go in the `SUPABASE_KEY`
   environment variable. **Do not use the service_role / secret key.**
4. Double-click `check_sources.bat`. It lists the tables the key can see, the
   columns in the configured table, and its 5 latest rows.
5. Set `table` and `draw_column` (plus `order_column` if the draw number is stored
   as text) in `settings.supabase`. Then make each game's `filters` match the
   table's column names and values:

```json
"supabase": { "url": "https://abcdefghijkl.supabase.co", "key_file": "supabase_key.txt",
              "table": "results", "draw_column": "draw_number", "order_column": "" }

{ "type": "supabase", "filters": { "game": "Play Way", "period": "Night" } }
```

The script reads the row with the highest draw number for those filters
(`order=<draw_column>.desc&limit=1`). Filters ignore upper/lower case, and `*`
works as a wildcard (`"Play*Way"`).

If the table has rows but the script sees none, Row Level Security is blocking
the public key. Allow read-only access in the SQL editor:

```sql
create policy "vMix can read results" on public.results for select to anon using (true);
```

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
{ "daily3_morning": { "date": "2026-10-03", "next_draw": 12345 } }
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

Do this in each game's `.vmix` file (Daily 3 Morning, Daily 3 Midday, …, Lotto).

### Title

1. The title's fields are `Date.Text` and `DRAW_ID.Text` (exact spelling and case).
   If a title uses other names, change `vmix_api.date_field` / `vmix_api.draw_field`.
2. Give the title input the same name in every preset, e.g. **`LottoTitle`**
   (right-click the input → *Input Settings → General → Title*). The API push
   uses this name.

### Option 1: Data Source (recommended)

1. **Settings → Data Sources → Add → Excel/CSV** (in older vMix: the
   **Data Sources** button at the bottom).
2. Pick that preset's own file, e.g. `C:\vMixLotto\output\daily3_morning.csv`.
3. Tick **Auto Refresh** and set the interval to about 10 seconds.
4. Open the title's input settings (cog → **Data Source** tab). Bind
   `Date.Text` → column **Date** and `DRAW_ID.Text` → column **DRAW_ID**.
5. **Save the preset.** The binding is stored in the `.vmix` file.

| Preset file        | Data Source file           |
|--------------------|----------------------------|
| Daily 3 Morning    | `daily3_morning.csv`       |
| Daily 3 Midday     | `daily3_midday.csv`        |
| Daily 3 Afternoon  | `daily3_afternoon.csv`     |
| Daily 3 Night      | `daily3_night.csv`         |
| Play Way …         | `playway_<period>.csv`     |
| Daily Pick 3 …     | `dailypick3_<period>.csv`  |
| Lotto              | `lotto.csv`                |

### Option 2: Web API push (no binding needed)

1. Turn on **Settings → Web Controller** (port 8088).
2. In `config.json`, set each game's `preset_match` to text contained in its
   preset filename. **It must match your real filenames**, e.g. if the file is
   `Dail3 Morning.vmix`, use `"preset_match": "Dail3 Morning"`. Matching ignores
   upper/lower case.
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

Per game, `draw_format` can pad or prefix the number:
`"Draw #{0}"` or `"{0:06d}"`.

## Tests

```
python -m unittest discover -s tests
```
