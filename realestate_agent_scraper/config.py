"""
Everything specific to "how realestate.com.au's pages are structured" lives
here. Two extraction strategies are supported, tried in this order:

  1. SELECTORS  — exact CSS/data-testid selectors. Fill these in once you've
     inspected the live DOM (see README "Getting real selectors"). Fast and
     precise when present.
  2. TEXT_PATTERNS — regex run against the page's plain visible text. Works
     even when class names are hashed/auto-generated and change on every
     deploy (very common on large React/Next sites), which is why this is
     the primary strategy until real selectors are confirmed.

Nothing else in the codebase needs to change when you update either of
these — extractor.py just consumes whichever produces a value.
"""
from __future__ import annotations
import re

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
BASE_URL = "https://www.realestate.com.au"
FIND_AGENT_URL = f"{BASE_URL}/find-agent"

# ---------------------------------------------------------------------------
# STATE_CODE_MAP — maps full state names to the lowercase abbreviation
# ---------------------------------------------------------------------------
STATE_CODE_MAP = {
    "new south wales": "nsw",
    "victoria": "vic",
    "queensland": "qld",
    "south australia": "sa",
    "western australia": "wa",
    "tasmania": "tas",
    "northern territory": "nt",
    "australian capital territory": "act",
}

# ---------------------------------------------------------------------------
# SELECTORS — fill in once confirmed against the live site (see README).
# Leave a value as None to skip straight to the text-pattern fallback for
# that field. Prefer `data-testid` attributes over CSS classes: testids are
# put there deliberately for automated testing and survive redesigns far
# better than hashed utility-class names.
# ---------------------------------------------------------------------------
SELECTORS = {
    # --- search / find-agent flow ---
    # Clicking this opens a search dialog/modal (confirmed from real HTML:
    # it's a <button aria-haspopup="dialog">, not a text input itself).
    "search_open_button": 'button.search-button[aria-haspopup="dialog"]',
    "suburb_search_input": None,       # TODO: the actual <input> INSIDE the dialog once opened
    "suburb_autocomplete_item": None,  # TODO: a suburb suggestion item (not a property card)
    "search_submit_button": None,      # if Enter key doesn't trigger it

    # --- results/listing page ---
    "agent_result_card": None,         # e.g. '[data-testid="agent-card"]'
    "agent_profile_link": None,        # anchor within the card, if not the card itself
    "pagination_next_button": None,    # e.g. '[data-testid="pagination-next"]'
    "load_more_button": None,          # if "load more" style instead of numbered pages

    # --- agent profile page ---
    "agent_name": None,
    "job_title": None,
    "agency_name": None,
    "agency_address": None,
    "phone_number": None,
    # Confirmed from real HTML: matched by visible text rather than its
    # class name, since styled-components hashes (e.g. "sc-etylg7-1")
    # regenerate on every deploy and would break silently.
    "reveal_phone_button": 'text="Call"',
    "rating": None,
    "properties_sold": None,
    "median_sold_price": None,
    "median_days_advertised": None,
    "agency_url": None,
}

# ---------------------------------------------------------------------------
# TEXT_PATTERNS — regex fallback, run against page.inner_text("body").
# Each pattern's first capture group is the extracted value.
# ---------------------------------------------------------------------------
TEXT_PATTERNS = {
    "phone_number": re.compile(
        r"(?:tel:)?("
        r"04\d{2}[\s-]?\d{3}[\s-]?\d{3}"        # mobile: 04XX XXX XXX
        r"|\(?0[2-478]\)?[\s-]?\d{4}[\s-]?\d{4}"  # landline: 0X XXXX XXXX
        r"|\+?61[\s-]?4?\d{2}[\s-]?\d{3}[\s-]?\d{3}"  # +61 formatted
        r"|0\d{9}"                               # no-space fallback
        r")"
    ),
    "rating": re.compile(
        r"([0-5](?:\.\d)?)\s*(?:out of 5|/\s*5|stars?)\b", re.IGNORECASE
    ),
    "properties_sold": re.compile(
        r"([\d,]+)\s*(?:properties\s*)?sold\b", re.IGNORECASE
    ),
    "median_sold_price": re.compile(
        r"median\s*(?:sold|sale)\s*price[:\s]*\$?\s*([\d.,]+\s*[kKmM]?)",
        re.IGNORECASE,
    ),
    "median_days_advertised": re.compile(
        r"median\s*days?\s*advertised[:\s]*(\d+)", re.IGNORECASE
    ),
}

# ---------------------------------------------------------------------------
# TIMING — deliberately conservative/human-like. Do not lower these without
# a good reason; realestate.com.au runs active bot-detection (Kasada), and
# fast, uniform request timing is one of the easiest ways to get flagged.
# ---------------------------------------------------------------------------\
MIN_ACTION_DELAY_MS = 800
MAX_ACTION_DELAY_MS = 2200
MIN_PROFILE_DELAY_S = 3.0
MAX_PROFILE_DELAY_S = 7.0
NAVIGATION_TIMEOUT_MS = 30_000

# Max agent profiles to visit per suburb (safety cap; None = no limit)
MAX_AGENTS_PER_SUBURB = None

# Max pages of results to page through per suburb
MAX_RESULT_PAGES = 5