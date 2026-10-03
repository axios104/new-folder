"""Durable per-suburb progress and record journals for resumable scrapes."""
from __future__ import annotations

import json
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from scraper.html_fields import (
    agent_profile_identity,
    clean_agent_name,
    clean_job_title,
    clean_years_experience,
    parse_team_member_summary,
    split_suburb_and_postcode,
)

logger = logging.getLogger("scraper.progress")

_CARD_FIELDS = ("job_title", "rating", "reviews", "properties_sold", "median_sold_price")


def _normalize_checkpoint_record(record: dict) -> tuple[dict, set[str]]:
    """Repair older checkpoints that stored an entire team-card summary as Name."""
    normalized = dict(record)
    parsed = parse_team_member_summary(str(record.get("name") or ""))
    name = clean_agent_name(str(record.get("name") or ""), str(record.get("profile_url") or ""))
    normalized["name"] = name
    title = clean_job_title(str(record.get("job_title") or "")) or str(parsed.get("job_title") or "")
    if title:
        normalized["job_title"] = title
    if "years_experience" in record:
        normalized["years_experience"] = clean_years_experience(record.get("years_experience"))
    card_fields = set()
    for field in ("rating", "reviews", "properties_sold", "median_sold_price"):
        if parsed.get(field) not in (None, ""):
            normalized[field] = parsed[field]
            card_fields.add(field)
    if parsed.get("job_title") and not record.get("job_title"):
        card_fields.add("job_title")
    return normalized, card_fields


def _merge_duplicate_records(
    preferred: dict,
    secondary: dict,
    preferred_card_fields: set[str],
    secondary_card_fields: set[str],
) -> tuple[dict, set[str]]:
    merged = dict(preferred)
    merged_card_fields = preferred_card_fields | secondary_card_fields
    for field, value in secondary.items():
        if field.startswith("_") or field in {"record_type", "primary_agent", "primary_agent_url", "profile_url"}:
            continue
        if field in preferred_card_fields:
            continue
        if field in secondary_card_fields or merged.get(field) in (None, ""):
            if value not in (None, "") or field in secondary_card_fields:
                merged[field] = value
    return merged, merged_card_fields


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProgressStore:
    """Keep a status manifest and append-only record journal for each suburb."""

    def __init__(self, destination: Path) -> None:
        self.destination = Path(destination)
        self.destination.mkdir(parents=True, exist_ok=True)
        self.journal_dir = self.destination / ".checkpoints"
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.destination / "_scrape_progress.json"
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            self.suburbs: dict[str, dict] = payload.get("suburbs", {})
        except (OSError, json.JSONDecodeError, AttributeError):
            self.suburbs = {}

    @staticmethod
    def filename_stem(suburb: str) -> str:
        if " | " in suburb:
            stem = re.sub(r"[^a-z0-9]+", "_", suburb.lower()).strip("_") or "search"
            if len(stem) > 120:
                suffix = hashlib.sha1(suburb.encode("utf-8")).hexdigest()[:8]
                stem = f"{stem[:110].rstrip('_')}_{suffix}"
            return stem
        name, postcode = split_suburb_and_postcode(suburb)
        stem = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "suburb"
        if postcode:
            stem = f"{stem}_{postcode}"
        return stem

    def output_path(self, suburb: str, mode: str = "excel") -> Path:
        extension = "xlsx" if mode == "excel" else "json"
        return self.destination / f"{self.filename_stem(suburb)}.{extension}"

    def journal_path(self, suburb: str) -> Path:
        return self.journal_dir / f"{self.filename_stem(suburb)}.jsonl"

    def status(self, suburb: str) -> str:
        return str(self.suburbs.get(suburb, {}).get("status", "pending"))

    def register(self, suburb_names: list[str]) -> None:
        changed = False
        for suburb in suburb_names:
            if suburb not in self.suburbs:
                self.suburbs[suburb] = {
                    "status": "pending",
                    "profiles_found": 0,
                    "records_scraped": 0,
                    "profiles_failed": 0,
                    "output_file": self.output_path(suburb).name,
                }
                changed = True
        if changed:
            self._write_manifest()

    def _write_manifest(self) -> None:
        payload = {
            "updated_at": _timestamp(),
            "total_suburbs": len(self.suburbs),
            "suburbs": self.suburbs,
        }
        temp = self.manifest_path.with_name("_scrape_progress.tmp.json")
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(self.manifest_path)

    def update(self, suburb: str, **fields) -> None:
        row = self.suburbs.setdefault(suburb, {})
        row.update(fields)
        row["updated_at"] = _timestamp()
        row.setdefault("output_file", self.output_path(suburb).name)
        self._write_manifest()

    def append_record(self, suburb: str, record: dict) -> None:
        path = self.journal_path(suburb)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def load_records(self, suburb: str, limit: int | None = None) -> list[dict]:
        path = self.journal_path(suburb)
        if not path.exists():
            return []
        records: list[dict] = []
        indexes_by_profile: dict[str, int] = {}
        card_fields_by_profile: dict[str, set[str]] = {}
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Ignoring incomplete checkpoint line %d in %s", line_number, path)
                    continue
                if not isinstance(record, dict):
                    continue
                record, card_fields = _normalize_checkpoint_record(record)
                if not record.get("name"):
                    logger.warning("Ignoring checkpoint row with no trustworthy agent name in %s", path)
                    continue
                identity = agent_profile_identity(record.get("profile_url", ""))
                if not identity:
                    records.append(record)
                    continue
                previous_index = indexes_by_profile.get(identity)
                if previous_index is None:
                    indexes_by_profile[identity] = len(records)
                    records.append(record)
                    card_fields_by_profile[identity] = card_fields
                else:
                    previous = records[previous_index]
                    previous_card_fields = card_fields_by_profile.get(identity, set())
                    previous_is_primary = previous.get("record_type") != "Team member"
                    current_is_primary = record.get("record_type") != "Team member"
                    if current_is_primary and not previous_is_primary:
                        preferred, secondary = record, previous
                        preferred_fields, secondary_fields = card_fields, previous_card_fields
                    elif previous_is_primary and not current_is_primary:
                        preferred, secondary = previous, record
                        preferred_fields, secondary_fields = previous_card_fields, card_fields
                    else:
                        # Latest checkpoint of the same role has fresh fields.
                        preferred, secondary = record, previous
                        preferred_fields, secondary_fields = card_fields, previous_card_fields
                    merged, merged_card_fields = _merge_duplicate_records(
                        preferred, secondary, preferred_fields, secondary_fields
                    )
                    records[previous_index] = merged
                    card_fields_by_profile[identity] = merged_card_fields
        return records[:limit] if limit is not None and limit > 0 else records

    def record_count(self, suburb: str) -> int:
        return len(self.load_records(suburb))
