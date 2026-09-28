#!/usr/bin/env python3
"""Suburb-by-suburb realestate.com.au agent scraper CLI."""
from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import Counter
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
        handlers=[
            logging.FileHandler(log_dir / "scraper.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _postcode(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"\d{4}", value):
        raise argparse.ArgumentTypeError("enter one four-digit Australian postcode")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape all paginated agent profiles for one Australian postcode.",
    )
    parser.add_argument(
        "postcode",
        type=_postcode,
        help="Four-digit Australian postcode; its suburb is looked up from the postcode JSON",
    )
    parser.add_argument(
        "output",
        type=Path,
        help="Folder where this postcode's workbook and resume data will be saved",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=_DEFAULT_POSTCODE_FILE,
        help=f"Australia suburb/postcode JSON (default: {_DEFAULT_POSTCODE_FILE})",
    )
    parser.add_argument("--format", choices=("excel", "json"), default="excel", help="Output format (default: excel)")
    parser.add_argument("--headless", action="store_true", help="Run Chrome without a visible window")
    parser.add_argument(
        "--max-agents",
        type=int,
        default=0,
        help="Testing cap per suburb; 0 visits every unique profile URL",
    )
    return parser.parse_args()


def _records_for(records: list[dict], suburb: str) -> list[dict]:
    return [row for row in records if row.get("_suburb_query") == suburb]


def _save_suburb(
    store: ProgressStore,
    records: list[dict],
    suburb: str,
    mode: str,
    logger: logging.Logger,
) -> Path:
    subset = _records_for(records, suburb)
    path = write_output(subset, store.destination, mode, store.filename_stem(suburb))
    logger.info("Saved %d record(s) for %s to %s", len(subset), suburb, path.resolve())
    return path


def _suburbs_for_postcode(all_suburbs: list[str], postcode: str) -> list[str]:
    return [
        suburb for suburb in all_suburbs
        if split_suburb_and_postcode(suburb)[1] == postcode
    ]


def _select_suburbs(candidates: list[str], store: ProgressStore) -> list[str]:
    return [suburb for suburb in candidates if store.status(suburb) != "completed"]


def main() -> int:
    args = parse_args()
    setup_logging(Path("logs"))
    logger = logging.getLogger("scraper.main")

    destination = args.output.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    try:
        suburbs = load_suburbs(args.input)
    except (OSError, ValueError) as exc:
        logger.error("Could not read postcode list %s: %s", args.input, exc)
        return 2
    if not suburbs:
        logger.error("No suburbs found in %s", args.input)
        return 1

    store = ProgressStore(destination)
    store.register(suburbs)
    candidates = _suburbs_for_postcode(suburbs, args.postcode)
    if not candidates:
        logger.error("Postcode %s was not found in %s", args.postcode, args.input)
        return 2
    if len(candidates) > 1:
        logger.info("Postcode %s matches %d localities; processing each one.", args.postcode, len(candidates))
    states = Counter(store.status(suburb) for suburb in suburbs)
    logger.info(
        "Loaded %d Australian suburbs; completed=%d, unfinished=%d. Progress: %s",
        len(suburbs),
        states["completed"],
        len(suburbs) - states["completed"],
        store.manifest_path.resolve(),
    )

    pending = _select_suburbs(candidates, store)
    if not pending:
        logger.info("There are no unfinished suburbs to scrape.")
        return 0

    # Recover append-only journals first. This restores records even if the
    # previous process was killed before it could refresh the Excel workbook.
    records: list[dict] = []
    for suburb in pending:
        recovered = store.load_records(suburb)
        for record in recovered:
            record.setdefault("_suburb_query", suburb)
        records.extend(recovered)
        if recovered:
            out_path = _save_suburb(store, records, suburb, args.format, logger)
            store.update(
                suburb,
                status="in_progress",
                records_scraped=len(recovered),
                output_file=out_path.name,
                last_error=None,
            )
            logger.info("Resuming %s with %d previously saved profile(s).", suburb, len(recovered))

    logger.info("This run will process %d suburb(s): %s", len(pending), pending)

    def on_record(suburb: str, record: dict) -> None:
        store.append_record(suburb, record)
        current = store.suburbs.get(suburb, {})
        current_count = int(current.get("records_scraped", 0)) + 1
        if current_count % 10 == 0:
            path = _save_suburb(store, records, suburb, args.format, logger)
            store.update(
                suburb,
                status="in_progress",
                records_scraped=current_count,
                output_file=path.name,
            )
            logger.info("Checkpoint: %d profile(s) saved for %s.", current_count, suburb)

    checkpointed_entries: dict[str, tuple] = {}

    def on_checkpoint(recs: list[dict], report: list[dict]) -> None:
        for entry in report:
            suburb = entry.get("suburb")
            if not suburb:
                continue
            count = len(_records_for(recs, suburb))
            state = entry.get("status") or ("completed" if not entry.get("error") else "failed")
            signature = (
                state,
                count,
                entry.get("profiles_found", 0),
                entry.get("profiles_failed", 0),
                entry.get("pages_scraped", 0),
                entry.get("error"),
            )
            if checkpointed_entries.get(suburb) == signature:
                continue
            path = _save_suburb(store, recs, suburb, args.format, logger)
            store.update(
                suburb,
                status=state,
                profiles_found=entry.get("profiles_found", 0),
                records_scraped=count,
                profiles_failed=entry.get("profiles_failed", 0),
                pages_scraped=entry.get("pages_scraped", 0),
                last_error=entry.get("error"),
                output_file=path.name,
            )
            checkpointed_entries[suburb] = signature
        done = sum(store.status(suburb) == "completed" for suburb in suburbs)
        logger.info("Progress: %d/%d suburbs completed.", done, len(suburbs))

    try:
        scrape_suburbs(
            pending,
            headless=args.headless,
            records=records,
            report=[],
            on_checkpoint=on_checkpoint,
            on_record=on_record,
            max_agents=args.max_agents or None,
        )
        # Final refresh also covers interrupts raised while the browser was
        # starting or navigating, outside an individual profile request.
        for suburb in pending:
            subset = _records_for(records, suburb)
            if not subset:
                continue
            path = _save_suburb(store, records, suburb, args.format, logger)
            if store.status(suburb) != "completed":
                store.update(
                    suburb,
                    status="partial",
                    records_scraped=len(subset),
                    output_file=path.name,
                )
    except KeyboardInterrupt:
        logger.info("Ctrl+C detected. Saving all completed profile records.")
        for suburb in pending:
            subset = _records_for(records, suburb)
            if subset:
                path = _save_suburb(store, records, suburb, args.format, logger)
                store.update(
                    suburb,
                    status="interrupted",
                    records_scraped=len(subset),
                    output_file=path.name,
                )
    completed = sum(store.status(suburb) == "completed" for suburb in suburbs)
    remaining = len(suburbs) - completed
    logger.info(
        "Run ended. Completed suburbs: %d/%d; remaining: %d. Resume postcode %s by running the same command again.",
        completed,
        len(suburbs),
        remaining,
        args.postcode,
    )
    logger.info("Per-suburb workbooks and progress are in %s", destination)
    return 0


if __name__ == "__main__":
    sys.exit(main())
