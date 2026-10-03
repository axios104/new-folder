from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.matching import designation_confidence, matches_designation  # noqa: E402


def test_designation_confidence_uses_85_percent_cutoff():
    assert designation_confidence("Senior Sales Agent", "Sales Agent") == 1.0
    assert designation_confidence("Property Manager", "Sales Agent") < 0.85
    assert designation_confidence("", "Sales Agent") == 0.0
    assert matches_designation("Sales Agent", "Sales Agent")
    assert not matches_designation("Property Manager", "Sales Agent")
    assert matches_designation("Property Manager", "all")
    assert matches_designation("", "*")


if __name__ == "__main__":
    test_designation_confidence_uses_85_percent_cutoff()
    print("Designation matching tests passed.")
