"""Offline tests for profile-field cleanup and unreliable page summaries."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.extractor import extract_agent_record  # noqa: E402


class _Body:
    text_all = "Alexandra Porter 2025 years experience 5.0 (380 reviews)"


class _ProfilePage:
    async def get_content(self):
        return "<html><body>" + (" " * 6000) + "</body></html>"

    async def query_selector(self, _selector):
        return _Body()

    async def evaluate(self, script):
        if script == "document.body.innerText":
            return _Body.text_all
        return json.dumps({
            "name": "Alexandra Porter Principal, Lead Agent 2025 Top Agent 5.0 (380 reviews)",
            "job_title": "Sales Agent 5.0 (380 reviews) 83 Properties sold",
            "years_experience": 2025,
            "agency_name": "McGrath - Aspley",
            "agency_url": "https://www.realestate.com.au/agency/mcgrath-aspley-ABCD",
        })


async def _no_sleep(*_args, **_kwargs):
    return None


def test_profile_extraction_cleans_card_text_and_rejects_award_year():
    with patch("scraper.extractor.asyncio.sleep", new=_no_sleep):
        record = asyncio.run(
            extract_agent_record(
                _ProfilePage(),
                "https://www.realestate.com.au/agent/alexandra-porter-3079355",
                "Aspley, Queensland 4034",
            )
        )

    assert record["name"] == "Alexandra Porter"
    assert record["job_title"] == "Sales Agent"
    assert record["years_experience"] == ""
    assert record["suburb"] == "Aspley"
    assert record["postcode"] == "4034"


if __name__ == "__main__":
    test_profile_extraction_cleans_card_text_and_rejects_award_year()
    print("Profile extraction quality tests passed.")
