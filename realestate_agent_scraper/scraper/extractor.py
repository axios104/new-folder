"""
Extractor — the "scraper" subtool (nodriver/async version).

Given a nodriver Tab sitting on an agent's profile page, pulls out every
field in the canonical schema using HTML structure, JSON-LD, and visible text.
"""
from __future__ import annotations
import asyncio
import json
import logging
import re

import nodriver as nd

import config
from scraper.html_fields import (
    clean_agent_name,
    clean_job_title,
    clean_years_experience,
    extract_profile_fields_from_html,
    split_suburb_and_postcode,
)

logger = logging.getLogger("scraper.extractor")

_OPTIONAL_FIELDS = {
    "years_experience",
    "agent_email",
    "postcode",
    "agency_url",
    "agency_name",
    "rating",
    "reviews",
    "job_title",
    "agency_address",
}

_DOM_EXTRACT_JS = r"""
(() => {
  const result = {
    name: "",
    years_experience: "",
    agency_name: "",
    agency_url: "",
    rating: "",
    reviews: "",
    job_title: "",
    agent_email: "",
    phone: "",
    agency_address: ""
  };
  const bodyText = document.body ? (document.body.innerText || "") : "";
  const nameNode = document.querySelector('[data-testid*="agent-name" i], [class*="AgentName"], main h1, h1');
  if (nameNode) result.name = (nameNode.innerText || nameNode.textContent || "").trim();
  const emailLink = document.querySelector('a[href^="mailto:"]');
  if (emailLink) result.agent_email = (emailLink.getAttribute("href") || "").replace(/^mailto:/i, "").split("?")[0];
  const phoneLink = document.querySelector('a[href^="tel:"]');
  if (phoneLink) result.phone = (phoneLink.getAttribute("href") || "").replace(/^tel:/i, "").split("?")[0];
  const addressNode = document.querySelector('address, [itemprop="streetAddress"], [data-testid*="agency-address" i]');
  if (addressNode) result.agency_address = (addressNode.innerText || addressNode.textContent || "").trim();
  const titleNode = document.querySelector('[data-testid*="job-title" i], [data-testid*="agent-title" i], [class*="JobTitle"], [class*="jobTitle"], [class*="AgentTitle"]');
  if (titleNode) result.job_title = (titleNode.innerText || titleNode.textContent || "").trim();
  if (!result.job_title) {
    const heading = document.querySelector('main h1, h1');
    const next = heading && (heading.nextElementSibling || heading.parentElement?.nextElementSibling);
    if (next && /agent|sales|property|leasing|auction|consultant|manager/i.test(next.innerText || '')) {
      result.job_title = (next.innerText || '').trim();
    }
  }
  const yearsMatch = bodyText.match(/(\d+)\s*years?\s+experience/i);
  if (yearsMatch) result.years_experience = yearsMatch[1];

  const agency = document.querySelector('a[href*="/agency/"]');
  if (agency && agency.getAttribute("href")) {
    result.agency_name = (agency.innerText || "").trim();
    result.agency_url = agency.href || "";
  }

  const reviewLink = document.querySelector('a[href="#CustomerReviews"], a[href$="#CustomerReviews"]');
  if (reviewLink) {
    const reviewMatch = (reviewLink.innerText || "").match(/(\d+)/);
    if (reviewMatch) result.reviews = reviewMatch[1];
    const parent = reviewLink.closest("p") || reviewLink.parentElement;
    if (parent) {
      const ratingMatch = (parent.innerText || "").match(/\b([0-5](?:\.\d)?)\b/);
      if (ratingMatch) result.rating = ratingMatch[1];
    }
  }
  return JSON.stringify(result);
})()
"""


def _text_by_pattern(body_text: str, pattern_key: str) -> str:
    pattern: re.Pattern | None = config.TEXT_PATTERNS.get(pattern_key)
    if not pattern:
        return ""
    match = pattern.search(body_text)
    return match.group(1).strip() if match else ""


def _fill_if_empty(record: dict, key: str, value) -> None:
    if value in (None, ""):
        return
    if not record.get(key):
        record[key] = str(value).strip()


async def _maybe_reveal_phone(page: nd.Tab) -> None:
    """Clicks a 'Call' button to reveal the phone number."""
    try:
        call_btn = await page.find("Call", best_match=True, timeout=3)
        if call_btn:
            await call_btn.click()
            await asyncio.sleep(1.5)
    except Exception:  # noqa: BLE001
        pass


async def _dom_fields(page: nd.Tab) -> dict:
    try:
        raw = await page.evaluate(_DOM_EXTRACT_JS)
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.startswith("{"):
            return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        logger.debug("DOM evaluate failed: %s", exc)
    return {}


