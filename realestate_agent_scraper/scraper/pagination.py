"""Parse find-agent (or listing) pagination from HTML without hashed CSS classes."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from config import BASE_URL

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

_GO_TO_PAGE_RE = re.compile(
    r"""aria-label=["']Go to page\s+(\d+)["']""",
    re.IGNORECASE,
)
_NEXT_HREF_RE = re.compile(
    r"""<a\b[^>]*(?:rel=["']next["']|aria-label=["'][^"']*next page[^"']*["'])[^>]*href=["']([^"']+)["']"""
    r"""|<a\b[^>]*href=["']([^"']+)["'][^>]*(?:rel=["']next["']|aria-label=["'][^"']*next page[^"']*["'])""",
    re.IGNORECASE,
)
_SHOWING_RE = re.compile(
    r"Showing\s+([\d,]+)\s*[–-]\s*([\d,]+)\s+of\s+([\d,]+)",
    re.IGNORECASE,
)
_PROFILES_RE = re.compile(
    r"([\d,]+)\s+profiles?\b",
    re.IGNORECASE,
)
_PAGE_QUERY_RE = re.compile(r"([?&]page=)(\d+)", re.IGNORECASE)
_LIST_PATH_RE = re.compile(r"/list-(\d+)\b", re.IGNORECASE)


def _abs(href: str, current_url: str) -> str:
    href = html.unescape(href.strip())
    if href.startswith("//"):
        href = "https:" + href
    else:
        href = urljoin(current_url or BASE_URL + "/", href)
    return _clean_pagination_url(href)


def _clean_pagination_url(url: str) -> str:
    """Drop tracking parameters and duplicated/HTML-escaped pagination junk."""
    parts = urlsplit(html.unescape(url))
    # Results are fully determined by their path and page number. The source
    # attaches campaign parameters that can contain nested escaped query
    # strings; carrying them forward grows the URL on every pagination step.
    allowed = {"page", "activesort", "sort"}
    query: list[tuple[str, str]] = []
    page_value: str | None = None
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        normal_key = key.strip().lower()
        if normal_key == "page" and value.isdigit():
            page_value = value
        elif normal_key in allowed - {"page"} and not re.search(r"amp|%3b|%26", value, re.I):
            query.append((key, value))
    if page_value is not None:
        query.append(("page", page_value))
    clean_path = _LIST_PATH_RE.sub(lambda match: f"/list-{match.group(1)}", parts.path)
    return urlunsplit((parts.scheme, parts.netloc, clean_path, urlencode(query), ""))


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(str(value).replace(",", "").strip())
    except ValueError:
        return None


@dataclass
class PaginationInfo:
    current_page: int = 1
    last_page: int = 1
    page_size: int | None = None
    total_results: int | None = None
    next_url: str | None = None
    page_urls: dict[int, str] = field(default_factory=dict)
    has_pagination: bool = False

    @property
    def expected_pages(self) -> int:
        if self.last_page and self.last_page > 1:
            return self.last_page
        if self.total_results and self.page_size:
            return max(1, (self.total_results + self.page_size - 1) // self.page_size)
        return 1


def parse_pagination(html: str, current_url: str = "") -> PaginationInfo:
    source = _COMMENT_RE.sub(" ", html or "")
    info = PaginationInfo()

    page_numbers = [int(n) for n in _GO_TO_PAGE_RE.findall(source)]
    if page_numbers:
        info.has_pagination = True
        info.last_page = max(page_numbers)

    showing = _SHOWING_RE.search(source)
    if showing:
        start = _to_int(showing.group(1))
        end = _to_int(showing.group(2))
        total = _to_int(showing.group(3))
        info.total_results = total
        if start and end and end >= start:
            info.page_size = end - start + 1
            info.current_page = ((start - 1) // info.page_size) + 1 if info.page_size else 1
        if total and info.page_size:
            derived_last = (total + info.page_size - 1) // info.page_size
            info.last_page = max(info.last_page, derived_last)
            if derived_last > 1:
                info.has_pagination = True

    if info.total_results is None:
        profiles = _PROFILES_RE.search(source)
        if profiles:
            info.total_results = _to_int(profiles.group(1))

    current_url = _clean_pagination_url(current_url) if current_url else ""
    next_match = _NEXT_HREF_RE.search(source)
    if next_match:
        href = next_match.group(1) or next_match.group(2)
        if href:
            info.next_url = _abs(href, current_url)
            info.has_pagination = True

    # Capture numbered page links with hrefs, regardless of attribute order.
    for link in re.finditer(
        r'<a\b([^>]+)>(.*?)</a>',
        source,
        re.IGNORECASE | re.DOTALL,
    ):
        attrs = link.group(1)
        label = re.search(r"""aria-label=["']Go to page\s+(\d+)["']""", attrs, re.I)
        href_m = re.search(r"""href=["']([^"']+)["']""", attrs, re.I)
        if label and href_m:
            page_no = int(label.group(1))
            # The visible page label is reliable; the href's campaign query
            # may contain encoded copies of many other pagination links.
            base_url = current_url or _abs(href_m.group(1), BASE_URL)
            info.page_urls[page_no] = build_page_url(base_url, page_no)
            info.last_page = max(info.last_page, page_no)
            info.has_pagination = True

    if not info.has_pagination:
        info.last_page = 1
        info.next_url = None

    return info


def build_page_url(current_url: str, page_number: int) -> str:
    """Best-effort construction of a results-page URL for an arbitrary page."""
    if not current_url:
        return current_url
    current_url = _clean_pagination_url(current_url)
    if page_number <= 1:
        # Strip page query / list-N when returning to page 1.
        parts = urlsplit(current_url)
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != "page"]
        path = _LIST_PATH_RE.sub("", parts.path)
        return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), parts.fragment))

    if _PAGE_QUERY_RE.search(current_url):
        return _PAGE_QUERY_RE.sub(rf"\g<1>{page_number}", current_url, count=1)

    if _LIST_PATH_RE.search(current_url):
        return _LIST_PATH_RE.sub(f"/list-{page_number}", current_url, count=1)

    parts = urlsplit(current_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["page"] = str(page_number)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def extract_agent_profile_urls(html: str) -> list[str]:
    matches = re.findall(
        r"""href=["'](https?://(?:www\.)?realestate\.com\.au/agent/[\w-]+-\d+)["']""",
        html or "",
        flags=re.IGNORECASE,
    )
    relative = re.findall(
        r"""href=["'](/agent/[\w-]+-\d+)["']""",
        html or "",
        flags=re.IGNORECASE,
    )
    urls = [m.split("?")[0] for m in matches]
    urls.extend(_abs(path, BASE_URL) for path in relative)
    # Preserve order, drop duplicates and trailing slashes inconsistencies.
    normalised = []
    seen = set()
    for url in urls:
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        normalised.append(url.rstrip("/"))
    return normalised
