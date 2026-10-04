"""
Navigator — the "automation" subtool (nodriver/async version).

Navigates to find-agent pages using direct URLs and collects agent profile
links across every pagination page for a suburb.
"""
from __future__ import annotations
import asyncio
import json
import logging
import random
import re
from collections.abc import Callable

import nodriver as nd

import config
from scraper.pagination import (
    build_page_url,
    extract_agent_profile_urls,
    parse_pagination,
)

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
    else:
        pc = re.search(r"\b(\d{4})\b", suburb)
        if pc:
            postcode = pc.group(1)

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


async def _page_ready(page: nd.Tab, suburb: str, attempts: int = 10) -> bool:
    for _ in range(attempts):
        html = await page.get_content()
        if html and len(html) > 5000:
            logger.info("Page loaded with content for '%s' (%d chars)", suburb, len(html))
            return True
        await asyncio.sleep(2)
    return False


def _normalise_suggestion_label(label: str) -> str:
    """Normalize a displayed label such as ``Aspley QLD 4034``."""
    value = re.sub(r"\s*\n\s*", ", ", (label or "")).strip()
    return re.sub(
        r"\s+(NSW|VIC|QLD|SA|WA|TAS|NT|ACT)\s+(\d{4})$",
        r", \1 \2",
        value,
        flags=re.IGNORECASE,
    )


def _suggestion_matches_location(label: str, location: str) -> bool:
    """Accept a location recommendation, never a profile or agency result."""
    candidate = _normalise_suggestion_label(label).casefold()
    query = _normalise_suggestion_label(location).casefold()
    postcode = re.search(r"\b(\d{4})\b", query)
    state = re.search(r"\b(nsw|vic|qld|sa|wa|tas|nt|act)\b", query)
    if postcode and postcode.group(1) not in candidate:
        return False
    if state and state.group(1) not in candidate:
        return False
    if not re.search(r"\b(?:nsw|vic|qld|sa|wa|tas|nt|act)\b\s+\d{4}\b", candidate):
        return False
    query_words = [word for word in re.findall(r"[a-z]+", query) if word not in {
        "nsw", "vic", "qld", "sa", "wa", "tas", "nt", "act"
    }]
    return not query_words or all(word in candidate for word in query_words)


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
        await _human_delay(3000, 5000)

        if await _page_ready(page, suburb):
            return True

        logger.warning("Page still appears to be blocked for '%s' after waiting", suburb)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("Search failed for suburb '%s': %s", suburb, exc)
        return False


async def search_location(page: nd.Tab, location: str) -> str | None:
    """Search the find-agent page and choose the first location suggestion.

    Uses accessible input metadata and suggestion roles instead of hashed CSS
    selectors so minor visual redesigns are less likely to break the flow.
    """
    try:
        await page.get(config.FIND_AGENT_URL)
        if not await _page_ready(page, "find-agent location search", attempts=8):
            logger.warning("Find-agent search page did not load before searching %r", location)
            return False
        await _human_delay(1000, 1800)
        query = json.dumps(location)
        opened = await page.evaluate(f"""(() => {{
          const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
          const button = [...document.querySelectorAll('button,[role="button"]')].find(el =>
            visible(el) && (/search|location|area/i.test((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')) ||
              el.querySelector('svg[class*="SearchIcon"],svg[class*="Search"]')));
          if (button) button.click();
          return !!button;
        }})()""")
        await _human_delay(500, 900)
        filled = await page.evaluate(f"""(() => {{
          const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
          const inputs = [...document.querySelectorAll('input:not([type=hidden]), [role=combobox]')].filter(visible);
          const input = inputs.find(el => /location|suburb|area|where|search/i.test(
            (el.getAttribute('placeholder') || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('name') || '')
          )) || inputs[0];
          if (!input) return false;
          const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
          if (setter && input instanceof HTMLInputElement) setter.call(input, {query});
          else input.textContent = {query};
          input.dispatchEvent(new Event('input', {{bubbles:true}}));
          input.dispatchEvent(new Event('change', {{bubbles:true}}));
          return true;
        }})()""")
        if not filled:
            logger.warning("Could not find a visible location search input for %r (search opened=%s)", location, opened)
            return False
        selected_location = ""
        selection_query = json.dumps(location)
        for _ in range(8):
            selected_location = await page.evaluate(f"""(() => {{
          const visible = el => !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
          const query = {selection_query}.toLowerCase();
          const expectedPostcode = (query.match(/\\b\\d{{4}}\\b/) || [])[0] || '';
          const expectedState = (query.match(/\\b(?:nsw|vic|qld|sa|wa|tas|nt|act)\\b/) || [])[0] || '';
          const expectedWords = (query.match(/[a-z]+/g) || []).filter(word => !['nsw','vic','qld','sa','wa','tas','nt','act'].includes(word));
          const options = [...document.querySelectorAll('[role="option"], [role="listbox"] a, [role="listbox"] button, [role="listbox"] li, [class*="suggest" i] a, [class*="suggest" i] button, [class*="suggest" i] li')]
            .filter(el => visible(el) && (el.innerText || '').trim() && !el.closest('header'));
          const first = options.find(el => {{
            const label = (el.innerText || '').replace(/\\s*\\n\\s*/g, ', ').trim().toLowerCase();
            return /\\b(?:nsw|vic|qld|sa|wa|tas|nt|act)\\b\\s+\\d{{4}}\\b/.test(label)
              && (!expectedPostcode || label.includes(expectedPostcode))
              && (!expectedState || label.includes(expectedState))
              && expectedWords.every(word => label.includes(word));
          }});
          if (first) {{ const label = (first.innerText || '').replace(/\\s*\\n\\s*/g, ', ').trim(); first.click(); return label; }}
          return '';
        }})()""")
            if isinstance(selected_location, str) and selected_location.strip():
                selected_location = _normalise_suggestion_label(selected_location)
                break
            await _human_delay(400, 650)
        if not selected_location:
            logger.warning("No matching location recommendation appeared for %r", location)
            return None
        await _human_delay(1800, 2800)
        if not await _page_ready(page, location, attempts=8):
            return None
        return selected_location
    except Exception as exc:  # noqa: BLE001
        logger.error("Location search failed for %r: %s", location, exc)
        return False

