# Realestate.com.au Agent Scraper

Scrapes agent profiles for Australian suburbs from a JSON, text, CSV, or Excel
input list. The scraper processes one unfinished suburb per run by default,
creates a separate workbook for each suburb, and resumes unfinished work when
you run the same command again.

## Setup

Open PowerShell in this folder and install the runtime requirements once:

```powershell
cd C:\Users\ASUS\Desktop\AUSWORK\new\realestate_agent_scraper
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The repository's `aus_postcode.json` has the 2,641-entry Australia suburb list.
If you are using the copy at the parent project folder, pass `..\aus_postcode.json`
as the input path instead.

## Scrape a suburb by postcode

Give the four-digit postcode and the folder where you want the workbook and
resume files saved:

```powershell
python main.py 0800 C:\Users\ASUS\Desktop\scraped_output
```

If the postcode maps to multiple suburbs, the scraper processes those matching
entries and creates one workbook for each. If a run is interrupted, run the
same command again. The scraper restores
profile records from its local journal, rechecks the suburb's paginated results,
and skips profiles already saved.

The required arguments are the four-digit postcode and the output folder you
choose. The JSON input defaults to the Australia postcode file; use `--input`
only to select a different copy. Excel is the default format; `--format json`
is available when needed. `--max-agents` sets a temporary per-suburb test cap,
and `--headless` hides the browser window.

## Files and resume tracking

The output folder contains a separate workbook per suburb, for example
`C:\Users\ASUS\Desktop\scraped_output\darwin_city_0800.xlsx`. The workbook is
refreshed every ten profiles, when a suburb finishes, and on Ctrl+C. A JSONL
journal records each profile as soon as it is scraped so a forced close can
recover it on the next run.

`_scrape_progress.json` tracks each suburb's status, profile count, failures,
and workbook filename. `.checkpoints` contains the per-suburb journals. Completed
suburbs are skipped automatically; interrupted or partially failed suburbs
remain eligible to resume. Suburb and postcode are kept in separate workbook
columns.

The scraper uses a visible Chrome window by default and applies deliberate
delays between profile visits. Check the website's terms before scraping and
avoid running an unnecessarily large batch unattended.
