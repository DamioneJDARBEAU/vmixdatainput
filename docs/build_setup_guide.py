"""Builds docs/vMix_Lotto_Setup_Guide.pdf.  Needs: pip install reportlab"""

import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (KeepTogether, ListFlowable, ListItem, PageBreak,
                                Paragraph, Preformatted, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "vMix_Lotto_Setup_Guide.pdf")

NAVY = colors.HexColor("#1F3A5F")
BLUE = colors.HexColor("#2E6DB4")
LIGHT = colors.HexColor("#EEF3F9")
TIP_BG = colors.HexColor("#EAF6EC")
TIP_LINE = colors.HexColor("#3C8D4F")
WARN_BG = colors.HexColor("#FFF4E0")
WARN_LINE = colors.HexColor("#D98A00")
GREY = colors.HexColor("#5A6270")

ss = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica",
                      fontSize=10.5, leading=15, spaceAfter=6)
SMALL = ParagraphStyle("small", parent=BODY, fontSize=9, leading=12, spaceAfter=0)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=9.5, leading=12.5, spaceAfter=0)
CELL_B = ParagraphStyle("cellb", parent=CELL, fontName="Helvetica-Bold",
                        textColor=colors.white)
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                    fontSize=18, leading=22, textColor=NAVY, spaceBefore=4,
                    spaceAfter=10)
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                    fontSize=13, leading=17, textColor=BLUE, spaceBefore=12,
                    spaceAfter=6)
CODE = ParagraphStyle("code", fontName="Courier", fontSize=8.8, leading=11.5,
                      textColor=colors.HexColor("#1B1F24"))
TITLE = ParagraphStyle("title", parent=H1, fontSize=30, leading=36,
                       alignment=TA_CENTER, spaceAfter=14)
SUB = ParagraphStyle("sub", parent=BODY, fontSize=14, leading=19,
                     alignment=TA_CENTER, textColor=GREY)


def p(text, style=BODY):
    return Paragraph(text, style)


def steps(items):
    return ListFlowable([ListItem(p(t), leftIndent=18, value=i + 1)
                         for i, t in enumerate(items)],
                        bulletType="1", bulletFontName="Helvetica-Bold",
                        bulletFontSize=10.5, leftIndent=18, spaceAfter=6)


def bullets(items):
    return ListFlowable([ListItem(p(t), leftIndent=14) for t in items],
                        bulletType="bullet", start="\u2022", leftIndent=14,
                        spaceAfter=6)