def _max_pages() -> int | None:
    """Return an explicit operator cap, or None to follow site pagination."""
    configured = config.MAX_RESULT_PAGES
    return int(configured) if configured not in (None, 0) else None


async def collect_agent_profile_urls(
    page: nd.Tab,
    suburb: str,
    on_page: Callable[[int], None] | None = None,
) -> list[str]:
    """
    From a loaded results page, walk every pagination page and collect unique
    agent profile URLs. Does not assume page 1 contains the full result set.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    visited_page_urls: set[str] = set()
    page_number = 1
    reported_total: int | None = None
    expected_pages = 1
    max_pages = _max_pages()

    async def _add_from_html(html: str, label: str) -> int:
        found = extract_agent_profile_urls(html)
        added = 0
        for url in found:
            key = url.rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(url)
            added += 1
        logger.info(
            "Page %s for '%s': %d profile link(s) on page, %d new, %d unique so far",
            label,
            suburb,
            len(found),
            added,
            len(ordered),
        )
        return added

    try:
        html = await page.get_content()
        current_url = ""
        try:
            current_url = await page.evaluate("location.href") or ""
        except Exception:  # noqa: BLE001
            current_url = _build_find_agent_url(suburb)

        info = parse_pagination(html, current_url)
        reported_total = info.total_results
        expected_pages = max(1, info.expected_pages)
        page_count_known = info.last_page > 1 or bool(info.total_results and info.page_size)
        logger.info(
            "Pagination for '%s': current_page=%s last_page=%s page_size=%s "
            "total_results=%s has_pagination=%s",
            suburb,
            info.current_page,
            info.last_page,
            info.page_size,
            info.total_results,
            info.has_pagination,
        )
        await _add_from_html(html, str(page_number))
        if on_page:
            on_page(page_number)
        visited_page_urls.add((current_url or "").split("#")[0].rstrip("/").lower())

        while (max_pages is None or page_number < max_pages) and (
            page_number < expected_pages or (not page_count_known and bool(info.next_url))
        ):
            next_url = info.page_urls.get(page_number + 1) or info.next_url
            if not next_url:
                next_url = build_page_url(current_url, page_number + 1)
            next_key = (next_url or "").split("#")[0].rstrip("/").lower()
            if not next_url or next_key in visited_page_urls:
                logger.info("No further pagination URL for '%s' after page %d", suburb, page_number)
                break

            logger.info("Opening results page %d for '%s': %s", page_number + 1, suburb, next_url)
            await page.get(next_url)
            await _human_delay(1500, 3000)
            if not await _page_ready(page, suburb, attempts=8):
                logger.warning("Results page %d for '%s' did not load; stopping pagination", page_number + 1, suburb)
                break

            html = await page.get_content()
            try:
                current_url = await page.evaluate("location.href") or next_url
            except Exception:  # noqa: BLE001
                current_url = next_url
            visited_page_urls.add((current_url or next_url).split("#")[0].rstrip("/").lower())
            page_number += 1
            info = parse_pagination(html, current_url)
            if info.total_results:
                reported_total = info.total_results
            if info.last_page > 1 or (info.total_results and info.page_size):
                page_count_known = True
            expected_pages = max(expected_pages, info.expected_pages, page_number)
            added = await _add_from_html(html, str(page_number))
            if on_page:
                on_page(page_number)
            if added == 0:
                logger.warning("Page %d for '%s' contained no new profile URLs; stopping to avoid looping", page_number, suburb)
                break

        if max_pages is not None and expected_pages > page_number and page_number >= max_pages:
            logger.warning(
                "Stopped pagination for '%s' at page %d (cap=%d); website indicated ~%s pages",
                suburb,
                page_number,
                max_pages,
                expected_pages,
            )

    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to collect agent URLs for '%s': %s", suburb, exc)

    if reported_total is not None and len(ordered) != reported_total:
        logger.warning(
            "Pagination discrepancy for '%s': website reported %s result(s) but "
            "%d unique agent profile URL(s) were collected across %d page(s).",
            suburb,
            reported_total,
            len(ordered),
            page_number,
        )
    else:
        logger.info(
            "Collected %d unique agent profile URL(s) for suburb '%s' across %d page(s)",
            len(ordered),
            suburb,
            page_number,
        )

    return ordered
