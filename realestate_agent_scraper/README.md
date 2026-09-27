# Realestate.com.au Agent Scraper

Two interconnected subtools that turn a list of suburbs into agent contact
records, in the exact same format your `recruitment_formatter` tool produces:

- **`automation/`** — drives the browser: goes to the search page, types the
  suburb, clicks the right autocomplete suggestion, opens the results list,
  and clicks through to each agent's profile page (this is the click-path
  you described — the "endpoint" is reaching the profile page where contact
  info lives).
- **`scraper/`** — once a profile page is open, reads every field off it
  (name, job title, agency, phone, rating, properties sold, etc.).

`pipeline.py` connects the two and writes output using the **same schema
and writer code** as `recruitment_formatter` (imported directly, not
copied), so scraped data and manually-collected data always end up in one
consistent format, ready for the same destination folder / Zoho push.

## ⚠️ Before you run this at volume

realestate.com.au runs **Kasada bot-detection**, an active anti-automation
service. This tool applies standard, legitimate mitigations (headful
browser, real user-agent, randomized human-like delays — see `config.py`),
but no tool can honestly guarantee it won't get blocked or rate-limited.
Please also check realestate.com.au's Terms of Service regarding automated
access before running this against their site at scale. Go slow, especially
at first.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

**Required folder layout** — this tool imports `recruitment_formatter`'s
schema/writers directly, so the two projects must sit side by side:

```
Desktop/
├── recruitment_formatter/
└── realestate_agent_scraper/
```

## Getting real selectors (important — do this before a real run)

The extraction is built to work two ways:
1. **Text-pattern matching** (regex, in `config.py` → `TEXT_PATTERNS`) —
   already filled in and works out of the box for phone numbers, ratings,
   "properties sold", median price/days — no setup needed. This is the
   primary strategy because sites like this often use auto-generated CSS
   class names that change on every deploy, making hardcoded selectors
   fragile.
2. **Exact selectors** (`config.py` → `SELECTORS`) — currently all `None`.
   Filling these in makes the click-path (search box, autocomplete,
   pagination) actually work, since there's no reliable text-pattern
   fallback for "which element do I click."

**To fill in `SELECTORS`:** open the live site in Chrome, right-click the
element → Inspect → right-click the highlighted HTML in DevTools → Copy →
Copy selector (or outerHTML for me to turn into a selector). Prefer
`[data-testid="..."]` attributes over class names if you see them — they're
far more stable. Paste what you find for each `SELECTORS` key and I'll wire
it in, or edit `config.py` yourself; every key has a comment showing the
expected format.

Until `SELECTORS["agent_result_card"]` is filled in, the results-page
collector falls back to a generic scan for any link containing `/agent/` —
functional but less precise than a real selector.

## Usage

```bash
# suburbs.txt: one suburb per line
python main.py suburbs.txt ./scraped_output excel

# or from an Excel/CSV column named "suburb"
python main.py suburbs.xlsx ./scraped_output json

# headless (faster, but more easily fingerprinted — off by default)
python main.py suburbs.txt ./scraped_output excel --headless
```

Output:
- `scraped_output/scraped_agents.xlsx` (or `.json`) — all scraped records,
  same columns/keys as `recruitment_formatter`'s output.
- `scraped_output/_scrape_report.json` — per-suburb count of profiles found
  and records scraped, plus any errors (same auditability pattern as the
  formatter tool's `_run_summary.json`).
- `logs/scraper.log` — full run log.

## Feeding scraped output into the rest of your pipeline

Because the output uses the identical schema, you can drop
`scraped_agents.xlsx` straight into `recruitment_formatter`'s destination
folder alongside employee-collected files, or run it directly through
`recruitment_formatter`'s `zoho` mode:

```bash
cd ../recruitment_formatter
python main.py ../realestate_agent_scraper/scraped_output ./clean zoho
```

## Tuning

- `config.MIN_ACTION_DELAY_MS` / `MAX_ACTION_DELAY_MS` — pacing between
  clicks/typing. Don't lower these casually.
- `config.MIN_PROFILE_DELAY_S` / `MAX_PROFILE_DELAY_S` — pause between
  visiting agent profiles.
- `config.MAX_AGENTS_PER_SUBURB` — cap per suburb (`None` = no cap).
- `config.MAX_RESULT_PAGES` — how many result pages to page through per
  suburb.

## Project layout

```
realestate_agent_scraper/
├── main.py                  # CLI entry point
├── config.py                # URLs, SELECTORS, TEXT_PATTERNS, timing
├── suburb_loader.py         # reads suburbs.txt / .xlsx / .csv
├── pipeline.py               # connects automation + scraper, writes output
├── automation/
│   ├── browser.py            # Playwright session w/ anti-detection settings
│   └── navigator.py          # search -> click through -> profile URLs
├── scraper/
│   └── extractor.py          # reads fields off a loaded profile page
└── requirements.txt
```
