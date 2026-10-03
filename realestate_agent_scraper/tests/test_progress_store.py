"""Offline tests for suburb journals and resume state."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from progress_store import ProgressStore  # noqa: E402


def test_journal_restores_and_deduplicates_profiles():
    with tempfile.TemporaryDirectory() as tmp:
        store = ProgressStore(Path(tmp))
        suburb = "Darwin City, Northern Territory 0800"
        store.register([suburb])
        store.update(suburb, status="in_progress")
        first = {
            "profile_url": "https://example.test/agent/one",
            "name": "One",
            "record_type": "Primary agent",
            "_deep_search_complete": True,
        }
        store.append_record(suburb, first)
        store.append_record(suburb, first)

        restored = ProgressStore(Path(tmp))
        assert restored.load_records(suburb) == [first]
        assert restored.status(suburb) == "in_progress"
        assert restored.output_path(suburb).name.startswith("darwin_city_0800")


def test_incomplete_final_line_is_ignored():
    with tempfile.TemporaryDirectory() as tmp:
        store = ProgressStore(Path(tmp))
        suburb = "Jingili, Northern Territory 0810"
        journal = store.journal_path(suburb)
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(
            json.dumps({"profile_url": "https://example.test/agent/ok", "name": "Ok Agent"}) + "\n{partial",
            encoding="utf-8",
        )
        assert len(store.load_records(suburb)) == 1


def test_numeric_and_slug_profile_urls_restore_as_one_primary_record():
    with tempfile.TemporaryDirectory() as tmp:
        store = ProgressStore(Path(tmp))
        suburb = "Aspley 4034"
        store.register([suburb])
        team = {
            "profile_url": "https://www.realestate.com.au/agent/3079355",
            "record_type": "Team member",
            "name": "Alexandra Porter Principal 5.0 (380 reviews)",
            "primary_agent_url": "https://www.realestate.com.au/agent/another-1",
        }
        primary = {
            "profile_url": "https://www.realestate.com.au/agent/alexandra-porter-3079355",
            "record_type": "Primary agent",
            "name": "Alexandra Porter",
        }
        store.append_record(suburb, team)
        store.append_record(suburb, primary)
        updated_primary = {**primary, "agency_name": "McGrath Estate Agents Aspley"}
        store.append_record(suburb, updated_primary)

        restored = ProgressStore(Path(tmp)).load_records(suburb)
        assert len(restored) == 1
        assert restored[0]["record_type"] == "Primary agent"
        assert restored[0]["name"] == "Alexandra Porter"
        assert restored[0]["agency_name"] == "McGrath Estate Agents Aspley"


def test_legacy_team_summary_repairs_name_title_stats_and_bad_years():
    with tempfile.TemporaryDirectory() as tmp:
        store = ProgressStore(Path(tmp))
        suburb = "Aspley 4034"
        store.register([suburb])
        primary = {
            "profile_url": "https://www.realestate.com.au/agent/alexandra-porter-3079355",
            "record_type": "Primary agent",
            "name": "Alexandra Porter",
            "years_experience": 2025,
            "median_sold_price": 8_000_000,
        }
        team = {
            "profile_url": "https://www.realestate.com.au/agent/3079355",
            "record_type": "Team member",
            "name": (
                "Alexandra Porter Principal, Lead Agent 2025 Top Agent 5.0 "
                "(380 reviews) 83 Properties sold (as lead agent) $1.21M Median sale price"
            ),
            "primary_agent_url": "https://www.realestate.com.au/agent/alexandra-porter-3079355",
        }
        store.append_record(suburb, primary)
        store.append_record(suburb, team)

        restored = ProgressStore(Path(tmp)).load_records(suburb)
        assert len(restored) == 1
        assert restored[0]["record_type"] == "Primary agent"
        assert restored[0]["name"] == "Alexandra Porter"
        assert restored[0]["job_title"] == "Principal, Lead Agent"
        assert restored[0]["years_experience"] == ""
        assert restored[0]["rating"] == "5.0"
        assert restored[0]["reviews"] == "380"
        assert restored[0]["properties_sold"] == "83"
        assert restored[0]["median_sold_price"] == 1_210_000


if __name__ == "__main__":
    test_journal_restores_and_deduplicates_profiles()
    test_incomplete_final_line_is_ignored()
    test_numeric_and_slug_profile_urls_restore_as_one_primary_record()
    test_legacy_team_summary_repairs_name_title_stats_and_bad_years()
    print("All progress-store tests passed.")
