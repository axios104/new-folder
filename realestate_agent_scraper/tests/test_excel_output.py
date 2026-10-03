"""Excel writer tests for Requirement 3 (no live browser)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "recruitment_formatter"))

from pipeline import _clean_record, _schema_columns, write_output  # noqa: E402


def test_shared_formatter_schema_and_cleaners_are_used():
    from formatter.config import SCHEMA

    assert _schema_columns() == [(spec.key, spec.output_name) for spec in SCHEMA]
    cleaned = _clean_record({
        "years_experience": "33",
        "rating": "4.9",
        "postcode": "0800",
        "agency_url": "www.realestate.com.au/agency/example-ABCD",
    })
    assert cleaned["years_experience"] == 33
    assert cleaned["rating"] == 4.9
    assert cleaned["postcode"] == "0800"
    assert cleaned["agency_url"].startswith("https://")


def test_excel_writes_to_requested_directory():
    dest = ROOT / "tests" / "_tmp_excel_out"
    dest.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "name": "Ada Agent",
            "years_experience": "33",
            "agency_name": "Smart Real Estate - CASUARINA",
            "suburb": "Darwin City",
            "postcode": "0800",
            "rating": "4.9",
            "reviews": "22",
            "agency_url": "https://www.realestate.com.au/agency/smart-real-estate-casuarina-CBOKDJ",
            "profile_url": "https://www.realestate.com.au/agent/ada-agent-1",
            "record_type": "Primary agent",
            "primary_agent": "Ada Agent",
            "primary_agent_url": "https://www.realestate.com.au/agent/ada-agent-1",
            "designation_confidence": 1.0,
        },
        {
            "name": "No Extras",
            "suburb": "Jingili",
            "postcode": "0810",
            "profile_url": "https://www.realestate.com.au/agent/no-extras-2",
        },
    ]
    out = write_output(records, dest, "excel", "scraped_data")
    assert out == dest / "scraped_data.xlsx"
    assert out.exists()
    import pandas as pd
    df = pd.read_excel(out, dtype=str)
    assert "Years_experience" in df.columns
    assert "Agency Name" in df.columns
    assert "agency_url" in df.columns
    assert "rating" in df.columns
    assert "Reviews" in df.columns
    assert "suburbs" in df.columns
    assert "Post code" in df.columns
    assert "Record type" in df.columns
    assert "Primary agent" in df.columns
    assert df.columns.is_unique
    assert len(df.columns) == len(_schema_columns()) + 4
    assert df.iloc[0]["Record type"] == "Primary agent"
    assert df.iloc[0]["Primary agent"] == "Ada Agent"
    assert str(df.iloc[0]["suburbs"]) == "Darwin City"
    postcode = str(df.iloc[0]["Post code"]).replace(".0", "")
    assert postcode in {"0800", "800"}
    assert len(df) == 2
    print(f"PASS excel written to {out}")


def test_missing_fields_do_not_crash():
    dest = ROOT / "tests" / "_tmp_excel_out"
    dest.mkdir(parents=True, exist_ok=True)
    out = write_output([{"name": "Only Name"}], dest, "excel", "partial")
    assert out.exists()
    print(f"PASS partial excel written to {out}")


def test_empty_checkpoint_still_writes_headers():
    dest = ROOT / "tests" / "_tmp_excel_out"
    dest.mkdir(parents=True, exist_ok=True)
    out = write_output([], dest, "excel", "empty_checkpoint")
    assert out.exists()
    import pandas as pd
    df = pd.read_excel(out, dtype=str)
    assert len(df) == 0
    assert "Name" in df.columns
    print(f"PASS empty checkpoint written to {out}")


if __name__ == "__main__":
    test_shared_formatter_schema_and_cleaners_are_used()
    test_excel_writes_to_requested_directory()
    test_missing_fields_do_not_crash()
    test_empty_checkpoint_still_writes_headers()
    print("All Requirement 3 Excel unit tests passed.")
