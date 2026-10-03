"""Unit tests for Requirement 1 field extraction (no live browser)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.html_fields import (  # noqa: E402
    extract_agency_name_from_page,
    extract_profile_fields_from_html,
    split_suburb_and_postcode,
)

YEARS_HTML = """
<div class="Inline__InlineContainer-sc-1ppy24s-0 jgKGIL">
    <svg></svg>
    <span class="Text__Typography-sc-1103tao-0 frvUJs">
        33<!-- --> years experience
    </span>
</div>
"""

AGENCY_HTML = """
<a href="https://www.realestate.com.au/agency/smart-real-estate-casuarina-CBOKDJ"
   class="LinkBase-sc-1ba0r3r-0 jpmDZo">
    Smart Real Estate - CASUARINA
</a>
"""

RATING_HTML = """
<div class="Inline__InlineContainer-sc-1ppy24s-0 jgKGIL">
    <svg></svg>
    <p class="Text__Typography-sc-1103tao-0 frvUJs">
        4.9
        <span class="Text__Typography-sc-1103tao-0 dBBSGp">
            (
            <a href="#CustomerReviews"
               class="LinkBase-sc-1ba0r3r-0 iTkPyV styles__StyledLink-sc-1doobco-1 pBUGT">
                22<!-- --> reviews
            </a>
            )
        </span>
    </p>
</div>
"""

MISSING_HTML = "<html><body><h1>Agent profile</h1><p>No extras here</p></body></html>"


def test_years_experience():
    fields = extract_profile_fields_from_html(YEARS_HTML)
    assert fields["years_experience"] == "33"


def test_agency_name_and_url():
    fields = extract_profile_fields_from_html(AGENCY_HTML)
    assert fields["agency_name"] == "Smart Real Estate - CASUARINA"
    assert fields["agency_url"] == (
        "https://www.realestate.com.au/agency/smart-real-estate-casuarina-CBOKDJ"
    )


def test_rating_and_reviews():
    fields = extract_profile_fields_from_html(RATING_HTML)
    assert fields["rating"] == "4.9"
    assert fields["reviews"] == "22"


def test_missing_fields_do_not_raise():
    fields = extract_profile_fields_from_html(MISSING_HTML)
    assert fields["years_experience"] == ""
    assert fields["agency_name"] == ""
    assert fields["agency_url"] == ""
    assert fields["rating"] == ""
    assert fields["reviews"] == ""


def test_suburb_and_postcode_are_separate():
    suburb, postcode = split_suburb_and_postcode("Darwin City, Northern Territory 0800")
    assert suburb == "Darwin City"
    assert postcode == "0800"
    assert suburb != postcode
    assert "0800" not in suburb


def test_does_not_hardcode_example_values():
    other = extract_profile_fields_from_html(
        '<span>12<!-- --> years experience</span>'
        '<a href="https://www.realestate.com.au/agency/other-agency-XYZ123">Other Agency</a>'
        '<p>3.5<span>(<a href="#CustomerReviews">8<!-- --> reviews</a>)</span></p>'
    )
    assert other["years_experience"] == "12"
    assert other["agency_name"] == "Other Agency"
    assert other["agency_url"].endswith("/agency/other-agency-XYZ123")
    assert other["rating"] == "3.5"
    assert other["reviews"] == "8"


def test_profile_contacts_require_semantic_address_and_mailto_markup():
    fields = extract_profile_fields_from_html(
        '<a href="mailto:ada@example.test?subject=Hello">Email</a>'
        '<address>12 Main Street, Aspley QLD 4034</address>'
    )
    assert fields["agent_email"] == "ada@example.test"
    assert fields["agency_address"] == "12 Main Street, Aspley QLD 4034"
    assert extract_agency_name_from_page("<h1>Belle Property - Aspley</h1>") == "Belle Property - Aspley"


if __name__ == "__main__":
    tests = [
        test_years_experience,
        test_agency_name_and_url,
        test_rating_and_reviews,
        test_missing_fields_do_not_raise,
        test_suburb_and_postcode_are_separate,
        test_does_not_hardcode_example_values,
        test_profile_contacts_require_semantic_address_and_mailto_markup,
    ]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"All {len(tests)} Requirement 1 unit tests passed.")
