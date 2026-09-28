"""Postcode-only CLI defaults and lookup tests (no browser/network)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "recruitment_formatter"))
sys.path.insert(0, str(ROOT))

from main import _suburbs_for_postcode, parse_args  # noqa: E402
from suburb_loader import load_suburbs  # noqa: E402


def test_postcode_only_defaults_and_lookup():
    with patch.object(sys, "argv", ["main.py", "0800", "C:/scraped"]):
        args = parse_args()
    assert args.postcode == "0800"
    assert str(args.output) == "C:\\scraped"
    assert args.format == "excel"
    entries = load_suburbs(args.input)
    assert len(entries) == 2641
    assert _suburbs_for_postcode(entries, args.postcode) == [
        "Darwin City, Northern Territory 0800"
    ]


if __name__ == "__main__":
    test_postcode_only_defaults_and_lookup()
    print("Postcode CLI test passed.")
