#!/usr/bin/env python3
"""
Realestate.com.au Agent Scraper — CLI entry point.

Two interconnected subtools:
    automation/  — drives the browser: search suburb -> click through to
                   each agent's profile page (the click-path you describe)
    scraper/     — reads the fields off a loaded profile page

pipeline.py wires them together and writes output using the SAME schema/
writers as recruitment_formatter, so both tools' outputs are always in one
consistent format.

REQUIRES recruitment_formatter to be a sibling folder (see README) —
this script adds it to sys.path automatically.

Usage:
    python main.py SUBURBS_FILE DESTINATION_DIR MODE [--headless] [--merge-name NAME]

Example:
    python main.py suburbs.txt ./scraped_output excel
    python main.py suburbs.xlsx ./scraped_output json --headless
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path

# --- make the sibling recruitment_formatter package importable ---
_THIS_DIR = Path(__file__).resolve().parent
_SIBLING_FORMATTER_PROJECT = _THIS_DIR.parent / "recruitment_formatter"
if _SIBLING_FORMATTER_PROJECT.exists():
    sys.path.insert(0, str(_SIBLING_FORMATTER_PROJECT))
else:
    print(
        f"WARNING: expected recruitment_formatter at {_SIBLING_FORMATTER_PROJECT} "
        "but it wasn't found. Place both project folders side by side, or edit "
        "the path in main.py. Falling back may cause import errors.",
        file=sys.stderr,
    )

from suburb_loader import load_suburbs
from pipeline import scrape_suburbs, write_output


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automate + scrape realestate.com.au agent contact data by suburb.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("suburbs_file", type=Path, help=".txt (one per line), .json, or .xlsx/.csv suburb list")
    parser.add_argument("destination", type=Path, help="Folder to write scraped output into")
    parser.add_argument("mode", choices=("excel", "json"), help="Output format")
    parser.add_argument("--headless", action="store_true", help="Run browser headless (more detectable; off by default)")
    parser.add_argument("--merge-name", default="scraped_agents", help="Output filename stem (default: scraped_agents)")
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Max suburbs to process in this run (default: 5, a safe testing size). "
             "Pass --limit 0 to process the whole list once you've confirmed it works "
             "reliably on a small batch and have real SELECTORS configured.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    setup_logging(Path("logs"))
    logger = logging.getLogger("scraper.main")

    suburbs = load_suburbs(args.suburbs_file)
    if not suburbs:
        logger.error("No suburbs found in %s", args.suburbs_file)
        return 1

    if args.limit and len(suburbs) > args.limit:
        logger.warning(
            "Loaded %d suburb(s) but --limit is %d (default safety cap). Processing "
            "only the first %d. Pass --limit 0 to process all %d once you've verified "
            "this works reliably on a small batch.",
            len(suburbs), args.limit, args.limit, len(suburbs),
        )
        suburbs = suburbs[: args.limit]

    logger.info("Loaded %d suburb(s): %s%s", len(suburbs), suburbs[:5], " ..." if len(suburbs) > 5 else "")

    records, report = scrape_suburbs(suburbs, headless=args.headless)
    logger.info("Scraping complete: %d record(s) across %d suburb(s)", len(records), len(suburbs))

    args.destination.mkdir(parents=True, exist_ok=True)
    (args.destination / "_scrape_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not records:
        logger.warning("No records scraped — nothing written. Check logs/scraper.log and _scrape_report.json.")
        return 1

    out_path = write_output(records, args.destination, args.mode, args.merge_name)
    logger.info("Wrote %d record(s) to %s", len(records), out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
