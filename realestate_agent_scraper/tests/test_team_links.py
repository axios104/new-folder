from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.html_fields import (  # noqa: E402
    clean_agent_name,
    clean_job_title,
    clean_years_experience,
    agent_profile_identity,
    extract_team_member_links,
    parse_team_member_summary,
)


def test_team_members_are_only_read_from_about_team_section():
    html = '''
    <a href="/agent/outside-agent-1">Outside Agent</a>
    <div id="TeamMembers"><h2>About the team</h2>
      <p>Showing 2 of 2 team members</p><div class="styles__StyledGrid">
        <a href="/agent/alex-one-11?campaignType=internal">Alex One</a>
        <a href="/agent/sam-two-22">Sam Two</a>
        <a href="/agent/alex-one-11">Alex One</a>
      </div></div>
    <div id="CustomerReviews"></div>
    '''
    links = extract_team_member_links(html)
    assert [(item.name, item.profile_url) for item in links] == [
        ("Alex One", "https://www.realestate.com.au/agent/alex-one-11"),
        ("Sam Two", "https://www.realestate.com.au/agent/sam-two-22"),
    ]


def test_team_card_summary_is_split_into_person_title_and_stats():
    summary = (
        "Alexandra Porter Principal, Lead Agent 2025 Top Agent 5.0 "
        "( 380 reviews ) 83 Properties sold (as lead agent) $1.21M Median sale price"
    )
    parsed = parse_team_member_summary(summary)
    assert parsed == {
        "name": "Alexandra Porter",
        "job_title": "Principal, Lead Agent",
        "rating": "5.0",
        "reviews": "380",
        "properties_sold": "83",
        "median_sold_price": 1_210_000,
    }
    assert clean_agent_name(summary, "https://www.realestate.com.au/agent/3079355") == "Alexandra Porter"
    assert clean_job_title("Sales Agent 5.0 (380 reviews) 83 Properties sold") == "Sales Agent"
    assert clean_job_title("Director - Properties sold (as lead agent)") == "Director"
    assert clean_job_title("Sales Agent - Properties sold (as lead agent)") == "Sales Agent"
    assert clean_job_title("Properties sold (as lead agent)") == ""


def test_team_card_summary_rejects_company_card_as_a_person_name():
    parsed = parse_team_member_summary(
        "Belle Property Rentals Belle Property Rentals 2 Properties leased $660 Median leased price per week"
    )
    assert parsed["name"] == ""


def test_years_experience_rejects_calendar_years_and_invalid_values():
    assert clean_years_experience("33") == 33
    assert clean_years_experience("2025") == ""
    assert clean_years_experience("unknown") == ""


def test_slugged_and_numeric_profile_links_have_same_identity():
    assert agent_profile_identity("https://www.realestate.com.au/agent/alexandra-porter-3079355") == (
        agent_profile_identity("https://www.realestate.com.au/agent/3079355")
    )


if __name__ == "__main__":
    test_team_members_are_only_read_from_about_team_section()
    test_team_card_summary_is_split_into_person_title_and_stats()
    test_team_card_summary_rejects_company_card_as_a_person_name()
    test_years_experience_rejects_calendar_years_and_invalid_values()
    test_slugged_and_numeric_profile_links_have_same_identity()
    print("Team member extraction test passed.")
