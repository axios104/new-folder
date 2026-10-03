from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.html_fields import extract_team_member_links  # noqa: E402


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


if __name__ == "__main__":
    test_team_members_are_only_read_from_about_team_section()
    print("Team member extraction test passed.")
