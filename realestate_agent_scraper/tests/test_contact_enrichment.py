"""Offline tests for safe agency-site contact enrichment."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.contact_enrichment import (  # noqa: E402
    extract_agency_website_url,
    extract_external_agent_details,
    extract_external_agent_links,
    extract_team_directory_urls,
)


def test_agency_link_and_same_site_directory_filtering():
    agency = '''<a href="https://agency.example/">Agency website</a>
      <a href="https://unrelated.example/team">Meet our team</a>'''
    website = extract_agency_website_url(agency)
    assert website == "https://agency.example/"

    html = '''<a href="/our-team/">Our team</a>
      <a href="/our-team/alexandra-porter/">Alexandra Porter</a>
      <a href="https://unrelated.example/our-team/jane-doe/">Jane Doe</a>'''
    dirs = extract_team_directory_urls(html, website)
    assert dirs == [website, "https://agency.example/our-team/"]
    profiles = extract_external_agent_links(html, website)
    assert list(profiles) == ["alexandra porter"]
    assert profiles["alexandra porter"] == "https://agency.example/our-team/alexandra-porter/"


def test_profile_details_require_expected_person_and_extract_contacts():
    html = '''<h1>Alexandra Porter</h1><p>Principal, Lead Agent</p>
      <a href="tel:+61732638888">Call</a><a href="mailto:alex@example.com">Email</a>
      <h2>Office details</h2><p>123 Main Street, Aspley QLD 4034</p>'''
    assert extract_external_agent_details(html, "Alexandra Porter") == {
        "job_title": "Principal, Lead Agent",
        "agent_email": "alex@example.com",
        "phone": "+61732638888",
        "agency_address": "123 Main Street, Aspley QLD 4034",
    }
    assert extract_external_agent_details(html, "Different Person") == {
        "job_title": "", "agent_email": "", "phone": "", "agency_address": ""
    }


def test_unsafe_and_non_http_agency_urls_are_ignored():
    assert extract_agency_website_url('<a href="http://127.0.0.1/">Agency website</a>') == ""
    assert extract_agency_website_url('<a href="javascript:alert(1)">Agency website</a>') == ""


if __name__ == "__main__":
    test_agency_link_and_same_site_directory_filtering()
    test_profile_details_require_expected_person_and_extract_contacts()
    test_unsafe_and_non_http_agency_urls_are_ignored()
    print("All contact enrichment tests passed.")
