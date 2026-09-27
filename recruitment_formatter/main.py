#!/usr/bin/env python3
"""
Recruitment Data Formatter — CLI entry point.

Usage:
    python main.py SOURCE_DIR DEST_DIR MODE [options]

MODE is one of: excel, json, zoho

Examples:
    # Convert every file in ./raw_exports into clean Excel files in ./clean
    python main.py ./raw_exports ./clean excel

    # Same, but as JSON (CRM/API-ready shape)
    python main.py ./raw_exports ./clean json

    # Convert AND push straight into Zoho CRM (also writes JSON copies to DEST_DIR
    # so you have an audit trail of exactly what was sent)
    python main.py ./raw_exports ./clean zoho

    # Combine one file per source file (default) or merge all into one output file
    python main.py ./raw_exports ./clean excel --merge

Exit codes:
    0 = all files processed without error
    1 = one or more files failed (see logs/formatter.log and console summary)
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path

from formatter.core import discover_source_files, normalize_file
from formatter.writers import write_excel, write_json, records_to_zoho_payload

VALID_MODES = ("excel", "json", "zoho")


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "formatter.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize jumbled recruitment Excel exports into a consistent schema.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("source", type=Path, help="Folder containing raw source files (.xlsx/.xls/.csv)")
    parser.add_argument("destination", type=Path, help="Folder to write converted files into")
    parser.add_argument("mode", choices=VALID_MODES, help="Output mode: excel, json, or zoho")
    parser.add_argument(
        "--merge", action="store_true",
        help="Combine all source files into a single output file instead of one-per-file",
    )
    parser.add_argument(
        "--zoho-module", default=None,
        help="Override the Zoho CRM module to push into (default: config.ZOHO_MODULE)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="In zoho mode: normalize and write JSON audit files but skip the actual API push",
    )
    return parser.parse_args()


def process_one_file(path: Path, dest_dir: Path, mode: str, merge_records: list | None) -> tuple[int, dict]:
    """Returns (rows_out, report_dict). Appends to merge_records if merging."""
    records, report = normalize_file(path)

    if merge_records is not None:
        merge_records.extend(records)
    else:
        stem = path.stem
        if mode == "excel":
            write_excel(records, dest_dir / f"{stem}.xlsx")
        elif mode in ("json", "zoho"):
            # zoho mode also writes a JSON audit copy per file
            write_json(records, dest_dir / f"{stem}.json")

    return report.rows_out, {
        "file": str(path.name),
        "rows_in": report.rows_in,
        "rows_out": report.rows_out,
        "unmatched_headers": report.unmatched_headers,
        "matched_headers": report.matched_headers,
    }


def main() -> int:
    args = parse_args()
    setup_logging(Path("logs"))
    logger = logging.getLogger("formatter.main")

    if not args.source.is_dir():
        logger.error("Source folder does not exist or is not a directory: %s", args.source)
        return 1
    args.destination.mkdir(parents=True, exist_ok=True)

    files = discover_source_files(args.source)
    if not files:
        logger.warning("No supported files (.xlsx/.xls/.csv) found in %s", args.source)
        return 0

    logger.info("Found %d source file(s). Mode=%s Merge=%s", len(files), args.mode, args.merge)

    all_reports = []
    merge_records: list | None = [] if args.merge else None
    failures = 0

    for path in files:
        try:
            rows_out, rep = process_one_file(path, args.destination, args.mode, merge_records)
            all_reports.append(rep)
            logger.info(
                "OK  %-40s rows_in=%-4d rows_out=%-4d unmatched_headers=%s",
                path.name, rep["rows_in"], rows_out, rep["unmatched_headers"] or "none",
            )
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
            failures += 1
            logger.error("FAIL %s -> %s", path.name, exc, exc_info=True)
            all_reports.append({"file": str(path.name), "error": str(exc)})

    # Write merged output if requested
    if args.merge and merge_records is not None:
        out_stem = "merged_output"
        if args.mode == "excel":
            write_excel(merge_records, args.destination / f"{out_stem}.xlsx")
        else:
            write_json(merge_records, args.destination / f"{out_stem}.json")
        logger.info("Wrote merged output with %d total rows.", len(merge_records))

    # Zoho push
    if args.mode == "zoho":
        records_for_zoho = merge_records if args.merge else _reload_all_json(args.destination, files)
        zoho_payload = records_to_zoho_payload(records_for_zoho)

        if args.dry_run:
            logger.info("[DRY RUN] Skipping Zoho push. %d record(s) would have been sent.", len(zoho_payload))
        else:
            from formatter.zoho_client import ZohoClient
            from formatter.config import ZOHO_MODULE
            client = ZohoClient()
            summary = client.upsert_records(zoho_payload, module=args.zoho_module or ZOHO_MODULE)
            (args.destination / "_zoho_push_summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
            if summary["failed"]:
                failures += 1

    # Write a run summary alongside the outputs for auditability
    summary_path = args.destination / "_run_summary.json"
    summary_path.write_text(json.dumps(all_reports, indent=2), encoding="utf-8")
    logger.info("Run summary written to %s", summary_path)

    if failures:
        logger.error("Completed with %d failure(s). See logs/formatter.log", failures)
        return 1

    logger.info("All files processed successfully.")
    return 0


def _reload_all_json(dest_dir: Path, files: list[Path]) -> list[dict]:
    """When not merging, per-file JSON audit copies were written to disk during
    processing (mode=zoho always writes them) — reload and flatten them for
    a single combined Zoho push."""
    combined: list[dict] = []
    for path in files:
        json_path = dest_dir / f"{path.stem}.json"
        if json_path.exists():
            combined.extend(json.loads(json_path.read_text(encoding="utf-8")))
    return combined


if __name__ == "__main__":
    sys.exit(main())
