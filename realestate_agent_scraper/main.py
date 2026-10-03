#!/usr/bin/env python3
"""Location/designation based realestate.com.au agent scraper CLI."""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_SIBLING_FORMATTER_PROJECT = _THIS_DIR.parent / "recruitment_formatter"
if _SIBLING_FORMATTER_PROJECT.exists():
    sys.path.insert(0, str(_SIBLING_FORMATTER_PROJECT))

from pipeline import scrape_suburbs, write_output
from progress_store import ProgressStore
from suburb_loader import load_suburbs
from scraper.html_fields import split_suburb_and_postcode

_DEFAULT_POSTCODE_FILE = _THIS_DIR.parent / "aus_postcode.json"
if not _DEFAULT_POSTCODE_FILE.exists():
    _DEFAULT_POSTCODE_FILE = _THIS_DIR / "aus_postcode.json"


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_dir / "scraper.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


def _location(value: str) -> str:
    value = value.strip()
    if not value:
        raise argparse.ArgumentTypeError("location cannot be empty")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find agents by location and designation; optionally include their agency team members.",
    )
    parser.add_argument("location", type=_location, help="Australian postcode or location search phrase")
    parser.add_argument("designation", help="Primary-agent title to match, or 'all' to include every title")
    parser.add_argument("mode", choices=("area-specific", "deep-search"), help="Whether to include agency team members")
    parser.add_argument("output", type=Path, help="Folder where Excel and resumable progress files are saved")
    parser.add_argument("--input", type=Path, default=_DEFAULT_POSTCODE_FILE, help="Australia postcode JSON used when LOCATION is a four-digit postcode")
    parser.add_argument("--headless", action="store_true", help="Run Chrome without a visible window")
    parser.add_argument("--max-agents", type=int, default=0, help="Optional test cap for primary profiles; 0 means no cap")
    return parser.parse_args()


def _query_key(location: str, designation: str, mode: str) -> str:
    return f"{location} | {designation} | {mode}"


def _records_for(records: list[dict], query_key: str) -> list[dict]:
    return [row for row in records if row.get("_suburb_query") == query_key]


def _save_query(store: ProgressStore, records: list[dict], query_key: str, logger: logging.Logger) -> Path:
    path = write_output(_records_for(records, query_key), store.destination, "excel", store.filename_stem(query_key))
    logger.info("Saved workbook with %d row(s): %s", len(_records_for(records, query_key)), path.resolve())
    return path


def _locations_for_input(location: str, input_file: Path) -> list[str]:
    """Expand an exact Australian postcode to its locality names when possible."""
    if not re.fullmatch(r"\d{4}", location):
        return [location]
    suburbs = load_suburbs(input_file)
    matches = [row for row in suburbs if split_suburb_and_postcode(row)[1] == location]
    return matches or [location]


def main() -> int:
    args = parse_args()
    setup_logging(_THIS_DIR / "logs")
    logger = logging.getLogger("scraper.main")
    destination = args.output.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        locations = _locations_for_input(args.location, args.input)
    except (OSError, ValueError) as exc:
        logger.error("Could not read postcode list %s: %s", args.input, exc)
        return 2
    query_to_location = {_query_key(loc, args.designation, args.mode): loc for loc in locations}
    query_keys = list(query_to_location)
    store = ProgressStore(destination)
    store.register(query_keys)
    pending = [key for key in query_keys if store.status(key) != "completed"]
    if not pending:
        logger.info("All matching location searches are already complete. Workbooks are in %s", destination)
        return 0

    records: list[dict] = []
    for key in pending:
        recovered = store.load_records(key)
        for row in recovered:
            row.setdefault("_suburb_query", key)
        records.extend(recovered)
        if recovered:
            path = _save_query(store, records, key, logger)
            store.update(key, status="in_progress", records_scraped=len(recovered), output_file=path.name)
            logger.info("Resuming %s with %d saved row(s).", query_to_location[key], len(recovered))

    def on_record(query_key: str, record: dict) -> None:
        store.append_record(query_key, record)
        count = int(store.suburbs.get(query_key, {}).get("records_scraped", 0)) + 1
        if count % 10 == 0:
            path = _save_query(store, records, query_key, logger)
            store.update(query_key, status="in_progress", records_scraped=count, output_file=path.name)

    def on_checkpoint(rows: list[dict], report: list[dict]) -> None:
        for item in report:
            key = item.get("suburb")
            if key not in query_to_location:
                continue
            count = len(_records_for(rows, key))
            state = item.get("status") or ("failed" if item.get("error") else "completed")
            path = _save_query(store, rows, key, logger)
            store.update(
                key, status=state, profiles_found=item.get("profiles_found", 0),
                records_scraped=count, profiles_failed=item.get("profiles_failed", 0),
                pages_scraped=item.get("pages_scraped", 0), last_error=item.get("error"),
                output_file=path.name,
            )

    try:
        scrape_suburbs(
            pending,
            headless=args.headless,
            records=records,
            report=[],
            on_checkpoint=on_checkpoint,
            on_record=on_record,
            max_agents=args.max_agents or None,
            designation=args.designation,
            deep_search=args.mode == "deep-search",
            use_location_search=True,
            search_terms={key: query_to_location[key] for key in pending},
        )
        for key in pending:
            count = len(_records_for(records, key))
            path = _save_query(store, records, key, logger)
            status = store.status(key)
            if status in {"pending", "in_progress"}:
                status = "partial"
            store.update(key, status=status, records_scraped=count, output_file=path.name)
    except KeyboardInterrupt:
        logger.info("Ctrl+C detected. Saving collected rows and checkpoints.")
        for key in pending:
            path = _save_query(store, records, key, logger)
            store.update(key, status="interrupted", records_scraped=len(_records_for(records, key)), output_file=path.name)

    for key in pending:
        logger.info("Progress for %s: %s; workbook: %s", query_to_location[key], store.status(key), store.output_path(key).resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
