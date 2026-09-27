# Recruitment Data Formatter

Normalizes inconsistent, jumbled-header Excel/CSV exports from your cold-calling
team into one consistent schema, then optionally pushes the result straight
into Zoho CRM.

## What it solves

Every employee's cold-call sheet has the same underlying fields (agent name,
agency, phone, rating, etc.) but different header text, different column
order, and some sheets are missing fields entirely. This tool:

1. Reads every `.xlsx` / `.xls` / `.csv` file in a source folder.
2. Maps each file's headers onto one canonical schema — using an exact alias
   dictionary first, then fuzzy string matching for anything not explicitly
   listed (so "Star Rating", "rating", "agent rating" all resolve to the same
   field, and genuinely unrecognized columns are reported, never guessed).
3. Cleans values per field type (phone numbers, `$419k` / `$1.18M` currency
   shorthand, ratings, postcodes, URLs).
4. Writes the result as clean Excel or CRM-ready JSON.
5. (Zoho mode) Pushes records directly into Zoho CRM via the Bulk Upsert API,
   using email as the de-dup key so re-running the tool never creates
   duplicate CRM records.

## Canonical schema

Defined once in `formatter/config.py`, matching your reference sheet exactly:

`Name, job_title, Years_experience, Agency Name, Email ID of the Agent, suburbs,
Post code, agency_address, phone, rating, properties_sold, median_sold_price,
median_days_advertised, profile_url, agency_url`

**To teach it a new header spelling**, add the lowercase string to the
relevant field's `aliases` tuple in `config.py`. No other code changes needed.

## Install

```bash
pip install -r requirements.txt
```

## Usage

```
python main.py SOURCE_DIR DEST_DIR MODE [options]
```

| Argument | Meaning |
|---|---|
| `SOURCE_DIR` | Folder containing the raw, jumbled employee files |
| `DEST_DIR` | Folder to write converted files into (created if missing) |
| `MODE` | `excel`, `json`, or `zoho` |

Options:
- `--merge` — combine every source file into one output file instead of one output file per input file.
- `--zoho-module NAME` — override the Zoho module to push into (default set in `config.py`, e.g. `Contacts` or a custom `Agents` module).
- `--dry-run` — (zoho mode) normalize and write the JSON audit files but skip the actual API call. Use this to sanity-check before pushing live.

### Examples

```bash
# 1000 messy employee files -> clean per-file Excel sheets
python main.py ./raw_exports ./clean excel

# Same, but one merged Excel file for the whole batch
python main.py ./raw_exports ./clean excel --merge

# CRM-ready JSON (snake_case keys), one merged file
python main.py ./raw_exports ./clean json --merge

# Normalize AND push straight into Zoho CRM
python main.py ./raw_exports ./clean zoho

# Safe rehearsal: normalize + write audit JSON, but don't call Zoho yet
python main.py ./raw_exports ./clean zoho --dry-run
```

Every run writes:
- `logs/formatter.log` — full run log (also printed to console)
- `DEST_DIR/_run_summary.json` — per-file report: rows in/out, which headers matched, which were dropped
- `DEST_DIR/_zoho_push_summary.json` — (zoho mode only) per-record success/failure detail from the CRM API

A single bad or corrupt file **never stops the batch** — it's logged as a
failure and everything else still processes. Exit code is `1` if anything
failed, `0` if everything succeeded, so you can wire this into a scheduled
job and alert on non-zero exit.

## Setting up Zoho CRM push

Zoho CRM API v3 uses OAuth2 with a self-client (server-to-server) flow:

1. Go to the [Zoho API Console](https://api-console.zoho.com) → **Add Client** → **Self Client**.
2. Generate a Client ID and Client Secret.
3. Under the **Generate Code** tab, request scope `ZohoCRM.modules.ALL` (or narrower, e.g. `ZohoCRM.modules.contacts.ALL`), with a long duration, and generate a **grant token**.
4. Exchange that grant token once (curl example below) for a **refresh token** — this is the credential the app actually uses day-to-day; it doesn't expire.

```bash
curl -X POST https://accounts.zoho.in/oauth/v2/token \
  -d "grant_type=authorization_code" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "redirect_uri=YOUR_REDIRECT_URI" \
  -d "code=YOUR_GRANT_TOKEN"
```

5. Copy `.env.example` to `.env`, fill in `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`,
   `ZOHO_REFRESH_TOKEN`, and set the two domain vars to match your Zoho
   datacenter region (India/US/EU/AU — see comments in `.env.example`).
6. Load the env vars before running (`export $(grep -v '^#' .env | xargs)`, or use `python-dotenv`, or your process manager's env file support).

The app auto-refreshes the short-lived access token from the refresh token
on every run — you never touch a token manually again.

**Field mapping to Zoho** lives in `config.py` under each field's `zoho_field`
(e.g. `Name` → `Last_Name`, `phone` → `Phone`). Adjust these to match your
actual Zoho module's field API names (Setup → Customization → Modules →
[Module] → Fields in Zoho CRM shows the API name for each field). If you're
using a **custom module** (e.g. "Agents") instead of the standard Contacts
module, set `ZOHO_MODULE` in `config.py` (or pass `--zoho-module Agents`) and
update the `zoho_field` values to that module's field API names.

De-duplication on push uses `ZOHO_DUPLICATE_CHECK_FIELD` (default: `Email`) —
re-running the tool on the same data updates existing CRM records instead of
creating duplicates.

## Project layout

```
recruitment_formatter/
├── main.py                  # CLI entry point
├── formatter/
│   ├── config.py             # canonical schema, header aliases, Zoho field map
│   ├── header_mapper.py      # exact + fuzzy header matching
│   ├── cleaners.py           # per-field value cleaning (phone/currency/etc.)
│   ├── core.py                # file reading + normalization pipeline
│   ├── writers.py             # excel / json output, Zoho payload builder
│   └── zoho_client.py         # OAuth + bulk upsert with retry/backoff
├── requirements.txt
├── .env.example
└── README.md
```

## Extending

- **New output field**: add a `FieldSpec` to `SCHEMA` in `config.py`.
- **New source header variant**: add the lowercase spelling to that field's `aliases` tuple.
- **Different Zoho module or field names**: update `zoho_field` values and `ZOHO_MODULE`/`ZOHO_DUPLICATE_CHECK_FIELD`.
- **Lower/raise fuzzy-match strictness**: tune `FUZZY_MATCH_THRESHOLD` in `config.py` (0–1; higher = stricter).