async def extract_agent_record(page: nd.Tab, profile_url: str, suburb_hint: str = "") -> dict:
    """
    Returns a dict with keys matching the canonical schema.
    Missing optional fields are stored as empty strings and never raise.
    """
    await asyncio.sleep(3)

    html = ""
    for attempt in range(6):
        try:
            html = await page.get_content()
        except Exception:  # noqa: BLE001
            html = ""
        if html and len(html) > 5000:
            break
        await asyncio.sleep(2)

    await _maybe_reveal_phone(page)

    body_text = ""
    try:
        body_el = await page.query_selector("body")
        if body_el:
            body_text = body_el.text_all or ""
    except Exception:  # noqa: BLE001
        pass

    if not body_text:
        try:
            body_text = await page.evaluate("document.body.innerText") or ""
        except Exception:
            logger.warning("Could not read page text for %s", profile_url)

    suburb, postcode = split_suburb_and_postcode(suburb_hint)

    record = {
        "name": "",
        "job_title": "",
        "years_experience": "",
        "agency_name": "",
        "agent_email": "",
        "suburb": suburb,
        "postcode": postcode,
        "agency_address": "",
        "phone": _text_by_pattern(body_text, "phone_number"),
        "rating": "",
        "reviews": "",
        "properties_sold": _text_by_pattern(body_text, "properties_sold"),
        "median_sold_price": _text_by_pattern(body_text, "median_sold_price"),
        "median_days_advertised": _text_by_pattern(body_text, "median_days_advertised"),
        "profile_url": profile_url,
        "agency_url": "",
    }

    html_fields = extract_profile_fields_from_html(html)
    for key, value in html_fields.items():
        _fill_if_empty(record, key, value)

    try:
        fresh_html = await page.get_content()
        html = fresh_html or html
    except Exception:  # noqa: BLE001
        pass
    html_fields = extract_profile_fields_from_html(html)
    for key, value in html_fields.items():
        _fill_if_empty(record, key, value)

    for key, value in (await _dom_fields(page)).items():
        if key == "name":
            value = clean_agent_name(str(value or ""), profile_url)
        elif key == "job_title":
            value = clean_job_title(str(value or ""))
        _fill_if_empty(record, key, value)

    _fill_if_empty(record, "years_experience", _text_by_pattern(body_text, "years_experience"))
    _fill_if_empty(record, "rating", _text_by_pattern(body_text, "rating"))
    _fill_if_empty(record, "reviews", _text_by_pattern(body_text, "reviews"))

    _extract_from_json(html, record)

    # Years experience is a human count. Reject award years and other values
    # accidentally surfaced by embedded page data.
    record["years_experience"] = clean_years_experience(record.get("years_experience"))

    if not record["name"]:
        record["name"] = clean_agent_name("", profile_url)

    missing = [k for k, v in record.items() if v == "" and k not in _OPTIONAL_FIELDS]
    if missing:
        logger.debug("Fields not found on %s: %s", profile_url, missing)

    return record


def _extract_from_json(html: str, record: dict) -> None:
    """
    Extracts agent data from JSON-LD or embedded __NEXT_DATA__ / Apollo state
    commonly found in React-rendered REA pages.
    """
    next_data_match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    if next_data_match:
        try:
            data = json.loads(next_data_match.group(1))
            _walk_json_for_agent(data, record)
            return
        except (json.JSONDecodeError, KeyError):
            pass

    for script_match in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
        script_content = script_match.group(1)
        if '"salespersonId"' in script_content or '"agentName"' in script_content:
            try:
                for json_match in re.finditer(r'\{[^{}]*"salespersonId"[^{}]*\}', script_content):
                    data = json.loads(json_match.group(0))
                    if data.get("name") and not record["name"]:
                        record["name"] = clean_agent_name(str(data["name"]), record.get("profile_url", ""))
                    break
            except (json.JSONDecodeError, KeyError):
                pass


def _walk_json_for_agent(obj, record: dict, depth: int = 0) -> None:
    """Recursively walk JSON data to find agent-related fields."""
    if depth > 10:
        return
    if isinstance(obj, dict):
        if "salespersonId" in obj or "agentName" in obj or "agencyName" in obj or "jobTitle" in obj:
            if obj.get("name") and not record.get("name"):
                name = clean_agent_name(str(obj.get("name")), record.get("profile_url", ""))
                if name:
                    record["name"] = name
            if obj.get("jobTitle"):
                _fill_if_empty(record, "job_title", obj.get("jobTitle"))
            if obj.get("designation"):
                _fill_if_empty(record, "job_title", obj.get("designation"))
            if obj.get("agencyName"):
                _fill_if_empty(record, "agency_name", obj.get("agencyName"))
            phone = obj.get("phone") or obj.get("phoneNumber") or obj.get("mobile") or obj.get("telephone")
            if phone:
                _fill_if_empty(record, "phone", phone)
            email = obj.get("email") or obj.get("emailAddress") or obj.get("workEmail") or obj.get("agentEmail")
            if email:
                _fill_if_empty(record, "agent_email", email)
            years = (
                obj.get("yearsExperience") or obj.get("yearsOfExperience")
                or obj.get("experienceYears") or obj.get("experienceInYears")
            )
            if years not in (None, ""):
                _fill_if_empty(record, "years_experience", years)
            rating = obj.get("rating") or obj.get("averageRating") or obj.get("ratingValue")
            if rating not in (None, ""):
                _fill_if_empty(record, "rating", rating)
            reviews = obj.get("reviewCount") or obj.get("numberOfReviews")
            if reviews not in (None, ""):
                _fill_if_empty(record, "reviews", reviews)
            agency_url = obj.get("agencyUrl") or obj.get("agencyProfileUrl")
            if agency_url:
                _fill_if_empty(record, "agency_url", agency_url)
        for v in obj.values():
            _walk_json_for_agent(v, record, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_json_for_agent(item, record, depth + 1)
