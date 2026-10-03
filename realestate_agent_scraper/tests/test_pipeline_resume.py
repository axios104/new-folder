"""Mocked pipeline test for suburb-scoped resume and duplicate handling."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline  # noqa: E402


class FakePage:
    async def get(self, _url):
        return self


class DeepPage(FakePage):
    async def get_content(self):
        return '<div id="TeamMembers"><a href="/agent/member-2">Team Member</a></div>'


class FakeBrowser:
    async def get(self, _url):
        return FakePage()

    async def stop(self):
        return None


class DeepBrowser(FakeBrowser):
    def __init__(self, page):
        self.page = page

    async def get(self, _url):
        return self.page


async def _no_wait():
    return None


async def _fake_collector(_page, _suburb, on_page=None):
    if on_page:
        on_page(1)
    return [
        "https://example.test/agent/shared-1",
        "https://example.test/agent/new-2",
    ]


async def _fake_extract(_page, url, suburb_hint=""):
    return {
        "name": url.rsplit("/", 1)[-1],
        "profile_url": url,
        "suburb": suburb_hint.split(",", 1)[0],
    }


def test_resume_dedupes_within_each_suburb_only():
    alpha = "Alpha, New South Wales 2000"
    beta = "Beta, New South Wales 2001"
    recovered = [{
        "name": "shared",
        "profile_url": "https://example.test/agent/shared-1",
        "suburb": "Alpha",
        "postcode": "2000",
        "_suburb_query": alpha,
    }]
    saved = []
    events = []

    with (
        patch.object(pipeline, "create_browser", new=lambda **_kwargs: _async_value(FakeBrowser())),
        patch.object(pipeline, "search_suburb", new=_search_ok),
        patch.object(pipeline, "collect_agent_profile_urls", new=_fake_collector),
        patch.object(pipeline, "extract_agent_record", new=_fake_extract),
        patch.object(pipeline, "_human_pause", new=_no_wait),
    ):
        all_records, report = asyncio.run(
            pipeline._scrape_suburbs_async(
                [alpha, beta],
                records=recovered,
                on_record=lambda suburb, row: saved.append((suburb, row["profile_url"])),
                on_checkpoint=lambda rows, entries: events.append((len(rows), len(entries))),
            )
        )

    assert len(all_records) == 4
    assert all(row["status"] == "completed" for row in report)
    assert len([r for r in all_records if r["_suburb_query"] == alpha]) == 2
    assert len([r for r in all_records if r["_suburb_query"] == beta]) == 2
    assert len(saved) == 3
    assert events[-1] == (4, 2)


def test_deep_search_groups_team_members_under_matching_primary_agent():
    page = DeepPage()
    saved = []

    async def create_browser(**_kwargs):
        return DeepBrowser(page)

    async def collect(_page, _location, on_page=None):
        if on_page:
            on_page(1)
        return ["https://example.test/agent/primary-1"]

    async def extract(_page, url, suburb_hint=""):
        return {
            "name": "Primary" if "primary" in url else "Team Member",
            "profile_url": url,
            "job_title": "Sales Agent",
            "agency_url": "https://www.realestate.com.au/agency/example-ABCD",
            "suburb": suburb_hint,
        }

    with (
        patch.object(pipeline, "create_browser", new=create_browser),
        patch.object(pipeline, "search_location", new=_search_location_ok),
        patch.object(pipeline, "collect_agent_profile_urls", new=collect),
        patch.object(pipeline, "extract_agent_record", new=extract),
        patch.object(pipeline, "_human_pause", new=_no_wait),
    ):
        records, report = asyncio.run(
            pipeline._scrape_suburbs_async(
                ["Darwin City | Sales Agent | deep-search"],
                use_location_search=True,
                search_terms={"Darwin City | Sales Agent | deep-search": "Darwin City"},
                designation="Sales Agent",
                deep_search=True,
                on_record=lambda _key, row: saved.append(row),
            )
        )

    assert [row["record_type"] for row in records] == ["Primary agent", "Team member"]
    assert records[1]["primary_agent"] == "Primary"
    assert records[1]["primary_agent_url"].endswith("primary-1")
    assert records[1]["designation_confidence"] == ""
    assert len(saved) == 2
    assert report[0]["status"] == "completed"


def test_all_designations_still_respects_max_rows():
    query = "Aspley | all | area-specific"
    with (
        patch.object(pipeline, "create_browser", new=lambda **_kwargs: _async_value(FakeBrowser())),
        patch.object(pipeline, "search_suburb", new=_search_ok),
        patch.object(pipeline, "collect_agent_profile_urls", new=_fake_collector),
        patch.object(pipeline, "extract_agent_record", new=_fake_extract),
        patch.object(pipeline, "_human_pause", new=_no_wait),
    ):
        records, report = asyncio.run(
            pipeline._scrape_suburbs_async(
                [query],
                designation="all",
                max_rows=1,
            )
        )

    assert len(records) == 1
    assert records[0]["_suburb_query"] == query
    assert report[0]["status"] == "partial"
    assert report[0]["error"] == "max_rows_reached:1"


async def _async_value(value):
    return value


async def _search_ok(_page, _suburb):
    return True


async def _search_location_ok(_page, _location):
    return "Darwin City, Northern Territory 0800"


if __name__ == "__main__":
    test_resume_dedupes_within_each_suburb_only()
    test_deep_search_groups_team_members_under_matching_primary_agent()
    test_all_designations_still_respects_max_rows()
    print("Pipeline resume test passed.")
