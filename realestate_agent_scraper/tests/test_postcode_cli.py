"""CLI location parsing tests (no browser/network)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "recruitment_formatter"))
sys.path.insert(0, str(ROOT))

from main import _locations_for_input, parse_args  # noqa: E402


def test_location_designation_mode_and_output_arguments():
    with patch.object(sys, "argv", ["main.py", "0800", "Sales Agent", "deep-search", "C:/scraped"]):
        args = parse_args()
    assert args.location == "0800"
    assert str(args.output) == "C:\\scraped"
    assert args.designation == "Sales Agent"
    assert args.mode == "deep-search"
    assert _locations_for_input(args.location, args.input) == [
        "Darwin City, Northern Territory 0800"
    ]


if __name__ == "__main__":
    test_location_designation_mode_and_output_arguments()
    print("Location/designation/mode CLI test passed.")