def code(text):
    t = Table([[Preformatted(text.strip("\n"), CODE)]], colWidths=[6.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F4F6")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#C9CDD3")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return KeepTogether([t, Spacer(1, 8)])


def box(label, text, bg, line):
    t = Table([[p("<b>%s</b> %s" % (label, text), CELL)]], colWidths=[6.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 3, line),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return KeepTogether([t, Spacer(1, 8)])


def tip(text):
    return box("Tip:", text, TIP_BG, TIP_LINE)


def warn(text):
    return box("Important:", text, WARN_BG, WARN_LINE)


def table(rows, widths):
    data = [[p(c, CELL_B) for c in rows[0]]]
    data += [[p(c, CELL) for c in r] for r in rows[1:]]
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9CDD3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return KeepTogether([t, Spacer(1, 10)])


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(GREY)
    canvas.drawString(inch, 0.55 * inch, "vMix Lottery Title Data - Setup Guide")
    canvas.drawRightString(letter[0] - inch, 0.55 * inch, "Page %d" % doc.page)
    canvas.setStrokeColor(colors.HexColor("#C9CDD3"))
    canvas.line(inch, 0.72 * inch, letter[0] - inch, 0.72 * inch)
    canvas.restoreState()


SUPABASE_SAMPLE = """
SUPABASE
Project: https://abcdefghijkl.supabase.co
Columns in 'daily_results': id, draw_date, period, play_way_draw_no, ...
Latest rows:
  {"draw_date": "2026-10-03", "period": "mid_morning", "play_way_draw_no": 505, ...
  ...
Draw IDs the feeder would use right now:
  pick3_morning          705
  pick3_midday           706
  ...
  playway_night          508
  lotto                  2101
"""

WEB_SAMPLE = r"""
{ "type": "web",
  "label_regex": "Play\\s*Way\\W{0,20}Night",
  "draw_regex": "Game\\s*#\\s*(\\d+)",
  "window": 400 }
"""

PERIODS = ["Morning", "Midday", "Afternoon", "Night"]
GAMES = [("Pick 3", "pick3"), ("Play Way", "playway"), ("Cash 4", "cash4")]


def story():
    s = []

    # ---------------------------------------------------------------- cover
    s += [Spacer(1, 1.6 * inch),
          p("vMix Lottery Title Data", TITLE),
          p("Automatic date and next draw ID for every game title", SUB),
          Spacer(1, 0.4 * inch)]
    sample = Table([[p("<b>Date</b>", CELL), p("Mon. 9th Sept. 2026", CELL)],
                    [p("<b>DRAW_ID</b>", CELL), p("10452  (last draw number + 1)", CELL)]],
                   colWidths=[1.4 * inch, 3.2 * inch], hAlign="CENTER")
    sample.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, NAVY),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9CDD3")),
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10)]))
    s += [sample, Spacer(1, 0.5 * inch),
          p("Covers: Pick 3, Play Way and Cash 4 (Morning, Midday, Afternoon, "
            "Night) and Lotto. Super 6 is not included.", SUB),
          PageBreak()]

    # ---------------------------------------------------------------- contents
    s += [p("Contents", H1)]
    for line in ["1. How it works", "2. What you need", "3. Install Python",
                 "4. Copy the files to the vMix PC", "5. First test run",
                 "6. Tell the script where to find draw numbers",
                 "7. Prepare the title in vMix",
                 "8. Connect each preset to its data file (Data Source)",
                 "9. Optional: direct push through the vMix Web API",
                 "10. Start automatically with Windows",
                 "11. Daily checklist",
                 "12. Changing things later",
                 "13. Troubleshooting",
                 "Appendix: game keys"]:
        s.append(p(line))
    s.append(PageBreak())

    # ---------------------------------------------------------------- 1
    s += [p("1. How it works", H1),
          p("vMix cannot write ordinal dates such as \"9th\" or \"12th\", and it cannot "
            "look up a draw number and add one to it. A small program, "
            "<b>vmix_lotto_data.py</b>, runs on the vMix computer and does this for "
            "you every 5 minutes."),
          steps([
              "It formats today's date from the PC clock, e.g. <b>Mon. 9th Sept. 2026</b>.",
              "For every game and time period it finds the <b>last</b> draw number - "
              "from the email blast results database in Supabase, the NLA website, or "
              "a manual override - and adds 1.",
              "It writes one small file per game into the <b>output</b> folder, e.g. "
              "<font face='Courier'>output\\pick3_morning.csv</font>.",
              "Each vMix preset reads its own file through a vMix <b>Data Source</b> "
              "and shows the two values in the title.",
              "Optionally it also types the values straight into the title of "
              "whichever preset is open, using the vMix Web API.",
          ]),
          p("Where the draw number comes from (tried in this order, for each game):", H2),
          table([["Order", "Source", "Notes"],
                 ["1", "Manual override", "overrides.json. Only used on the date written in it."],
                 ["2", "Supabase", "daily_results and lotto_results in your email blast "
                  "database."],
                 ["3", "Website", "about.nla.gd today. The address is one line in config.json."],
                 ["4", "Last good value", "Kept in state.json if everything above fails."]],
                [0.6, 1.7, 4.2]),
          tip("Because the program runs every 5 minutes, as soon as a draw result is "
              "published the next draw ID for that game goes up by itself. Nobody has "
              "to type it in."),
          PageBreak()]

    # ---------------------------------------------------------------- 2
    s += [p("2. What you need", H1),
          bullets([
              "The vMix computer (Windows 10 or 11) with vMix installed. Data Sources "
              "work in all vMix editions that support titles; the optional VB.NET "
              "script needs vMix 4K or Pro.",
              "Internet access on the vMix PC (for Supabase and the website).",
              "Access to the Supabase project that holds the email blast results "
              "(to copy its Project URL and API key).",
              "Python 3 (free) - installed in step 3.",
              "This project folder (from GitHub, branch "
              "<font face='Courier'>claude/vmix-title-date-draw-id-omxzaj</font>).",
              "One vMix preset (.vmix file) per game and time period - 13 in total.",
          ]),
          table([["Game", "Also called", "Preset files (one per draw)"],
                 ["Pick 3", "Daily 3, Daily Pick 3",
                  "Morning, Midday, Afternoon, Night"],
                 ["Play Way", "", "Morning, Midday, Afternoon, Night"],
                 ["Cash 4", "Daily Cash 4", "Morning, Midday, Afternoon, Night"],
                 ["Lotto", "", "Lotto"]], [1.2, 1.9, 3.4]),
          p("A preset file can use any of the game's names, e.g. <i>Daily 3 Night.vmix</i>, "
            "<i>Pick 3 Night.vmix</i> or <i>Daily Pick 3 Night.vmix</i> are all "
            "recognised as Pick 3 Night (section 9)."),
          ]

    # ---------------------------------------------------------------- 3
    s += [p("3. Install Python", H1),
          steps([
              "On the vMix PC open <b>https://www.python.org/downloads/</b> and click "
              "<b>Download Python 3.x</b>.",
              "Run the installer. On the first screen tick <b>\"Add python.exe to "
              "PATH\"</b> at the bottom. This is the most important step.",
              "Click <b>Install Now</b> and wait for \"Setup was successful\". Click Close.",
              "Check it: press the Windows key, type <b>cmd</b>, press Enter, then type "
              "<font face='Courier'>py --version</font> and press Enter. You should see "
              "something like <font face='Courier'>Python 3.12.4</font>.",
          ]),
          warn("If the check shows \"not recognized\", run the installer again, choose "
               "<b>Modify</b>, and make sure \"Add Python to environment variables\" "
               "is ticked."),
          PageBreak()]

    # ---------------------------------------------------------------- 4
    s += [p("4. Copy the files to the vMix PC", H1),
          steps([
              "Open the GitHub repository <b>damionejdarbeau/vmixdatainput</b>.",
              "Use the branch selector (top left of the file list) to choose "
              "<font face='Courier'>claude/vmix-title-date-draw-id-omxzaj</font>. "
              "The .bat files are on this branch.",
              "Click the green <b>Code</b> button, then <b>Download ZIP</b>.",
              "Right-click the ZIP and choose <b>Extract All...</b>",
              "Move the extracted folder to <font face='Courier'>C:\\vMixLotto</font> "
              "(any folder works, but this guide uses that one).",
          ]),
          p("The folder should now contain these files:"),
          code("""
C:\\vMixLotto\\
    vmix_lotto_data.py        the program
    config.json               settings (Supabase, website, games)
    supabase_key.txt          your Supabase key (you create it, step 6a)
    overrides.example.json    example for manual draw numbers
    run_once.bat              update once (for testing)
    run_loop.bat              keep updating every 5 minutes
    check_sources.bat         show what Supabase and the website contain
    supabase\\vmix_read_access.sql   only if the key cannot read results
    install_autostart.bat     start automatically at log on
    remove_autostart.bat      undo the automatic start
    vmix_scripts\\SetDateText.vb
    docs\\vMix_Lotto_Setup_Guide.pdf   (this guide)
"""),
          warn("If Windows shows the .bat files as plain \"Windows Batch File\" but "
               "they do nothing, right-click one > <b>Properties</b> and tick "
               "<b>Unblock</b> at the bottom (files downloaded from the internet "
               "are sometimes blocked)."),
          ]

    # ---------------------------------------------------------------- 5
    s += [PageBreak(), p("5. First test run", H1),
          steps([
              "Double-click <b>run_once.bat</b> in C:\\vMixLotto.",
              "A black window opens and prints one line per game, for example:",
          ]),
          code("""
[2026-10-03 09:15:02] Date text: Sat. 3rd Oct. 2026
[2026-10-03 09:15:03]   pick3_morning          next draw 10452    (supabase)
[2026-10-03 09:15:03]   pick3_midday           next draw 10453    (supabase)
...
[2026-10-03 09:15:04]   lotto                  next draw 2101     (web)
[2026-10-03 09:15:04] vMix: pushed playway_night into 'LottoTitle' (preset ...)
"""),
          steps([
              "A new folder <b>C:\\vMixLotto\\output</b> now holds 13 game files plus "
              "<b>all_games.csv</b>. Open all_games.csv in Excel or Notepad to check "
              "every value at once. Press any key to close the window.",
          ]),
          p("The word in brackets shows where each number came from: <b>supabase</b>, "
            "<b>web</b>, <b>override</b>, <b>cached</b> (last good value) or <b>none</b> "
            "(nothing found yet - DRAW_ID will be blank). Before you finish section 6, "
            "\"none\" and Supabase/website error lines are normal."),
          PageBreak()]

    # ---------------------------------------------------------------- 6
    s += [p("6. Tell the script where to find draw numbers", H1),
          p("All settings are in <b>config.json</b>. Open it with Notepad (right-click > "
            "Open with > Notepad). Keep the quotes and commas exactly as they are; a "
            "missing comma stops the program from starting."),
          p("6a. Supabase - the email blast results (main source)", H2),
          p("config.json is already set up for your results database: "
            "<b>daily_results</b> for the daily games and <b>lotto_results</b> for "
            "Lotto. You only need to give it the project address and a key."),
          p("<b>Step 1 - copy the project address and key.</b>"),
          steps([
              "Log in at <b>https://supabase.com/dashboard</b> and open the project "
              "that holds the results.",
              "Click <b>Project Settings</b> (the cog, bottom left), then <b>API</b> "
              "(in newer dashboards: <b>Data API</b> for the URL and <b>API Keys</b> for "
              "the key).",
              "Copy the <b>Project URL</b> (looks like "
              "<font face='Courier'>https://abcdefghijkl.supabase.co</font>). In "
              "config.json replace <font face='Courier'>https://YOUR-PROJECT-ID.supabase.co"
              "</font> with it.",
              "Copy the <b>anon / public</b> key (newer dashboards call it the "
              "<b>publishable</b> key).",
              "In C:\\vMixLotto create a new text file called <b>supabase_key.txt</b>, "
              "paste the key into it (nothing else) and save.",
          ]),
          warn("Use the <b>anon / publishable</b> key, not the <b>service_role / secret</b> "
               "key. The secret key can change or delete everything in the database "
               "(staff, recipients, blasts) and must not be stored on the vMix PC. "
               "Keep supabase_key.txt out of emails and GitHub."),
          tip("In File Explorer turn on <b>View &gt; File name extensions</b> so Notepad "
              "does not save the file as supabase_key.txt.txt."),
          p("<b>Step 2 - check it.</b> Double-click <b>check_sources.bat</b>. Under "
            "SUPABASE it shows the latest rows of daily_results and lotto_results, then "
            "the draw ID every preset would get right now:"),
          code(SUPABASE_SAMPLE),
          p("Compare a few of these with your own records. If they are right, the "
            "Supabase part is done."),
          warn("If it says a table <b>returned no rows</b> but the table has data, the "
               "public key is not allowed to read it. Open "
               "<b>supabase\\vmix_read_access.sql</b> from the folder, paste it into the "
               "Supabase <b>SQL Editor</b> and click Run. It allows reading "
               "<b>published</b> results only - results waiting for approval stay "
               "hidden, and nothing can be changed with the key."),
          p("How the draw ID is worked out", H2),
          table([["vMix preset", "Supabase column", "Period"],
                 ["Pick 3 / Daily 3 / Daily Pick 3 ...", "daily_results.pick3_draw_no", ""],
                 ["Play Way ...", "daily_results.play_way_draw_no", ""],
                 ["Cash 4 / Daily Cash 4 ...", "daily_results.cash4_draw_no", ""],
                 ["... Morning", "", "mid_morning"],
                 ["... Midday", "", "midday"],
                 ["... Afternoon", "", "mid_afternoon"],
                 ["... Night", "", "evening"],
                 ["Lotto", "lotto_results.draw_no", "(one draw per date)"]],
                [2.0, 2.6, 1.9]),
          p("Draw numbers run in one sequence through the day (mid-morning, midday, "
            "mid-afternoon, evening, then the next day). So for each preset the "
            "program:"),
          steps([
              "uses <b>today's row for that period</b> if it already has a draw number;",
              "otherwise takes the <b>latest draw number</b> in the table and counts "
              "forward one per draw slot to today's period. Example: yesterday's "
              "evening Play Way was 504, so today is mid-morning 505, midday 506, "
              "mid-afternoon 507, evening 508.",
          ]),
          p("Lotto works the same way with one draw per date: the latest draw_no plus "
            "1, or today's row if it is already there."),
          tip("On a disrupted or cancelled day the count can be off. Use a manual "
              "override (6c) for that day."),
          PageBreak(),
          p("6b. The website (backup source)", H2),
          p("The website address is near the top of config.json:"),
          code('"website_url": "https://about.nla.gd/",'),
          p("When the address changes in future, change only this line and save."),
          p("Each game has a <b>label_regex</b> - the game name as it appears on the "
            "website. The program finds that name and reads the first "
            "<i>Draw ... number</i> that follows it. The WEBSITE part of "
            "<b>check_sources.bat</b> lists every draw number found on the page with "
            "the text around it (also saved to <b>check_result.txt</b>)."),
          bullets([
              "If the page says <font face='Courier'>PLAY WAY - NIGHT ... Draw No: "
              "3512</font>, the default <font face='Courier'>Play\\\\s*Way\\\\W{0,20}"
              "Night</font> already matches it.",
              "If the page uses another word for the number, e.g. <i>Game #3512</i>, "
              "add a draw_regex line to that game's web source:",
          ]),
          code(WEB_SAMPLE),
          tip("To make the website the <b>main</b> source instead of Supabase, move "
              "its block above the supabase block inside that game's \"sources\" list."),
          p("6c. Manual override (when you need to type a number in)", H2),
          steps([
              "Copy <b>overrides.example.json</b> and rename the copy to "
              "<b>overrides.json</b>.",
              "Edit it so it lists only the games you want to force, with today's date "
              "and the draw ID to show:",
          ]),
          code('''
{
  "playway_night": { "date": "2026-10-03", "next_draw": 3513 }
}
'''),
          p("The override only applies on that date, so a forgotten override cannot "
            "show a wrong number tomorrow. The game names (keys) are listed in the "
            "Appendix."),
          PageBreak()]

    # ---------------------------------------------------------------- 7
    s += [p("7. Prepare the title in vMix", H1),
          p("Your title already has the two fields <b>Date.Text</b> and "
            "<b>DRAW_ID.Text</b>; the program is set up for exactly these names."),
          steps([
              "In vMix open the title input's <b>Title Editor</b> and confirm the field "
              "list shows <b>Date.Text</b> and <b>DRAW_ID.Text</b>.",
              "Right-click the title input > <b>Input Settings</b> > General, and set "
              "its name (title) to <b>LottoTitle</b>. Use this same name in every preset.",
              "Save the preset.",
          ]),
          warn("Field names must match exactly, including capitals and the underscore: "
               "<b>DRAW_ID.Text</b>, not Draw_ID.Text or DRAW ID.Text. If a title uses "
               "different names, change \"date_field\" and \"draw_field\" in the "
               "\"vmix_api\" part of config.json."),
          ]

    # ---------------------------------------------------------------- 8
    s += [p("8. Connect each preset to its data file", H1),
          p("Repeat these steps in each of the 13 presets. Run <b>run_once.bat</b> "
            "first so the files exist."),
          steps([
              "Open the preset, e.g. <b>Pick 3 Morning.vmix</b>.",
              "Open the <b>Data Sources Manager</b>. Depending on your vMix version this "
              "is the <b>Data Sources</b> button at the bottom of the main window, or "
              "under <b>Settings</b>.",
              "Click <b>Add</b>, choose <b>Excel/CSV</b>, and browse to the file for this "
              "preset (table below), e.g. "
              "<font face='Courier'>C:\\vMixLotto\\output\\pick3_morning.csv</font>. "
              "Click OK.",
              "In the Data Sources Manager, turn on <b>Auto Refresh</b> and set it to "
              "<b>10</b> seconds. Make sure the first row is used as the header "
              "(column names <b>Date</b> and <b>DRAW_ID</b> should appear).",
              "Open the title's <b>Title Editor</b> (click the cog on the title input, "
              "or right-click > Title Editor) and click <b>Data Source</b>.",
              "For <b>Date.Text</b> choose this data source and column <b>Date</b>. "
              "For <b>DRAW_ID.Text</b> choose column <b>DRAW_ID</b>. Close the window.",
              "Check the preview: the date and draw ID should appear in the title.",
              "<b>Save the preset</b> (File/Save). The link is stored inside the .vmix "
              "file, so you never have to do this again for that preset.",
          ]),
          warn("Each preset must point at <b>its own</b> file. A Night preset pointing "
               "at the Morning file will show the Morning draw ID."),
          ]
    rows = [["Preset", "Data file in C:\\vMixLotto\\output"]]
    for name, key in GAMES:
        for per in PERIODS:
            rows.append(["%s %s" % (name, per), "%s_%s.csv" % (key, per.lower())])
    rows.append(["Lotto", "lotto.csv"])
    s += [table(rows, [2.6, 3.9]),
          p("Each file has a header row and one data row, for example:"),
          code("Game,Date,DRAW_ID\nPlay Way Night,Sat. 3rd Oct. 2026,3513"),
          PageBreak()]

    # ---------------------------------------------------------------- 9
    s += [p("9. Optional: direct push through the vMix Web API", H1),
          p("This sends the values straight into the open preset's title, as well as "
            "writing the files. Use it if you prefer not to set up Data Sources, or as "
            "a second safety net. Both can be used together."),
          steps([
              "In vMix open <b>Settings > Web Controller</b>, tick <b>Enable</b>, "
              "keep port <b>8088</b>, and click OK.",
              "In config.json check that <font face='Courier'>\"vmix_api\"</font> has "
              "<font face='Courier'>\"enabled\": true</font> and "
              "<font face='Courier'>\"title_input\": \"LottoTitle\"</font>.",
              "Each game has a <b>preset_match</b> list of the names its preset file "
              "may have. Pick 3 Night, for example, accepts <i>Daily Pick 3 Night</i>, "
              "<i>Pick 3 Night</i> and <i>Daily 3 Night</i>; Cash 4 Night accepts "
              "<i>Daily Cash 4 Night</i> and <i>Cash 4 Night</i>. Upper/lower case, "
              "spaces and dashes are ignored. If a file has another name (e.g. "
              "<i>Dail3 Morning.vmix</i>), add it to that game's list: "
              "<font face='Courier'>\"preset_match\": [\"Daily Pick 3 Morning\", "
              "\"Pick 3 Morning\", \"Daily 3 Morning\", \"Dail3 Morning\"]</font>.",
              "Open a preset, run <b>run_once.bat</b>, and look for the line "
              "<font face='Courier'>vMix: pushed ... into 'LottoTitle'</font>.",
          ]),
          warn("The program picks the first game whose preset_match is found in the "
               "file name. Keep the names specific, e.g. \"Pick 3 Night\" and "
               "\"Cash 4 Night\", not just \"Night\"."),
          tip("The output files (section 8) keep one name per game - pick3_..., "
              "playway_..., cash4_... - whatever the preset file is called."),
          ]

    # ---------------------------------------------------------------- 10
    s += [p("10. Start automatically with Windows", H1),
          steps([
              "Right-click <b>install_autostart.bat</b> and choose <b>Run as "
              "administrator</b>. Click Yes.",
              "You should see \"Done. The feeder will start each time you log on.\"",
              "To start it now without logging off, double-click <b>run_loop.bat</b>.",
          ]),
          p("A window titled <b>vMix Lotto Data Feeder</b> stays open and prints an "
            "update every 5 minutes. Minimise it, but do not close it. If the program "
            "stops for any reason, the window restarts it after 30 seconds."),
          p("To stop the automatic start, right-click <b>remove_autostart.bat</b> > "
            "Run as administrator."),
          tip("To update more or less often, edit run_loop.bat and change "
              "<font face='Courier'>--loop 300</font> (seconds)."),
          PageBreak()]

    # ---------------------------------------------------------------- 11
    s += [p("11. Daily checklist", H1),
          bullets([
              "The <b>vMix Lotto Data Feeder</b> window is open on the vMix PC.",
              "Its latest lines show a draw number and <b>(supabase)</b> or "
              "<b>(web)</b> for each game - not <b>(none)</b> or <b>(cached)</b> for hours.",
              "The PC clock and date are correct (the date text comes from it).",
              "Before going on air, check the title preview: correct date and a draw "
              "ID one higher than the last published result.",
              "If a number is wrong, use an override (6c) and wait up to 5 minutes, or "
              "run run_once.bat to update immediately.",
          ]),
          ]

    # ---------------------------------------------------------------- 12
    s += [p("12. Changing things later", H1),
          table([["To change...", "Edit", "Example"],
                 ["Website address", "config.json: website_url",
                  "\"https://results.nla.gd/\""],
                 ["Month spelling", "config.json: month_names",
                  "\"Sep.\" instead of \"Sept.\""],
                 ["Day spelling", "config.json: day_names", "\"Mon\" without the dot"],
                 ["Date layout", "config.json: pattern",
                  "\"{day} {date} {month}, {year}\" gives Mon. 9th Sept., 2026"],
                 ["Draw ID look", "config.json: add \"draw_format\" to a game",
                  "\"Draw #{0}\" or \"{0:06d}\" (leading zeros)"],
                 ["Add / rename a game", "config.json: copy a game block, change the key, "
                  "name, preset_match and sources", "Run run_once.bat to create its file"],
                 ["Update interval", "run_loop.bat: --loop 300", "--loop 120 = 2 minutes"]],
                [1.5, 2.4, 2.6]),
          p("The running program reloads config.json automatically on its next "
            "update, so there is no need to restart it after saving."),
          ]

    # ---------------------------------------------------------------- 13
    s += [PageBreak(), p("13. Troubleshooting", H1),
          table([["Problem", "Fix"],
                 ["\"Python was not found\"", "Repeat step 3 and tick \"Add python.exe to PATH\"."],
                 ["Window opens and closes at once",
                  "Run run_once.bat - it stays open and shows the error."],
                 ["\"Config file not found\" or a JSON error",
                  "A quote or comma is missing in config.json. Open it at "
                  "jsonlint.com to find the line."],
                 ["DRAW_ID is blank, source (none)",
                  "No source returned a number. Run check_sources.bat (6a). Use an "
                  "override (6c) meanwhile."],
                 ["\"Supabase url/key not set\"",
                  "Put the Project URL in config.json and the key in supabase_key.txt (6a)."],
                 ["\"Supabase HTTP 401\" / Invalid API key",
                  "The key in supabase_key.txt is wrong or has extra text. Copy it again."],
                 ["\"Supabase HTTP 404\" / relation does not exist",
                  "A table was renamed in the database. Update \"table\" in config.json."],
                 ["\"Supabase HTTP 400\" / column does not exist",
                  "A column was renamed. Update \"draw_column\" in config.json."],
                 ["Supabase table returns no rows",
                  "Run supabase\\vmix_read_access.sql in the SQL Editor (6a)."],
                 ["Draw ID is one or more off",
                  "A draw was skipped, cancelled or entered late. Use an override (6c)."],
                 ["\"web source failed: urlopen error\"",
                  "The website cannot be reached. Check internet access or the address "
                  "in website_url. Supabase is still used first."],
                 ["\"... lower than previous ... ignored\"",
                  "A source returned an older number. Normally harmless; check the "
                  "source if it keeps happening."],
                 ["Title does not change in vMix",
                  "Check Auto Refresh is on and the field is bound to the right column "
                  "(section 8). Open the CSV in Notepad to confirm it has the value."],
                 ["\"vMix: could not set 'Date.Text'...\"",
                  "The title input is not named LottoTitle or the field name differs "
                  "(section 7). The CSV files are still updated."],
                 ["\"vMix API not reachable\"",
                  "Only matters for section 9. Enable Settings > Web Controller."],
                 ["\"no game matches loaded preset\"",
                  "Fix preset_match so it is part of the preset's file name (section 9)."],
                 ["Wrong date", "Fix the Windows clock/time zone on the vMix PC."]],
                [2.2, 4.3]),
          PageBreak()]

    # ---------------------------------------------------------------- appendix
    s += [p("Appendix: game keys", H1),
          p("These names are used for the output files, overrides.json and "
            "config.json."),
          ]
    rows = [["Key", "Recognised preset names", "Supabase column", "period"]]
    aliases = {"pick3": "Pick 3 / Daily 3 / Daily Pick 3", "playway": "Play Way",
               "cash4": "Cash 4 / Daily Cash 4"}
    cols = {"pick3": "pick3_draw_no", "playway": "play_way_draw_no",
            "cash4": "cash4_draw_no"}
    dbp = {"Morning": "mid_morning", "Midday": "midday",
           "Afternoon": "mid_afternoon", "Night": "evening"}
    for name, key in GAMES:
        for per in PERIODS:
            rows.append(["%s_%s" % (key, per.lower()), "%s %s" % (aliases[key], per),
                         cols[key], dbp[per]])
    rows.append(["lotto", "Lotto", "lotto_results.draw_no", "-"])
    s += [table(rows, [1.4, 2.3, 1.6, 1.2]),
          p("Date-only fallback without Python", H2),
          p("<b>vmix_scripts\\SetDateText.vb</b> sets only the date field from inside "
            "vMix (no draw ID). In vMix 4K/Pro: Settings > Scripting > Add, paste the "
            "file's contents, name it SetDateText, and start it from a shortcut or "
            "trigger. Use it only if the Python feeder cannot run.")]
    return s


def main():
    doc = SimpleDocTemplate(OUT, pagesize=letter, leftMargin=inch, rightMargin=inch,
                            topMargin=0.85 * inch, bottomMargin=0.95 * inch,
                            title="vMix Lottery Title Data - Setup Guide",
                            author="vmixdatainput")
    doc.build(story(), onFirstPage=lambda c, d: None, onLaterPages=footer)
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
