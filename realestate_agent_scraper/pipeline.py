
"""
Pipeline — connects the automation and scraper subtools (nodriver/async version).

Flow per suburb:
    create_browser()                    -> nd.Browser
    browser.get()                       -> nd.Tab
    navigator.search_suburb()           -> loads results page
    navigator.collect_agent_profile_urls()
                                        -> [profile urls]
    for each url:
        page.get(url)
        extractor.extract_agent_record()
                                        -> raw record
        formatter.cleaners.clean_value() -> cleaned per-field

    all records -> formatter.writers.write_excel / write_json
"""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path

import config

from automation.browser import create_browser
from automation.navigator import (
    search_suburb,
    collect_agent_profile_urls,
)
from scraper.extractor import extract_agent_record


logger = logging.getLogger("scraper.pipeline")


async def _human_pause() -> None:
    """
    Async delay between profile/suburb operations.
    """
    await asyncio.sleep(
        random.uniform(
            config.MIN_PROFILE_DELAY_S,
            config.MAX_PROFILE_DELAY_S,
        )
    )


def _clean_record(raw: dict) -> dict:
    """
    Runs each field through the same dtype-aware cleaners
    used by the Excel formatter.
    """
    try:
        from recruitment_formatter.formatter.config import FIELD_BY_KEY
        from recruitment_formatter.formatter.cleaners import clean_value

        cleaned = {}

        for key, value in raw.items():
            spec = FIELD_BY_KEY.get(key)

            if spec:
                cleaned[key] = clean_value(
                    spec.dtype,
                    value,
                )
            else:
                cleaned[key] = value

        return cleaned

    except ImportError:
        logger.debug(
            "formatter package not available, skipping cleaning"
        )
        return raw


async def _scrape_suburbs_async(
    suburbs: list[str],
    headless: bool = False,
) -> tuple[list[dict], list[dict]]:
    """
    Internal asynchronous scraping implementation.

    create_browser() returns an nd.Browser.

    The browser is used to obtain an nd.Tab. That tab is then passed
    to the nodriver-based navigator and extractor.
    """

    all_records: list[dict] = []
    report: list[dict] = []

    browser = None
    page = None

    try:
        # ----------------------------------------------------------
        # Start browser
        # ----------------------------------------------------------

        logger.info(
            "Starting nodriver browser (headless=%s)...",
            headless,
        )

        browser = await create_browser(
            headless=headless,
        )

        logger.info(
            "Nodriver browser started successfully."
        )

        # ----------------------------------------------------------
        # Create/get the browser tab
        # ----------------------------------------------------------

        page = await browser.get(
            config.FIND_AGENT_URL
        )

        logger.info(
            "Browser tab initialized."
        )

        # ----------------------------------------------------------
        # Process suburbs
        # ----------------------------------------------------------

        for suburb in suburbs:

            entry = {
                "suburb": suburb,
                "profiles_found": 0,
                "records_scraped": 0,
                "error": None,
            }

            try:
                logger.info(
                    "Processing suburb: %s",
                    suburb,
                )

                # --------------------------------------------------
                # Navigate to suburb
                # --------------------------------------------------

                ok = await search_suburb(
                    page,
                    suburb,
                )

                if not ok:
                    entry["error"] = "search_failed"

                    logger.warning(
                        "Search failed for suburb: %s",
                        suburb,
                    )

                    report.append(entry)
                    continue

                # --------------------------------------------------
                # Collect agent profile URLs
                # --------------------------------------------------

                profile_urls = await collect_agent_profile_urls(
                    page,
                    suburb,
                )

                if profile_urls is None:
                    profile_urls = []

                entry["profiles_found"] = len(
                    profile_urls
                )

                logger.info(
                    "Found %d agent profile(s) for '%s'.",
                    len(profile_urls),
                    suburb,
                )

                # --------------------------------------------------
                # Scrape each agent
                # --------------------------------------------------

                for url in profile_urls:

                    try:
                        logger.info(
                            "Opening agent profile: %s",
                            url,
                        )

                        # Navigate the existing nodriver tab.
                        await page.get(url)

                        await _human_pause()

                        # Extract the record.
                        raw = await extract_agent_record(
                            page,
                            url,
                            suburb_hint=suburb,
                        )

                        if not raw:
                            logger.warning(
                                "No record extracted from: %s",
                                url,
                            )
                            continue

                        # Clean record values.
                        cleaned = _clean_record(raw)

                        # Store record.
                        all_records.append(
                            cleaned
                        )

                        entry["records_scraped"] += 1

                        logger.info(
                            "Scraped: %s (%s) — %s",
                            cleaned.get("name", "?"),
                            suburb,
                            url,
                        )

                    except Exception as exc:  # noqa: BLE001

                        logger.error(
                            "Failed to scrape %s: %s",
                            url,
                            exc,
                            exc_info=True,
                        )

                    # Delay before next profile.
                    await _human_pause()

            except Exception as exc:  # noqa: BLE001

                logger.error(
                    "Suburb '%s' failed: %s",
                    suburb,
                    exc,
                    exc_info=True,
                )

                entry["error"] = str(exc)

            # Add suburb result to report.
            report.append(entry)

            logger.info(
                "Finished suburb '%s': "
                "%d profile(s) found, "
                "%d record(s) scraped.",
                suburb,
                entry["profiles_found"],
                entry["records_scraped"],
            )

            # Delay before next suburb.
            await _human_pause()

    except Exception as exc:  # noqa: BLE001

        logger.critical(
            "Browser pipeline failed: %s",
            exc,
            exc_info=True,
        )

        # Record unprocessed suburbs as failed.
        processed_suburbs = {
            item["suburb"]
            for item in report
        }

        for suburb in suburbs:

            if suburb not in processed_suburbs:

                report.append(
                    {
                        "suburb": suburb,
                        "profiles_found": 0,
                        "records_scraped": 0,
                        "error": f"browser_error: {exc}",
                    }
                )

    finally:

        # ----------------------------------------------------------
        # Stop browser
        # ----------------------------------------------------------

        if browser is not None:

            try:
                logger.info(
                    "Stopping nodriver browser..."
                )

                result = browser.stop()

                # Handle versions where stop() is awaitable.
                if asyncio.iscoroutine(result):
                    await result

                logger.info(
                    "Nodriver browser stopped."
                )

            except Exception as exc:  # noqa: BLE001

                logger.warning(
                    "Error while stopping browser: %s",
                    exc,
                )

    return all_records, report


def scrape_suburbs(
    suburbs: list[str],
    headless: bool = False,
) -> tuple[list[dict], list[dict]]:
    """
    Public synchronous entry point.

    main.py can continue calling:

        records, report = scrape_suburbs(
            suburbs,
            headless=args.headless,
        )

    The actual scraping work runs asynchronously internally.
    """

    return asyncio.run(
        _scrape_suburbs_async(
            suburbs,
            headless=headless,
        )
    )


def write_output(
    records: list[dict],
    destination: Path,
    mode: str,
    merge_filename: str = "scraped_agents",
) -> Path:
    """
    Writes scraped records using the formatter's writers if available.

    Falls back to JSON if the formatter package is unavailable.
    """

    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        from recruitment_formatter.formatter.writers import (
            write_excel,
            write_json,
        )

        if mode == "excel":

            out_path = destination / f"{merge_filename}.xlsx"

            write_excel(
                records,
                out_path,
            )

        else:

            out_path = destination / f"{merge_filename}.json"

            write_json(
                records,
                out_path,
            )

    except ImportError:

        import json

        out_path = destination / f"{merge_filename}.json"

        out_path.write_text(
            json.dumps(
                records,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    return out_path



