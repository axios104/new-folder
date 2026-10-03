from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.navigator import _normalise_suggestion_label  # noqa: E402
from scraper.html_fields import split_suburb_and_postcode  # noqa: E402


def test_suggestion_label_is_used_as_suburb_and_postcode():
    label = _normalise_suggestion_label("Aspley QLD 4034")
    assert label == "Aspley, QLD 4034"
    assert split_suburb_and_postcode(label) == ("Aspley", "4034")


if __name__ == "__main__":
    test_suggestion_label_is_used_as_suburb_and_postcode()
    print("Location suggestion test passed.")
