#!/usr/bin/env python3
"""Location/designation based realestate.com.au agent scraper CLI."""
from __future__ import annotations

import argparse
import json
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


_DEFAULT_SETTINGS_FILE = _THIS_DIR / "scraper_settings.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Find agents by location and designation; optionally include their agency team members.",
    )
    parser.add_argument("location", nargs="?", help="Optional override for configured location")
    parser.add_argument("designation", nargs="?", help="Optional override for configured designation")
    parser.add_argument("mode", nargs="?", choices=("area-specific", "deep-search"), help="Optional mode override")
    parser.add_argument("output", nargs="?", type=Path, help="Optional output-folder override")
    parser.add_argument("--config", type=Path, default=_DEFAULT_SETTINGS_FILE, help="Settings JSON file (default: scraper_settings.json)")
    parser.add_argument("--input", type=Path, help="Override the postcode JSON path")
    parser.add_argument("--headless", action="store_true", help="Override settings to run Chrome without a visible window")
    parser.add_argument("--max-agents", type=int, help="Override the configured profile cap; 0 means no cap")
    args = parser.parse_args()
    settings_path = args.config.expanduser().resolve()
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot load settings file {settings_path}: {exc}")
    if not isinstance(settings, dict):
        parser.error(f"settings file must contain a JSON object: {settings_path}")

    def from_settings(cli_value, key: str, fallback=None):
        return cli_value if cli_value is not None else settings.get(key, fallback)

    args.location = from_settings(args.location, "location")
    args.designation = from_settings(args.designation, "designation")
    args.mode = from_settings(args.mode, "mode")
    output_value = from_settings(args.output, "output_folder")
    input_value = from_settings(args.input, "postcode_json", str(_DEFAULT_POSTCODE_FILE))
    if not args.location or not str(args.location).strip():
        parser.error("set 'location' in the settings file or provide it as a positional argument")
    if not args.designation or not str(args.designation).strip():
        parser.error("set 'designation' in the settings file or provide it as a positional argument")
    if args.mode not in {"area-specific", "deep-search"}:
        parser.error("settings 'mode' must be 'area-specific' or 'deep-search'")
    if not output_value:
        parser.error("set 'output_folder' in the settings file or provide it as a positional argument")

    def configured_path(value) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else settings_path.parent / path

    args.location = _location(str(args.location))
    args.input = configured_path(input_value)
    args.output = configured_path(output_value)
    args.headless = bool(args.headless or settings.get("headless", False))
    args.max_agents = args.max_agents if args.max_agents is not None else int(settings.get("max_agents", 0))
    return args


def _query_key(location: str, designation: str, mode: str) -> str:
    return f"{location} | {designation} | {mode}"


def _records_for(records: list[dict], query_key: str) -> list[dict]:
    return [row for row in records if row.get("_suburb_query") == query_key]


def _save_query(store: ProgressStore, records: list[dict], query_key: str, logger: logging.Logger) -> Path:
    path = write_output(_records_for(records, query_key), store.destination, "excel", store.filename_stem(query_key))
    logger.info("Saved workbook with %d row(s): %s", len(_records_for(records, query_key)), path.resolve())
    return path


def _locations_for_input(location: str, input_file: Path) -> list[str]:
    """Keep postcode input intact so the website can choose its first suggestion."""
    if re.fullmatch(r"\d{4}", location):
        # Read the supplied list as a fallback/validation source, but do not
        # replace the postcode with its first JSON locality: postcode mappings
        # can be incomplete or ordered differently from the website's results.
        load_suburbs(input_file)
    return [location]


def _postcode_fallback(location: str, input_file: Path) -> str | None:
    if not re.fullmatch(r"\d{4}", location):
        return None
    matches = [row for row in load_suburbs(input_file) if split_suburb_and_postcode(row)[1] == location]
    return matches[0] if matches else None


def main() -> int:
    args = parse_args()
    setup_logging(_THIS_DIR / "logs")
    logger = logging.getLogger("scraper.main")
    destination = args.output.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        locations = _locations_for_input(args.location, args.input)
        fallback_location = _postcode_fallback(args.location, args.input)
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
            fallback_terms={key: fallback_location for key in pending if fallback_location},
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
