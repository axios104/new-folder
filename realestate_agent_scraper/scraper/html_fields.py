"""
Pure HTML field parsers for agent profile pages.

These helpers operate on page source (not hashed CSS class names) so they
can be unit-tested with captured outerHTML and reused by the live extractor.
"""
from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urljoin
from dataclasses import dataclass

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
_MAILTO_RE = re.compile(r'<a\b[^>]*href=["\']mailto:([^"\'?#]+)', re.IGNORECASE)

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

_TEAM_AGENT_LINK_RE = re.compile(
    r'<a\b[^>]*href=["\']([^"\']*/agent/[^"\'?#]+)[^"\']*["\'][^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class TeamMemberLink:
    """A team-member profile advertised by a realestate.com.au agency page."""

    name: str
    profile_url: str
    job_title: str = ""
    rating: str = ""
    reviews: str = ""
    properties_sold: str = ""
    median_sold_price: int | str = ""


_TEAM_ROLE_RE = re.compile(
    r"\b(Investment Specialist|Sales Representative|Sales Consultant|Sales Associate|"
    r"Property Manager|Leasing Consultant|Real Estate Agent|Sales Agent|Auctioneer|"
    r"Lead Agent|Co[- ]Agent|Principal|Director|Agent)\b",
    re.IGNORECASE,
)
_TEAM_CARD_END_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*\(\s*\d+\s+reviews?\b|\d+\s+properties?\s+(?:sold|leased)\b|"
    r"median\s+(?:sale|sold)\s+price\b|\$\s*\d)",
    re.IGNORECASE,
)
_ROLE_TRAILER_RE = re.compile(r"\b(?:20\d{2}\s+Top Agent|Top Agent|\d{4})\b", re.I)


def _valid_person_name(value: str) -> bool:
    value = _WS_RE.sub(" ", value or "").strip(" ,|—-")
    words = re.findall(r"[^\W\d_]+(?:['’.-][^\W\d_]+)*", value, re.UNICODE)
    if not 1 <= len(words) <= 6 or len(value) > 70 or re.search(r"\d", value):
        return False
    lower = value.casefold()
    if any(token in lower for token in (
        "property rentals", "real estate", "properties sold", "reviews", "top agent",
        "principal", "sales agent", "sales representative", "sales consultant",
        "sales associate", "investment specialist", "property manager",
    )):
        return False
    if lower in {"n/a", "na", "unknown", "not available", "agent profile"}:
        return False
    halfway = len(words) // 2
    if len(words) % 2 == 0 and words[:halfway] == words[halfway:]:
        return False
    return True


def parse_team_member_summary(value: str) -> dict[str, str | int]:
    """Split a team-card link's visible name/title/stat summary into fields."""
    text = _WS_RE.sub(" ", html_lib.unescape(value or "")).strip()
    if not text:
        return {"name": "", "job_title": "", "rating": "", "reviews": "", "properties_sold": "", "median_sold_price": ""}

    card_end = _TEAM_CARD_END_RE.search(text)
    prefix = text[:card_end.start()].strip(" ,|—-") if card_end else text
    role = _TEAM_ROLE_RE.search(prefix)
    if role:
        name = prefix[:role.start()].strip(" ,|—-")
        title = _ROLE_TRAILER_RE.split(prefix[role.start():], maxsplit=1)[0].strip(" ,|—-")
    else:
        name, title = prefix, ""
    if not _valid_person_name(name):
        name = ""

    data = {"name": name, "job_title": title, "rating": "", "reviews": "", "properties_sold": "", "median_sold_price": ""}
    review_match = re.search(r"\b([0-5](?:\.\d)?)\s*\(\s*([\d,]+)\s+reviews?\s*\)", text, re.I)
    if review_match:
        data["rating"], data["reviews"] = review_match.group(1), review_match.group(2).replace(",", "")
    sold_match = re.search(r"\b([\d,]+)\s+properties?\s+sold\b", text, re.I)
    if sold_match:
        data["properties_sold"] = sold_match.group(1).replace(",", "")
    price_match = re.search(r"\$\s*([\d,.]+\s*[kKmM]?)\s+median\s+(?:sale|sold)\s+price\b", text, re.I)
    if price_match:
        price = price_match.group(1).replace(" ", "")
        multiplier = 1_000_000 if price[-1:].lower() == "m" else 1_000 if price[-1:].lower() == "k" else 1
        numeric = price[:-1] if price[-1:].lower() in {"k", "m"} else price
        try:
            data["median_sold_price"] = int(round(float(numeric.replace(",", "")) * multiplier))
        except ValueError:
            data["median_sold_price"] = ""
    return data


def clean_agent_name(value: str, profile_url: str = "") -> str:
    """Return a person name, never the metric-rich text of a result card."""
    parsed = parse_team_member_summary(value)
    candidate = parsed["name"] or _WS_RE.sub(" ", html_lib.unescape(value or "")).strip(" ,|—-")
    if re.search(r"[-_]\d+$", candidate):
        candidate = ""
    if _valid_person_name(candidate):
        return candidate
    match = re.search(r"/agent/(?:[^/]*?-)?(\d+)(?:/)?(?:[?#].*)?$", profile_url, re.I)
    if match:
        slug = re.search(r"/agent/([^/?#]+?)-\d+/?(?:[?#].*)?$", profile_url, re.I)
        if slug:
            candidate = re.sub(r"[-_]+", " ", slug.group(1)).title()
            if _valid_person_name(candidate):
                return candidate
    return ""


def clean_years_experience(value) -> int | str:
    """Keep plausible experience counts and reject award/calendar years."""
    try:
        years = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return ""
    return years if 0 <= years <= 70 else ""


def clean_job_title(value: str) -> str:
    """Strip profile-card statistics from a title while preserving plain roles."""
    text = _WS_RE.sub(" ", html_lib.unescape(value or "")).strip(" ,|—-")
    if not text:
        return ""
    parsed = parse_team_member_summary(text)["job_title"]
    if parsed:
        return parsed
    if len(text) > 80 or re.search(r"\b(?:reviews?|properties? sold|median (?:sale|sold) price|20\d{2})\b", text, re.I):
        return ""
    return text


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


def agent_profile_identity(url: str) -> str:
    """Collapse slugged and numeric-only profile URLs to the same agent ID."""
    path = str(url or "").split("?", 1)[0].split("#", 1)[0].rstrip("/").lower()
    match = re.search(r"/agent/(?:[^/]*?-)?(\d+)$", path)
    return f"agent:{match.group(1)}" if match else path


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


def extract_agency_name_from_page(html: str) -> str:
    """Read an agency page heading when a profile has no agency anchor label."""
    match = re.search(r"<h1\b[^>]*>(.*?)</h1\s*>", html or "", re.I | re.S)
    name = _visible_text(match.group(1)) if match else ""
    if name and len(name) <= 100 and not re.search(
        r"\b(?:reviews?|properties? sold|median (?:sale|sold) price)\b", name, re.I
    ):
        return name
    return extract_agency(html or "")[0]


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
    email_match = _MAILTO_RE.search(html or "")
    email = html_lib.unescape(email_match.group(1)).strip() if email_match else ""
    address_match = re.search(r"<address\b[^>]*>(.*?)</address\s*>", html or "", re.I | re.S)
    if not address_match:
        address_match = re.search(
            r"<([a-z][\w:-]*)\b[^>]*itemprop=[\"']streetAddress[\"'][^>]*>(.*?)</\1\s*>",
            html or "",
            re.I | re.S,
        )
        address_html = address_match.group(2) if address_match else ""
    else:
        address_html = address_match.group(1)
    agency_address = _visible_text(address_html)
    return {
        "years_experience": years,
        "agency_name": agency_name,
        "agency_url": agency_url,
        "agent_email": email,
        "agency_address": agency_address,
        "rating": rating,
        "reviews": reviews,
    }


def extract_team_member_links(html: str) -> list[TeamMemberLink]:
    """Extract unique agent profile links from the agency's ``About the team`` card.

    The card's styled class names are generated, but its ``TeamMembers`` id is
    semantic and stable.  This parser deliberately only accepts links nested in
    that card, preventing unrelated agent links elsewhere on the agency page
    from being reported as team members.
    """
    source = html or ""
    start = re.search(r'<(?:div|section)\b[^>]*\bid=["\']TeamMembers["\'][^>]*>', source, re.I)
    if not start:
        return []

    # HTML is not generally regular, but this page's team card is a bounded
    # section. Scan from its opening tag until the next major page section so
    # nested grid divs do not cause a premature match.
    tail = source[start.end():]
    end = re.search(r'<(?:div|section)\b[^>]*\bid=["\'](?:CustomerReviews|Listings|SoldProperties)["\']', tail, re.I)
    fragment = tail[:end.start()] if end else tail
    members: list[TeamMemberLink] = []
    seen: set[str] = set()
    for match in _TEAM_AGENT_LINK_RE.finditer(fragment):
        url = _absolute_url(match.group(1))
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        summary = _visible_text(match.group(2))
        parsed = parse_team_member_summary(summary)
        name = parsed["name"] or clean_agent_name(summary, url)
        seen.add(key)
        members.append(
            TeamMemberLink(
                name=name,
                profile_url=url,
                job_title=parsed["job_title"],
                rating=parsed["rating"],
                reviews=parsed["reviews"],
                properties_sold=parsed["properties_sold"],
                median_sold_price=parsed["median_sold_price"],
            )
        )
    return members


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
