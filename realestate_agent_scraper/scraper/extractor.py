"""
Extractor — the "scraper" subtool (nodriver/async version).

Given a nodriver Tab sitting on an agent's profile page, pulls out every
field in the canonical schema using regex on the page's visible text.
"""
from __future__ import annotations
import asyncio
import logging
import re

import nodriver as nd

import config

logger = logging.getLogger("scraper.extractor")


def _text_by_pattern(body_text: str, pattern_key: str) -> str:
    pattern: re.Pattern | None = config.TEXT_PATTERNS.get(pattern_key)
    if not pattern:
        return ""
    match = pattern.search(body_text)
    return match.group(1).strip() if match else ""


async def _maybe_reveal_phone(page: nd.Tab) -> None:
    """Clicks a 'Call' button to reveal the phone number."""
    try:
        # Find button containing "Call" text
        call_btn = await page.find("Call", best_match=True, timeout=3)
        if call_btn:
            await call_btn.click()
            await asyncio.sleep(1.5)
    except Exception:  # noqa: BLE001
        pass


async def extract_agent_record(page: nd.Tab, profile_url: str, suburb_hint: str = "") -> dict:
    """
    Returns a dict with keys matching the canonical schema.
    """
    # Wait for page to load
    await asyncio.sleep(3)

    # Verify page has content
    for attempt in range(6):
        html = await page.get_content()
        if len(html) > 5000:
            break
        await asyncio.sleep(2)

    await _maybe_reveal_phone(page)

    # Get the full body text for regex extraction
    body_text = ""
    try:
        body_el = await page.query_selector("body")
        if body_el:
            body_text = body_el.text_all or ""
    except Exception:  # noqa: BLE001
        pass

    # If body text extraction failed, try getting it from page source
    if not body_text:
        try:
            # Use JavaScript to get innerText
            body_text = await page.evaluate("document.body.innerText")
        except Exception:
            logger.warning("Could not read page text for %s", profile_url)

    record = {
        "name": "",
        "job_title": "",
        "years_experience": "",
        "agency_name": "",
        "agent_email": "",
        "suburb": suburb_hint,
        "postcode": "",
        "agency_address": "",
        "phone": _text_by_pattern(body_text, "phone_number"),
        "rating": _text_by_pattern(body_text, "rating"),
        "properties_sold": _text_by_pattern(body_text, "properties_sold"),
        "median_sold_price": _text_by_pattern(body_text, "median_sold_price"),
        "median_days_advertised": _text_by_pattern(body_text, "median_days_advertised"),
        "profile_url": profile_url,
        "agency_url": "",
    }

    # Try to extract name from the profile URL (e.g. /agent/emily-sara-4005076)
    url_match = re.search(r"/agent/([\w-]+)-\d+$", profile_url)
    if url_match:
        name_slug = url_match.group(1)
        record["name"] = name_slug.replace("-", " ").title()

    # Try to extract structured data from JSON embedded in page
    html = await page.get_content()
    _extract_from_json(html, record)

    missing = [k for k, v in record.items() if v == "" and k not in ("years_experience", "agent_email", "postcode", "agency_url")]
    if missing:
        logger.debug("Fields not found on %s: %s", profile_url, missing)

    return record


def _extract_from_json(html: str, record: dict) -> None:
    """
    Extracts agent data from JSON-LD or embedded __NEXT_DATA__ / Apollo state
    commonly found in React-rendered REA pages.
    """
    import json

    # Try to find __NEXT_DATA__ JSON
    next_data_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if next_data_match:
        try:
            data = json.loads(next_data_match.group(1))
            _walk_json_for_agent(data, record)
            return
        except (json.JSONDecodeError, KeyError):
            pass

    # Try to find inline JSON with agent data
    # REA embeds agent data in various script tags
    for script_match in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
        script_content = script_match.group(1)
        if '"salespersonId"' in script_content or '"agentName"' in script_content:
            try:
                # Find JSON objects within the script
                for json_match in re.finditer(r'\{[^{}]*"salespersonId"[^{}]*\}', script_content):
                    data = json.loads(json_match.group(0))
                    if data.get("name") and not record["name"]:
                        record["name"] = data["name"]
                    break
            except (json.JSONDecodeError, KeyError):
                pass


def _walk_json_for_agent(obj, record: dict, depth: int = 0) -> None:
    """Recursively walk JSON data to find agent-related fields."""
    if depth > 10:
        return
    if isinstance(obj, dict):
        # Check if this looks like an agent record
        if "salespersonId" in obj or "agentName" in obj:
            if obj.get("name") and not record.get("name"):
                record["name"] = obj["name"]
            if obj.get("jobTitle") and not record.get("job_title"):
                record["job_title"] = obj["jobTitle"]
            if obj.get("agencyName") and not record.get("agency_name"):
                record["agency_name"] = obj["agencyName"]
            if obj.get("phone") and not record.get("phone"):
                record["phone"] = obj["phone"]
            if obj.get("yearsExperience"):
                record["years_experience"] = str(obj["yearsExperience"])
        for v in obj.values():
            _walk_json_for_agent(v, record, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json_for_agent(item, record, depth + 1)
