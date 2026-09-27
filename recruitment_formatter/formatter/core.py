"""
Core normalization pipeline:
    read source file -> map headers -> clean values -> canonical records

A "canonical record" is a dict keyed by FieldSpec.key, covering every field
in SCHEMA (missing ones filled with MISSING_VALUE), in schema order.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import SCHEMA, MISSING_VALUE
from .cleaners import clean_value
from .header_mapper import map_headers

logger = logging.getLogger("formatter")

SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv"}


@dataclass
class FileReport:
    source_file: str
    rows_in: int = 0
    rows_out: int = 0
    unmatched_headers: list[str] = field(default_factory=list)
    matched_headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None


def _read_any(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=True)
    # .xlsx / .xls — force everything to string on read. Without this,
    # pandas auto-infers dtypes and silently strips leading zeros from
    # all-digit text (AU mobile numbers like "0402934011", postcodes like
    # "0800"), turning them into wrong numbers before cleaners.py ever
    # sees them. Cleaners re-parse numeric fields from string anyway, so
    # this costs nothing and prevents real data corruption.
    return pd.read_excel(path, dtype=str, engine=None)


def normalize_file(path: Path) -> tuple[list[dict], FileReport]:
    """
    Reads one source file and returns (records, report).
    Never raises for row-level or header-level problems — only for
    totally unreadable files (corrupt/wrong format), which are caught
    by the caller.
    """
    report = FileReport(source_file=str(path))
    df = _read_any(path)
    df = df.dropna(how="all")  # drop fully blank rows (common in exports)
    report.rows_in = len(df)

    raw_headers = [str(c) for c in df.columns]
    mapping = map_headers(raw_headers)
    report.unmatched_headers = mapping.unmatched
    report.matched_headers = mapping.matched

    if mapping.unmatched:
        logger.warning(
            "%s: %d header(s) could not be mapped and were dropped: %s",
            path.name, len(mapping.unmatched), mapping.unmatched,
        )

    # Build reverse lookup: field key -> source column name (first match wins)
    key_to_source_col = {v: k for k, v in mapping.matched.items()}

    records: list[dict] = []
    for _, row in df.iterrows():
        record = {}
        for spec in SCHEMA:
            src_col = key_to_source_col.get(spec.key)
            raw_value = row[src_col] if src_col is not None else MISSING_VALUE
            record[spec.key] = clean_value(spec.dtype, raw_value)
        # Skip rows that are entirely empty after cleaning (junk rows)
        if any(v != MISSING_VALUE and v != "" for v in record.values()):
            records.append(record)

    report.rows_out = len(records)
    return records, report


def discover_source_files(source_dir: Path) -> list[Path]:
    files = [
        p for p in sorted(source_dir.iterdir())
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and not p.name.startswith("~$")  # skip Excel lock files
    ]
    return files
