# Realestate.com.au Agent Scraper

Search by an Australian location or postcode, filter primary agents by job
designation, and optionally include each matching agency's **About the team**
members. Search results are paginated fully. Each location/designation/mode
combination gets its own Excel workbook and resumable progress journal.

## Setup

Open PowerShell in this folder and install the runtime requirements:

```powershell
cd C:\Users\ASUS\Desktop\AUSWORK\new\realestate_agent_scraper
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Configure and run a search

Edit `scraper_settings.json` to set `location`, `designation`, `mode`, and
`output_folder`. It also stores the postcode JSON path, `headless`, and
`max_agents`, and `max_rows` (default 200 data rows per workbook; set it to 0
for unlimited rows). The cap includes team members. Postcode input is entered unchanged so the site's first
suggestion is selected. The JSON supplies a fallback if the website does not
expose a selectable suggestion.

Then the regular command is just:

```powershell
python main.py
```

You can instead pass one-off values positionally without editing the JSON:

```powershell
python main.py "4034" "all" deep-search C:\Users\ASUS\Desktop\scraped_output
```

Arguments are `LOCATION DESIGNATION MODE OUTPUT_FOLDER`. `LOCATION` may be a
four-digit postcode or text entered in the website's location search.
`DESIGNATION` is
compared with each profile's extracted job
title; only titles with at least 85% lexical confidence are included as primary
agents. Use `all` (or `*`) as the designation to include every profile regardless
of title. `area-specific` includes those primary agents. `deep-search` additionally
opens each primary agent's realestate.com.au agency page and extracts the agent
links from its semantic `TeamMembers` section. Team rows are grouped beneath
their primary agent using the `Primary agent` columns.

The last argument is the folder you choose for output. For the first example,
the workbook is saved as:

```text
C:\Users\ASUS\Desktop\scraped_output\4034_all_deep_search.xlsx
```

The workbook is refreshed after every ten saved rows, on completion, and on
Ctrl+C. The same command resumes the same location/designation/mode search.
Different location/designation/mode searches in the same output folder create
different workbooks. `.checkpoints` contains append-only profile journals and
`_scrape_progress.json` records page, profile, failure, and completion counts.

Optional flags: `--input PATH` selects another Australian postcode JSON;
`--headless` runs Chrome invisibly; `--max-agents N` caps primary profiles for
a small trial (omit it for all results). Excel is the output format.

The scraper uses deliberate delays. Check the website's terms and applicable
rules before scraping, and run a small location first to confirm the extracted
title and team data match your use case.
