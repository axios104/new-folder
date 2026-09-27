"""
Navigator — the "automation" subtool (nodriver/async version).

Navigates to find-agent pages using direct URLs and collects agent profile
links. Uses nodriver's async API.
"""
from __future__ import annotations
import asyncio
import logging
import random
import re

import nodriver as nd

import config

logger = logging.getLogger("scraper.automation")


async def _human_delay(min_ms: int | None = None, max_ms: int | None = None) -> None:
    lo = min_ms or config.MIN_ACTION_DELAY_MS
    hi = max_ms or config.MAX_ACTION_DELAY_MS
    await asyncio.sleep(random.uniform(lo, hi) / 1000)


def _parse_suburb_string(suburb: str) -> tuple[str, str, str]:
    """
    Parses "Darwin City, Northern Territory 0800" -> ("Darwin City", "nt", "0800")
    """
    parts = suburb.split(",", 1)
    suburb_name = parts[0].strip()
    state_code = ""
    postcode = ""

    if len(parts) > 1:
        rest = parts[1].strip()
        match = re.match(r"^(.+?)\s+(\d{4})$", rest)
        if match:
            state_full = match.group(1).strip()
            postcode = match.group(2)
            state_code = config.STATE_CODE_MAP.get(state_full.lower(), "")
            if not state_code:
                state_code = state_full.lower()
        else:
            state_code = config.STATE_CODE_MAP.get(rest.lower(), rest.lower())

    return suburb_name, state_code, postcode


def _build_find_agent_url(suburb: str) -> str:
    """
    Builds a direct find-agent URL.
    e.g. https://www.realestate.com.au/find-agent/haymarket-nsw-2000/
    """
    suburb_name, state_code, postcode = _parse_suburb_string(suburb)
    slug = suburb_name.lower().replace(" ", "+")

    if state_code and postcode:
        return f"{config.FIND_AGENT_URL}/{slug}-{state_code}-{postcode}/"
    elif state_code:
        return f"{config.FIND_AGENT_URL}/{slug}-{state_code}/"
    else:
        return f"{config.FIND_AGENT_URL}/{slug}/"


async def search_suburb(page: nd.Tab, suburb: str) -> bool:
    """
    Navigates to the find-agent results page for a suburb.
    Returns True if the results page loaded with content.
    """
    try:
        await _human_delay(
            int(config.MIN_PROFILE_DELAY_S * 1000),
            int(config.MAX_PROFILE_DELAY_S * 1000),
        )

        url = _build_find_agent_url(suburb)
        logger.info("Navigating to: %s", url)
        await page.get(url)

        # Wait for page to load with real content
        await _human_delay(3000, 5000)

        # Verify the page has actual content (not just Kasada challenge)
        for attempt in range(10):
            html = await page.get_content()
            if len(html) > 5000:
                logger.info("Page loaded with content for '%s' (%d chars)", suburb, len(html))
                return True
            await asyncio.sleep(2)

        logger.warning(
            "Page still appears to be blocked for '%s' after waiting",
            suburb,
        )
        return False

    except Exception as exc:  # noqa: BLE001
        logger.error("Search failed for suburb '%s': %s", suburb, exc)
        return False


async def collect_agent_profile_urls(page: nd.Tab, suburb: str) -> list[str]:
    """
    From a loaded results page, extracts agent profile URLs from the HTML.
    Uses regex on the page source since nodriver's element query may not
    reliably return href attributes for all links.
    """
    urls: list[str] = []

    try:
        html = await page.get_content()
        # Extract agent profile URLs from the HTML source directly
        # Pattern: href="https://www.realestate.com.au/agent/<name>-<id>"
        matches = re.findall(
            r'href="(https?://www\.realestate\.com\.au/agent/[\w-]+-\d+)"',
            html,
        )
        # De-duplicate while preserving order
        urls = list(dict.fromkeys(matches))

    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to collect agent URLs for '%s': %s", suburb, exc)

    if config.MAX_AGENTS_PER_SUBURB and len(urls) > config.MAX_AGENTS_PER_SUBURB:
        urls = urls[: config.MAX_AGENTS_PER_SUBURB]

    logger.info("Found %d agent profile URL(s) for suburb '%s'", len(urls), suburb)
    return urls
