"""
Loads the list of suburbs to search, from:
  - a .txt file, one suburb per line
  - an .xlsx/.xls/.csv file with a column named "suburb" (case-insensitive),
    or just the first column if no such header exists
  - a .json file, in any of these shapes:
      ["Rothwell", "Redcliffe", "Kippa-Ring"]
      [{"suburb": "Rothwell", "state": "QLD", "postcode": "4022"}, ...]
      {"suburbs": ["Rothwell", "Redcliffe"]}
      {"suburbs": [{"suburb": "Rothwell", ...}, ...]}

Each entry may optionally include state/postcode for a more precise search,
e.g. "Rothwell, QLD 4022" — everything after the first comma is kept as
supplementary context but the suburb name alone drives the search box.
"""
from __future__ import annotations
import json
from pathlib import Path

import pandas as pd

# Keys checked (in order) when a JSON entry is an object rather than a plain
# string, so common naming variants ("name", "suburb_name", etc.) still work.
_JSON_SUBURB_KEYS = ("suburb", "suburbs", "name", "suburb_name", "town", "location")


def _suburb_from_json_entry(entry) -> str | None:
    if isinstance(entry, str):
        return entry.strip() or None
    if isinstance(entry, dict):
        for key in _JSON_SUBURB_KEYS:
            if key in entry and str(entry[key]).strip():
                value = str(entry[key]).strip()
                # Append state/postcode as supplementary context if present,
                # matching the "Suburb, STATE POSTCODE" convention used for
                # txt/Excel input.
                extras = [str(entry[k]).strip() for k in ("state", "postcode") if entry.get(k)]
                return f"{value}, {' '.join(extras)}" if extras else value
    return None


def _load_json_suburbs(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))

    # Unwrap {"suburbs": [...]} to the inner list, if that's the shape used
    if isinstance(data, dict):
        for key in ("suburbs", "suburb", "data", "items"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            # dict of {suburb_name: <anything>} — use the keys
            data = list(data.keys())

    if not isinstance(data, list):
        raise ValueError(
            f"Unrecognized JSON structure in {path}. Expected a list of suburb "
            "names/objects, or a dict with a 'suburbs' key containing that list."
        )

    suburbs = []
    for entry in data:
        s = _suburb_from_json_entry(entry)
        if s:
            suburbs.append(s)
    return suburbs


def load_suburbs(path: Path) -> list[str]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Suburb list not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".txt":
        lines = path.read_text(encoding="utf-8").splitlines()
        suburbs = [line.strip() for line in lines if line.strip()]
    elif suffix == ".json":
        suburbs = _load_json_suburbs(path)
    else:
        df = pd.read_excel(path) if suffix in (".xlsx", ".xls") else pd.read_csv(path)
        col = None
        for c in df.columns:
            if str(c).strip().lower() in ("suburb", "suburbs"):
                col = c
                break
        if col is None:
            col = df.columns[0]
        suburbs = [str(v).strip() for v in df[col].dropna().tolist() if str(v).strip()]

    # de-duplicate while preserving order
    seen = set()
    deduped = []
    for s in suburbs:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(s)
    return deduped
