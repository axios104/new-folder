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
        first = {"profile_url": "https://example.test/agent/one", "name": "One"}
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
            json.dumps({"profile_url": "https://example.test/agent/ok"}) + "\n{partial",
            encoding="utf-8",
        )
        assert len(store.load_records(suburb)) == 1


if __name__ == "__main__":
    test_journal_restores_and_deduplicates_profiles()
    test_incomplete_final_line_is_ignored()
    print("All progress-store tests passed.")
