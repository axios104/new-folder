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


class WorkbookLockedError(RuntimeError):
    """Raised when a workbook cannot be safely replaced on Windows."""


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
    parser.add_argument("--max-rows", type=int, help="Override the configured maximum workbook data rows; 0 means unlimited")
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
    args.max_rows = args.max_rows if args.max_rows is not None else int(settings.get("max_rows", 200))
    args.row_limit_action = str(settings.get("row_limit_action", "prompt")).strip().lower()
    if args.max_rows < 0:
        parser.error("max_rows must be zero (unlimited) or a positive integer")
    if args.row_limit_action not in {"prompt", "new-file", "append", "exit"}:
        parser.error("row_limit_action must be 'prompt', 'new-file', 'append', or 'exit'")
    return args


def _query_key(location: str, designation: str, mode: str) -> str:
    return f"{location} | {designation} | {mode}"


def _records_for(records: list[dict], query_key: str) -> list[dict]:
    return [row for row in records if row.get("_suburb_query") == query_key]


def _save_query(
    store: ProgressStore,
    records: list[dict],
    query_key: str,
    logger: logging.Logger,
    max_rows: int | None = 200,
) -> Path:
    subset = _records_for(records, query_key)
    chunks = [subset] if not max_rows else [subset[index:index + max_rows] for index in range(0, len(subset), max_rows)]
    if not chunks:
        chunks = [[]]
    try:
        path: Path | None = None
        stem = store.filename_stem(query_key)
        for index, chunk in enumerate(chunks, 1):
            chunk_stem = stem if index == 1 else f"{stem}_part_{index:03d}"
            path = write_output(chunk, store.destination, "excel", chunk_stem)
    except PermissionError as exc:
        raise WorkbookLockedError(str(exc)) from exc
    assert path is not None
    logger.info("Saved %d row(s) across %d workbook(s); latest: %s", len(subset), len(chunks), path.resolve())
    return path


def _row_limit_choice(configured: str, max_rows: int, logger: logging.Logger) -> str:
    """Get the operator's choice only when a workbook boundary is reached."""
    if configured != "prompt":
        return configured
    if not sys.stdin.isatty():
        logger.info("Row limit reached without an interactive console; stopping safely.")
        return "exit"
    while True:
        answer = input(
            f"Reached {max_rows} rows. Choose [N]ew Excel file and continue, "
            "[A]ppend to the current Excel file, or [E]xit: "
        ).strip().lower()
        if answer in {"n", "new", "new-file"}:
            return "new-file"
        if answer in {"a", "append"}:
            return "append"
        if answer in {"e", "exit", ""}:
            return "exit"
        print("Enter N, A, or E.")


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
    try:
        for key in pending:
            recovered = store.load_records(key)
            for row in recovered:
                row.setdefault("_suburb_query", key)
            records.extend(recovered)
            if recovered:
                path = _save_query(store, records, key, logger, args.max_rows or None)
                store.update(key, status="in_progress", records_scraped=len(recovered), output_file=path.name)
                logger.info("Resuming %s with %d saved row(s).", query_to_location[key], len(recovered))
    except WorkbookLockedError as exc:
        logger.error("%s Saved checkpoint data is intact; close the workbook and rerun python main.py to resume.", exc)
        return 2

    def on_record(query_key: str, record: dict) -> None:
        store.append_record(query_key, record)
        count = len(_records_for(records, query_key))
        if count % 10 == 0:
            path = _save_query(store, records, query_key, logger, rows_per_workbook)
            store.update(query_key, status="in_progress", records_scraped=count, output_file=path.name)

    def on_checkpoint(rows: list[dict], report: list[dict]) -> None:
        for item in report:
            key = item.get("suburb")
            if key not in query_to_location:
                continue
            count = len(_records_for(rows, key))
            state = item.get("status") or ("failed" if item.get("error") else "completed")
            path = _save_query(store, rows, key, logger, rows_per_workbook)
            store.update(
                key, status=state, profiles_found=item.get("profiles_found", 0),
                records_scraped=count, profiles_failed=item.get("profiles_failed", 0),
                pages_scraped=item.get("pages_scraped", 0), last_error=item.get("error"),
                output_file=path.name,
            )

    rows_per_workbook = args.max_rows or None
    active_row_limit = args.max_rows or None
    try:
        while True:
            report: list[dict] = []
            scrape_suburbs(
                pending,
                headless=args.headless,
                records=records,
                report=report,
                on_checkpoint=on_checkpoint,
                on_record=on_record,
                max_agents=args.max_agents or None,
                designation=args.designation,
                deep_search=args.mode == "deep-search",
                use_location_search=True,
                search_terms={key: query_to_location[key] for key in pending},
                fallback_terms={key: fallback_location for key in pending if fallback_location},
                max_rows=active_row_limit,
            )
            reached_limit = bool(active_row_limit) and any(
                item.get("error") == f"max_rows_reached:{active_row_limit}" for item in report
            )
            if not reached_limit:
                break
            choice = _row_limit_choice(args.row_limit_action, rows_per_workbook or active_row_limit, logger)
            if choice == "exit":
                logger.info("Stopping at the workbook boundary. Run python main.py to resume later.")
                break
            if choice == "append":
                active_row_limit = None
                rows_per_workbook = None
                logger.info("Continuing in the existing workbook without a row cap.")
            else:
                active_row_limit += args.max_rows
                logger.info("Continuing in a new workbook after row %d.", active_row_limit - args.max_rows)
            for key in pending:
                store.update(key, status="in_progress")
        for key in pending:
            count = len(_records_for(records, key))
            path = _save_query(store, records, key, logger, rows_per_workbook)
            status = store.status(key)
            if status in {"pending", "in_progress"}:
                status = "partial"
            store.update(key, status=status, records_scraped=count, output_file=path.name)
    except KeyboardInterrupt:
        logger.info("Ctrl+C detected. Saving collected rows and checkpoints.")
        for key in pending:
            count = len(_records_for(records, key))
            try:
                path = _save_query(store, records, key, logger, rows_per_workbook)
                store.update(key, status="interrupted", records_scraped=count, output_file=path.name)
            except WorkbookLockedError as exc:
                logger.error(
                    "%s The journal is saved; close the workbook and rerun python main.py to resume.",
                    exc,
                )
                store.update(key, status="interrupted", records_scraped=count, last_error=str(exc))
                return 2
    except WorkbookLockedError as exc:
        logger.error("%s Checkpoint data is intact; close the workbook and rerun python main.py.", exc)
        for key in pending:
            count = len(_records_for(records, key))
            store.update(key, status="partial", records_scraped=count, last_error=str(exc))
        return 2

    for key in pending:
        logger.info("Progress for %s: %s; workbook: %s", query_to_location[key], store.status(key), store.output_path(key).resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
