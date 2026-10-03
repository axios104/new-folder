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
    def __init__(self):
        self.visited_urls = []

    async def get(self, url):
        self.visited_urls.append(url)
        return self

    async def get_content(self):
        return (
            '<div id="TeamMembers">'
            '<a href="/agent/1">Primary in team roster</a>'
            '<a href="/agent/member-3">Team Member Two</a>'
            '</div>'
        )


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
    query = "Darwin City | Sales Agent | deep-search"
    recovered_primary = {
        "name": "Primary",
        "profile_url": "https://example.test/agent/primary-1",
        "job_title": "Sales Agent",
        "agency_url": "https://www.realestate.com.au/agency/example-ABCD",
        "suburb": "Darwin City",
        "_suburb_query": query,
        "record_type": "Primary agent",
        "primary_agent": "Primary",
        "primary_agent_url": "https://example.test/agent/primary-1",
    }

    async def create_browser(**_kwargs):
        return DeepBrowser(page)

    async def collect(_page, _location, on_page=None):
        if on_page:
            on_page(1)
        return [
            "https://example.test/agent/primary-1",
            "https://example.test/agent/primary-2",
        ]

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
                [query],
                records=[recovered_primary],
                use_location_search=True,
                search_terms={query: "Darwin City"},
                designation="Sales Agent",
                deep_search=True,
                on_record=lambda _key, row: saved.append(row),
            )
        )

    assert [row["record_type"] for row in records] == [
        "Primary agent", "Team member", "Primary agent"
    ]
    assert records[1]["primary_agent"] == "Primary"
    assert records[1]["primary_agent_url"].endswith("primary-1")
    assert records[1]["designation_confidence"] == ""
    assert len({row["profile_url"] for row in saved}) == 3
    assert len({pipeline._record_dedupe_key(row) for row in records}) == len(records)
    assert records[0]["_deep_search_complete"] is True
    assert sum("/agency/" in url for url in page.visited_urls) == 1
    assert report[0]["status"] == "completed"


def test_deep_search_skips_primary_whose_team_was_checkpointed_complete():
    query = "Darwin City | all | deep-search"
    completed = {
        "name": "Already Scraped",
        "profile_url": "https://example.test/agent/already-1",
        "suburb": "Darwin City",
        "_suburb_query": query,
        "record_type": "Primary agent",
        "_deep_search_complete": True,
    }
    page = DeepPage()

    async def collect(_page, _location, on_page=None):
        if on_page:
            on_page(1)
        return [completed["profile_url"]]

    async def unexpected_extract(*_args, **_kwargs):
        raise AssertionError("A completed primary agent must be skipped on resume")

    with (
        patch.object(pipeline, "create_browser", new=lambda **_kwargs: _async_value(DeepBrowser(page))),
        patch.object(pipeline, "search_location", new=_search_location_ok),
        patch.object(pipeline, "collect_agent_profile_urls", new=collect),
        patch.object(pipeline, "extract_agent_record", new=unexpected_extract),
        patch.object(pipeline, "_human_pause", new=_no_wait),
    ):
        records, report = asyncio.run(
            pipeline._scrape_suburbs_async(
                [query],
                records=[completed],
                use_location_search=True,
                search_terms={query: "Darwin City"},
                designation="all",
                deep_search=True,
            )
        )

    assert records == [completed]
    assert report[0]["status"] == "completed"
    assert page.visited_urls == []


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
    test_deep_search_skips_primary_whose_team_was_checkpointed_complete()
    test_all_designations_still_respects_max_rows()
    print("Pipeline resume test passed.")
