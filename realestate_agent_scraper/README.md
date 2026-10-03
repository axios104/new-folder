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

## Run a search

```powershell
python main.py "0800" "Sales Agent" area-specific C:\Users\ASUS\Desktop\scraped_output
```

For agency team members as well:

```powershell
python main.py "Darwin City" "Sales Agent" deep-search C:\Users\ASUS\Desktop\scraped_output
```

Arguments are `LOCATION DESIGNATION MODE OUTPUT_FOLDER`. `LOCATION` may be a
four-digit postcode from `aus_postcode.json` or text entered in the website's
location search. Postcodes expand to matching Australian locality names from
the supplied JSON. The scraper selects the first displayed location
recommendation. `DESIGNATION` is compared with each profile's extracted job
title; only titles with at least 85% lexical confidence are included as primary
agents. Use `all` (or `*`) as the designation to include every profile regardless
of title. `area-specific` includes those primary agents. `deep-search` additionally
opens each primary agent's realestate.com.au agency page and extracts the agent
links from its semantic `TeamMembers` section. Team rows are grouped beneath
their primary agent using the `Primary agent` columns.

The last argument is the folder you choose for output. For the first example,
the workbook is saved as:

```text
C:\Users\ASUS\Desktop\scraped_output\darwin_city_northern_territory_0800_sales_agent_area_specific.xlsx
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
