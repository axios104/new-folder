"""Unit tests for Requirement 2 pagination parsing (no live browser)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.pagination import (  # noqa: E402
    build_page_url,
    extract_agent_profile_urls,
    parse_pagination,
)

PAGINATION_HTML = """
<div>
    <nav aria-label="Pagination Navigation">
        <a aria-label="Go to page 1" href="/find-agent/darwin+city-nt-0800/?page=1">1</a>
        <a aria-label="Go to page 2" href="/find-agent/darwin+city-nt-0800/?page=2">2</a>
        <a aria-label="Go to page 3" href="/find-agent/darwin+city-nt-0800/?page=3">3</a>
        <a aria-label="Go to page 4" href="/find-agent/darwin+city-nt-0800/?page=4">4</a>
        <a aria-label="Go to page 11" href="/find-agent/darwin+city-nt-0800/?page=11">11</a>
        <a aria-label="Go to next page"
           rel="next"
           href="/find-agent/darwin+city-nt-0800/?page=2">
            Next
        </a>
    </nav>
    <p>Showing 1 – 25 of 261 properties</p>
    <a href="https://www.realestate.com.au/agent/emily-sara-4005076">Emily</a>
    <a href="https://www.realestate.com.au/agent/mick-smith-1129187">Mick</a>
</div>
"""

SINGLE_PAGE_HTML = """
<div>
    <p>24 profiles</p>
    <a href="https://www.realestate.com.au/agent/emily-sara-4005076">Emily</a>
</div>
"""


def test_pagination_from_nav_and_showing():
    info = parse_pagination(
        PAGINATION_HTML,
        "https://www.realestate.com.au/find-agent/darwin+city-nt-0800/",
    )
    assert info.has_pagination is True
    assert info.last_page == 11
    assert info.total_results == 261
    assert info.page_size == 25
    assert info.expected_pages == 11
    assert info.next_url.endswith("/find-agent/darwin+city-nt-0800/?page=2")
    assert 11 in info.page_urls


def test_single_page_has_no_pagination():
    info = parse_pagination(SINGLE_PAGE_HTML, "https://www.realestate.com.au/find-agent/x/")
    assert info.has_pagination is False
    assert info.last_page == 1
    assert info.total_results == 24
    assert info.next_url is None


def test_build_page_url_uses_query_param():
    url = build_page_url("https://www.realestate.com.au/find-agent/darwin+city-nt-0800/", 3)
    assert "page=3" in url


def test_extract_agent_urls_dedupes():
    html = PAGINATION_HTML + '<a href="https://www.realestate.com.au/agent/emily-sara-4005076">'
    urls = extract_agent_profile_urls(html)
    assert len(urls) == 2
    assert urls[0].endswith("/agent/emily-sara-4005076")


if __name__ == "__main__":
    tests = [
        test_pagination_from_nav_and_showing,
        test_single_page_has_no_pagination,
        test_build_page_url_uses_query_param,
        test_extract_agent_urls_dedupes,
    ]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"All {len(tests)} Requirement 2 unit tests passed.")
