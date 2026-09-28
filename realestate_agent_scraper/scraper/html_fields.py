"""
Pure HTML field parsers for agent profile pages.

These helpers operate on page source (not hashed CSS class names) so they
can be unit-tested with captured outerHTML and reused by the live extractor.
"""
from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin

from config import BASE_URL

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_YEARS_RE = re.compile(
    r"(\d+)\s*(?:<!--.*?-->\s*)?years?\s+experience",
    re.IGNORECASE | re.DOTALL,
)

_AGENCY_ANCHOR_RE = re.compile(
    r"""<a\b[^>]*href=["']([^"']*?/agency/[A-Za-z0-9][A-Za-z0-9-]*)["'][^>]*>(.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)

_REVIEW_LINK_RE = re.compile(
    r"""<a\b[^>]*href=["'][^"']*#CustomerReviews["'][^>]*>(.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)

_REVIEWS_COUNT_RE = re.compile(
    r"(\d+)\s*(?:<!--.*?-->\s*)?reviews?",
    re.IGNORECASE | re.DOTALL,
)

_RATING_BEFORE_REVIEWS_RE = re.compile(
    r">\s*([0-5](?:\.\d)?)\s*<span[^>]*>\s*\(\s*<a\b[^>]*href=['\"][^'\"]*#CustomerReviews",
    re.IGNORECASE | re.DOTALL,
)

_JSON_RATING_RE = re.compile(
    r'"(?:ratingValue|averageRating|avgRating)"\s*:\s*"?([0-5](?:\.\d+)?)"?',
    re.IGNORECASE,
)
_JSON_REVIEWS_RE = re.compile(
    r'"(?:reviewCount|reviewsCount|numberOfReviews)"\s*:\s*"?(\d+)"?',
    re.IGNORECASE,
)
_JSON_YEARS_RE = re.compile(
    r'"(?:yearsExperience|yearsOfExperience|experienceYears)"\s*:\s*"?(\d+)"?',
    re.IGNORECASE,
)


def _visible_text(fragment: str) -> str:
    fragment = _COMMENT_RE.sub(" ", fragment)
    fragment = _TAG_RE.sub(" ", fragment)
    fragment = html_lib.unescape(fragment)
    return _WS_RE.sub(" ", fragment).strip()


def _absolute_url(href: str) -> str:
    href = html_lib.unescape(href).strip()
    if href.startswith("//"):
        return "https:" + href
    return urljoin(BASE_URL + "/", href)


def extract_years_experience(html: str) -> str:
    match = _YEARS_RE.search(html or "")
    return match.group(1) if match else ""


def extract_agency(html: str) -> tuple[str, str]:
    """Return (agency_name, agency_url) from the first real agency profile link."""
    for match in _AGENCY_ANCHOR_RE.finditer(html or ""):
        href = _absolute_url(match.group(1))
        if "/agency/" not in href:
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1]
        if not slug or slug.lower() in {"agency", "find-agent"}:
            continue
        name = _visible_text(match.group(2))
        if name:
            return name, href
        return "", href
    return "", ""


def extract_rating_and_reviews(html: str) -> tuple[str, str]:
    """Return (rating, review_count) from the CustomerReviews block when present."""
    source = html or ""
    rating = ""
    reviews = ""

    rating_match = _RATING_BEFORE_REVIEWS_RE.search(source)
    if rating_match:
        rating = rating_match.group(1)

    review_link = _REVIEW_LINK_RE.search(source)
    if review_link:
        count_match = _REVIEWS_COUNT_RE.search(review_link.group(1))
        if count_match:
            reviews = count_match.group(1)

    if not reviews:
        count_match = _REVIEWS_COUNT_RE.search(source)
        if count_match:
            reviews = count_match.group(1)

    if not rating:
        json_rating = _JSON_RATING_RE.search(source)
        if json_rating:
            rating = json_rating.group(1)
    if not reviews:
        json_reviews = _JSON_REVIEWS_RE.search(source)
        if json_reviews:
            reviews = json_reviews.group(1)

    return rating, reviews


def extract_profile_fields_from_html(html: str) -> dict[str, str]:
    """Extract all Requirement-1 fields that can be derived from page HTML."""
    years = extract_years_experience(html)
    if not years:
        json_years = _JSON_YEARS_RE.search(html or "")
        years = json_years.group(1) if json_years else ""

    agency_name, agency_url = extract_agency(html)
    rating, reviews = extract_rating_and_reviews(html)
    return {
        "years_experience": years,
        "agency_name": agency_name,
        "agency_url": agency_url,
        "rating": rating,
        "reviews": reviews,
    }


def split_suburb_and_postcode(suburb_hint: str) -> tuple[str, str]:
    """
    Split a suburb search string into separate suburb and postcode values.

    "Darwin City, Northern Territory 0800" -> ("Darwin City", "0800")
    Never returns a combined suburb+postcode string.
    """
    text = (suburb_hint or "").strip()
    if not text:
        return "", ""

    postcode = ""
    postcode_match = re.search(r"\b(\d{4})\b", text)
    if postcode_match:
        postcode = postcode_match.group(1)

    suburb = text
    if "," in text:
        suburb = text.split(",", 1)[0].strip()
    elif postcode:
        suburb = text[: postcode_match.start()].strip()

    suburb = re.sub(r"\s+", " ", suburb).strip(" ,")
    return suburb, postcode
