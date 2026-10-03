# vMix Lottery Title Data (Date + Next Draw ID)

Fills two fields in each game's vMix title:

| Field      | Example                | Where it comes from                                   |
|------------|------------------------|-------------------------------------------------------|
| `DateText` | `Mon. 9th Sept. 2026`  | PC clock, formatted by the script                     |
| `DrawID`   | `10452`                | last published draw number **+ 1**                    |

vMix cannot build ordinals ("9th", "12th") or fetch draw numbers by itself, so a
small Python script runs on the vMix PC. It works out the values and passes them
to vMix in two ways. Use either one or both:

1. **Data Source files (recommended).** One CSV per game/time period in `output\`.
   Each preset binds its title to its own file, so no row selection is needed.
2. **vMix Web API push.** The script asks vMix which preset is loaded
   (for example `Daily 3 Morning.vmix`) and sets the title fields directly.

```
 about.nla.gd  ─┐                       ┌─> output\daily3_morning.csv ─> vMix Data Source
 email-blast DB ─┼─> vmix_lotto_data.py ─┤
 overrides.json ─┘   (every 5 min)       └─> http://127.0.0.1:8088/api SetText (loaded preset)
```

## Games covered (13 entries in `config.json`)

| Key                                         | vMix preset it serves            |
|---------------------------------------------|----------------------------------|
| `daily3_morning` / `_midday` / `_afternoon` / `_night`       | Daily 3 Morning … Night      |
| `playwhe_morning` / `_midday` / `_afternoon` / `_night`      | Play Whe Morning … Night     |
| `dailypick3_morning` / `_midday` / `_afternoon` / `_night`   | Daily Pick 3 Morning … Night |
| `lotto`                                     | Lotto                            |

Super 6 is left out on purpose. Rename or add games by editing `config.json`;
the code does not need to change.

---

## 1. Install on the vMix PC

1. Install Python 3 from python.org and tick **"Add python.exe to PATH"**.
2. Copy this folder to e.g. `C:\vMixLotto\`.
3. Double-click `run_once.bat`. It creates `C:\vMixLotto\output\` with one CSV per game.
4. (Only if the email database is SQL Server/MySQL/Access) run `pip install pyodbc`.

## 2. Point it at the draw numbers

Open `config.json`. Each game has a list of `sources`, tried in order. The first
one that returns a number wins, and the result is that number plus `increment` (1).

### a) Website (`about.nla.gd`)

The URL is in one place, `settings.website_url`. When the site moves, change that
line. A single game can also have its own `"url"` inside its source.

```json
{ "type": "web", "label_regex": "Daily\\s*3\\W{0,20}Morning", "window": 400 }
```

The script turns the page into plain text, finds the game label (`label_regex`),
and reads the first `Draw … <number>` within `window` characters after it.
**Check this against the real page first:** double-click `probe_website.bat`.
It prints every draw number it finds along with the text around it.

* If the page shows e.g. `Draw No: 10450` next to "DAILY 3 – MORNING", the defaults will work.
* If the wording differs (e.g. `Game #10450`), add `"draw_regex": "Game\\s*#\\s*(\\d+)"` to the source.
* If probe finds nothing, the page is probably built by JavaScript. In Chrome,
  press F12, open **Network → Fetch/XHR**, and reload. Find the JSON that holds
  the results, then use a `json` source instead:
  ```json
  { "type": "json", "url": "https://about.nla.gd/api/results", "path": "daily3.morning.drawNumber" }
  ```

### b) Email-blast database

The sample config already has this as the second (fallback) source. Change the
path, table and column names to match your database:

```json
{ "type": "sqlite", "database": "C:/EmailBlast/results.db",
  "query": "SELECT MAX(draw_number) FROM results WHERE game = ? AND period = ?",
  "params": ["Daily 3", "Morning"] }
```

For SQL Server, MySQL or Access, use ODBC:

```json
{ "type": "odbc",
  "connection_string": "DRIVER={ODBC Driver 17 for SQL Server};SERVER=dbserver;DATABASE=EmailBlast;Trusted_Connection=yes",
  "query": "SELECT MAX(DrawNo) FROM Results WHERE Game = ? AND Period = ?",
  "params": ["Daily 3", "Morning"] }
```

If the email system can only export a spreadsheet, save it as CSV and use:

```json
{ "type": "csv", "file": "C:/EmailBlast/export.csv", "column": "Draw",
  "filter": { "Game": "Daily 3", "Period": "Morning" } }
```

To make the database the main source, move it above the `web` entry.

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

Pick one of these:

* **Simple:** start `run_loop.bat` before the show. It updates every 5 minutes.
* **Hands-off (recommended):** Windows **Task Scheduler → Create Task**
  * Trigger: *At log on* (or daily at 5:00 am)
  * Action: `python.exe` with argument `C:\vMixLotto\vmix_lotto_data.py --loop 300`
    and *Start in* set to `C:\vMixLotto`
  * Settings: tick *If the task fails, restart every 1 minute*

Run it every few minutes, not just once a day. After each draw's result is
published, that game's next draw ID moves up on its own.

## 4. vMix setup (once per preset)

Do this in each game's `.vmix` file (Daily 3 Morning, Daily 3 Midday, …, Lotto).

### Title

1. In **GT Title Designer**, give the two text fields clear names: `DateText` and
   `DrawID`. vMix shows them as `DateText.Text` and `DrawID.Text`.
2. Give the title input the same name in every preset, e.g. **`LottoTitle`**
   (right-click the input → *Input Settings → General → Title*). The API push
   uses this name.

### Option 1: Data Source (recommended)

1. **Settings → Data Sources → Add → Excel/CSV** (in older vMix: the
   **Data Sources** button at the bottom).
2. Pick that preset's own file, e.g. `C:\vMixLotto\output\daily3_morning.csv`.
3. Tick **Auto Refresh** and set the interval to about 10 seconds.
4. Open the title's input settings (cog → **Data Source** tab). Bind
   `DateText.Text` → column **DateText** and `DrawID.Text` → column **DrawID**.
5. **Save the preset.** The binding is stored in the `.vmix` file.

| Preset file        | Data Source file           |
|--------------------|----------------------------|
| Daily 3 Morning    | `daily3_morning.csv`       |
| Daily 3 Midday     | `daily3_midday.csv`        |
| Daily 3 Afternoon  | `daily3_afternoon.csv`     |
| Daily 3 Night      | `daily3_night.csv`         |
| Play Whe …         | `playwhe_<period>.csv`     |
| Daily Pick 3 …     | `dailypick3_<period>.csv`  |
| Lotto              | `lotto.csv`                |

### Option 2: Web API push (no binding needed)

1. Turn on **Settings → Web Controller** (port 8088).
2. In `config.json`, set each game's `preset_match` to text contained in its
   preset filename. **It must match your real filenames**, e.g. if the file is
   `Dail3 Morning.vmix`, use `"preset_match": "Dail3 Morning"`. Matching ignores
   upper/lower case.
3. If your title field names differ, change `vmix_api.date_field` and
   `vmix_api.draw_field`.

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
