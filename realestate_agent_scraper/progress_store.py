"""Durable per-suburb progress and record journals for resumable scrapes."""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from scraper.html_fields import split_suburb_and_postcode

logger = logging.getLogger("scraper.progress")


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

    def load_records(self, suburb: str) -> list[dict]:
        path = self.journal_path(suburb)
        if not path.exists():
            return []
        records: list[dict] = []
        seen: set[str] = set()
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Ignoring incomplete checkpoint line %d in %s", line_number, path)
                    continue
                if not isinstance(record, dict):
                    continue
                url = str(record.get("profile_url", "")).rstrip("/").lower()
                if url and url in seen:
                    continue
                if url:
                    seen.add(url)
                records.append(record)
        return records

    def record_count(self, suburb: str) -> int:
        return len(self.load_records(suburb))
