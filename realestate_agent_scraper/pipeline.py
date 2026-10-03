"""
Pipeline — connects the automation and scraper subtools (nodriver/async version).

Flow per suburb:
    create_browser()                    -> nd.Browser
    browser.get()                       -> nd.Tab
    navigator.search_suburb()           -> loads results page
    navigator.collect_agent_profile_urls()
                                        -> [profile urls] from ALL pages
    for each url:
        page.get(url)
        extractor.extract_agent_record()
                                        -> raw record
        formatter.cleaners.clean_value() -> cleaned per-field

    all records -> write_output (Excel/JSON) with checkpoints
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import tempfile
from collections.abc import Callable
from pathlib import Path

import pandas as pd

import config

from automation.browser import create_browser
from automation.navigator import (
    collect_agent_profile_urls,
    search_location,
    search_suburb,
)
from scraper.extractor import extract_agent_record
from scraper.html_fields import (
    agent_profile_identity,
    clean_agent_name,
    clean_job_title,
    extract_agency_name_from_page,
    extract_profile_fields_from_html,
    extract_team_member_links,
    split_suburb_and_postcode,
)
from scraper.matching import designation_confidence, matches_designation

logger = logging.getLogger("scraper.pipeline")

CheckpointFn = Callable[[list[dict], list[dict]], None]
RecordFn = Callable[[str, dict], None]


async def _human_pause() -> None:
    await asyncio.sleep(
        random.uniform(
            config.MIN_PROFILE_DELAY_S,
            config.MAX_PROFILE_DELAY_S,
        )
    )


def _record_dedupe_key(row: dict) -> str:
    return agent_profile_identity(row.get("profile_url", ""))


def _clean_record(raw: dict) -> dict:
    try:
        try:
            from formatter.config import FIELD_BY_KEY
            from formatter.cleaners import clean_value
        except ImportError:
            from recruitment_formatter.formatter.config import FIELD_BY_KEY
            from recruitment_formatter.formatter.cleaners import clean_value

        cleaned = {}
        for key, value in raw.items():
            spec = FIELD_BY_KEY.get(key)
            if spec:
                cleaned[key] = clean_value(spec.dtype, value)
            else:
                cleaned[key] = value
        return cleaned
    except ImportError:
        logger.debug("formatter package not available, skipping cleaning")
        return raw


def _visit_cap(max_agents: int | None) -> int | None:
    if max_agents is not None:
        return max_agents if max_agents > 0 else None
    return config.MAX_AGENTS_PER_SUBURB


async def _scrape_suburbs_async(
    suburbs: list[str],
    headless: bool = False,
    *,
    records: list[dict] | None = None,
    report: list[dict] | None = None,
    on_checkpoint: CheckpointFn | None = None,
    on_record: RecordFn | None = None,
    max_agents: int | None = None,
    designation: str = "",
    deep_search: bool = False,
    use_location_search: bool = False,
    search_terms: dict[str, str] | None = None,
    fallback_terms: dict[str, str] | None = None,
    max_rows: int | None = 200,
) -> tuple[list[dict], list[dict]]:
    all_records: list[dict] = records if records is not None else []
    report_rows: list[dict] = report if report is not None else []
    seen_urls_by_suburb: dict[str, set[str]] = {}
    for row in all_records:
        query = str(row.get("_suburb_query", ""))
        url = _record_dedupe_key(row)
        if query and url:
            seen_urls_by_suburb.setdefault(query, set()).add(url)

    browser = None
    page = None
    interrupted = False

    def checkpoint(reason: str) -> None:
        logger.info("Saving checkpoint... (%s, %d record(s))", reason, len(all_records))
        if on_checkpoint:
            try:
                on_checkpoint(all_records, report_rows)
                logger.info("Checkpoint saved")
            except Exception as exc:  # noqa: BLE001
                logger.error("Checkpoint failed: %s", exc, exc_info=True)

    try:
        logger.info("Starting nodriver browser (headless=%s)...", headless)
        browser = await create_browser(headless=headless)
        logger.info("Nodriver browser started successfully.")
        page = await browser.get(config.FIND_AGENT_URL)
        logger.info("Browser tab initialized.")

        for suburb in suburbs:
            location_text = (search_terms or {}).get(suburb, suburb)
            suburb_name, postcode = split_suburb_and_postcode(location_text)
            if use_location_search and not suburb_name:
                suburb_name = location_text
            entry = {
                "suburb": suburb,
                "suburb_name": suburb_name,
                "postcode": postcode,
                "profiles_found": 0,
                "pages_scraped": 0,
                "records_scraped": 0,
                "profiles_failed": 0,
                "status": "in_progress",
                "error": None,
            }
            seen_urls = seen_urls_by_suburb.setdefault(suburb, set())
            agency_details: dict[str, dict[str, str]] = {}
            visited_agencies: set[str] = set()
            completed_agencies: dict[str, bool] = {}
            query_row_count = sum(row.get("_suburb_query") == suburb for row in all_records)
            row_limit_reached = bool(max_rows and query_row_count >= max_rows)

            if row_limit_reached:
                entry["status"] = "partial"
                entry["error"] = f"max_rows_reached:{max_rows}"
                report_rows.append(entry)
                logger.info("Row limit %d already reached for %s; not scraping additional profiles.", max_rows, suburb)
                checkpoint(f"row_limit_reached:{suburb}")
                continue

            try:
                logger.info("Processing suburb: %s (suburb=%s postcode=%s)", suburb, suburb_name, postcode)
                if use_location_search:
                    selected_location = await search_location(page, location_text)
                    if selected_location:
                        logger.info("Selected first website location suggestion: %s", selected_location)
                        location_text = selected_location
                        suburb_name, postcode = split_suburb_and_postcode(location_text)
                        if not suburb_name:
                            suburb_name = location_text
                        ok = True
                    elif suburb in (fallback_terms or {}):
                        location_text = fallback_terms[suburb]
                        logger.warning(
                            "No selectable website suggestion found for %r; falling back to postcode JSON entry %r",
                            (search_terms or {}).get(suburb, suburb),
                            location_text,
                        )
                        suburb_name, postcode = split_suburb_and_postcode(location_text)
                        ok = await search_suburb(page, location_text)
                    else:
                        ok = False
                else:
                    ok = await search_suburb(page, suburb)
                if not ok:
                    entry["error"] = "search_failed"
                    entry["status"] = "failed"
                    logger.warning("Search failed for suburb: %s", suburb)
                    report_rows.append(entry)
                    checkpoint(f"search_failed:{suburb_name}")
                    continue

                profile_urls = await collect_agent_profile_urls(
                    page,
                    suburb,
                    on_page=lambda page_no: entry.__setitem__("pages_scraped", page_no),
                ) or []
                entry["profiles_found"] = len(profile_urls)
                candidate_primary_ids = {agent_profile_identity(candidate) for candidate in profile_urls}
                logger.info("Found %d agent profile(s) for '%s'.", len(profile_urls), suburb)

                completed_primary_ids = {
                    agent_profile_identity(row.get("profile_url", ""))
                    for row in all_records
                    if row.get("_suburb_query") == suburb
                    and row.get("record_type") != "Team member"
                    and row.get("_deep_search_complete")
                }
                remaining_urls = [
                    url for url in profile_urls
                    if agent_profile_identity(url) not in completed_primary_ids
                    and (deep_search or agent_profile_identity(url) not in seen_urls)
                ]
                cap = _visit_cap(max_agents)
                capped = bool(cap and len(remaining_urls) > cap)
                if capped:
                    logger.info(
                        "Visiting first %d of %d collected profile(s) for '%s' (max-agents cap)",
                        cap,
                        len(remaining_urls),
                        suburb,
                    )
                    remaining_urls = remaining_urls[:cap]

                for url in remaining_urls:
                    if max_rows and sum(row.get("_suburb_query") == suburb for row in all_records) >= max_rows:
                        row_limit_reached = True
                        break
                    key = agent_profile_identity(url)
                    try:
                        logger.info("Opening agent profile: %s", url)
                        await page.get(url)
                        await _human_pause()
                        raw = await extract_agent_record(page, url, suburb_hint=location_text)
                        if not raw:
                            logger.warning("No record extracted from: %s", url)
                            entry["profiles_failed"] += 1
                            continue
                        raw_name = clean_agent_name(str(raw.get("name") or ""), url)
                        if not raw_name:
                            logger.warning("Could not extract a clean agent name from %s", url)
                            entry["profiles_failed"] += 1
                            continue
                        raw["name"] = raw_name
                        raw["job_title"] = clean_job_title(str(raw.get("job_title") or ""))
                        raw_agency_url = str(raw.get("agency_url") or "").rstrip("/").lower()
                        known_agency = agency_details.get(raw_agency_url, {})
                        for field in ("agency_name", "agency_address"):
                            if not raw.get(field) and known_agency.get(field):
                                raw[field] = known_agency[field]
                        if not raw.get("suburb"):
                            raw["suburb"] = suburb_name
                        if not raw.get("postcode"):
                            raw["postcode"] = postcode
                        all_designations = designation.strip().lower() in {"all", "*", "any"}
                        confidence = 1.0 if all_designations else designation_confidence(
                            str(raw.get("job_title", "")), designation
                        )
                        if not matches_designation(str(raw.get("job_title", "")), designation):
                            logger.info(
                                "Skipping %s: designation %r confidence %.0f%% is below 85%%",
                                raw.get("name") or url,
                                raw.get("job_title", ""),
                                confidence * 100,
                            )
                            continue
                        raw["_suburb_query"] = suburb
                        raw["record_type"] = "Primary agent"
                        raw["primary_agent"] = raw.get("name", "")
                        raw["primary_agent_url"] = url
                        raw["designation_confidence"] = "" if all_designations else confidence
                        cleaned = _clean_record(raw)
                        existing_index = next(
                            (
                                index for index, existing in enumerate(all_records)
                                if existing.get("_suburb_query") == suburb
                                and _record_dedupe_key(existing) == key
                            ),
                            None,
                        )
                        if existing_index is None:
                            all_records.append(cleaned)
                            seen_urls.add(key)
                            entry["records_scraped"] += 1
                            if on_record:
                                try:
                                    on_record(suburb, cleaned)
                                except Exception as exc:  # noqa: BLE001
                                    entry["profiles_failed"] += 1
                                    logger.error("Could not persist profile checkpoint %s: %s", url, exc, exc_info=True)
                        elif (
                            all_records[existing_index].get("record_type") == "Team member"
                            or deep_search
                        ):
                            # Prefer a freshly scraped search-result row when
                            # promoting a team record or resuming deep-search.
                            all_records[existing_index] = cleaned
                            if on_record:
                                try:
                                    on_record(suburb, cleaned)
                                except Exception as exc:  # noqa: BLE001
                                    entry["profiles_failed"] += 1
                                    logger.error("Could not persist promoted profile %s: %s", url, exc, exc_info=True)
                        agency_url = str(cleaned.get("agency_url") or "").strip()
                        agency_key = agency_url.rstrip("/").lower()
                        agency_complete = deep_search and not agency_url
                        if deep_search and agency_url and agency_key not in visited_agencies and not (
                            max_rows and sum(row.get("_suburb_query") == suburb for row in all_records) >= max_rows
                        ):
                            # Several selected agents can belong to the same
                            # office. Crawl each company team once, instead of
                            # duplicating its entire roster under every agent
                            # and consuming the workbook row limit with copies.
                            visited_agencies.add(agency_key)
                            agency_complete = False
                            try:
                                await page.get(agency_url)
                                await _human_pause()
                                agency_html = await page.get_content()
                                agency_profile_fields = extract_profile_fields_from_html(agency_html)
                                agency_details[agency_key] = {
                                    "agency_name": extract_agency_name_from_page(agency_html)
                                    or agency_profile_fields.get("agency_name", ""),
                                    "agency_address": agency_profile_fields.get("agency_address", ""),
                                }
                                for field in ("agency_name", "agency_address"):
                                    if not cleaned.get(field) and agency_details[agency_key].get(field):
                                        cleaned[field] = agency_details[agency_key][field]
                                if existing_index is not None:
                                    all_records[existing_index] = cleaned
                                if on_record and (cleaned.get("agency_name") or cleaned.get("agency_address")):
                                    try:
                                        on_record(suburb, cleaned)
                                    except Exception as exc:  # noqa: BLE001
                                        logger.warning("Could not persist agency details for %s: %s", url, exc)
                                team_links = extract_team_member_links(agency_html)
                                logger.info("Found %d team member link(s) for %s", len(team_links), cleaned.get("name", url))
                                agency_complete = True
                                for member in team_links:
                                    if max_rows and sum(row.get("_suburb_query") == suburb for row in all_records) >= max_rows:
                                        row_limit_reached = True
                                        agency_complete = False
                                        break
                                    member_id = agent_profile_identity(member.profile_url)
                                    if member_id == key or member_id in seen_urls:
                                        continue
                                    # A company roster is represented once in
                                    # the workbook and grouped beneath the first
                                    # matching primary agent for that company.
                                    try:
                                        await page.get(member.profile_url)
                                        await _human_pause()
                                        team_raw = await extract_agent_record(page, member.profile_url, suburb_hint=location_text)
                                        if not team_raw:
                                            entry["profiles_failed"] += 1
                                            agency_complete = False
                                            continue
                                        team_name = clean_agent_name(
                                            str(team_raw.get("name") or ""), member.profile_url
                                        )
                                        team_raw["name"] = team_name or clean_agent_name(
                                            member.name, member.profile_url
                                        )
                                        if not team_raw["name"]:
                                            logger.warning(
                                                "Skipping team profile with no reliable name: %s",
                                                member.profile_url,
                                            )
                                            entry["profiles_failed"] += 1
                                            agency_complete = False
                                            continue
                                        team_raw["job_title"] = clean_job_title(
                                            str(team_raw.get("job_title") or "")
                                        ) or member.job_title
                                        for field in ("agency_name", "agency_address"):
                                            if not team_raw.get(field) and agency_details[agency_key].get(field):
                                                team_raw[field] = agency_details[agency_key][field]
                                        for field in ("rating", "reviews", "properties_sold", "median_sold_price"):
                                            if getattr(member, field):
                                                team_raw[field] = getattr(member, field)
                                        all_designations = designation.strip().lower() in {"all", "*", "any"}
                                        if member_id in candidate_primary_ids and (
                                            all_designations
                                            or matches_designation(str(team_raw.get("job_title", "")), designation)
                                        ):
                                            # Keep one row when a team member
                                            # is also a qualifying search result.
                                            continue
                                        team_raw["_suburb_query"] = suburb
                                        team_raw["record_type"] = "Team member"
                                        team_raw["profile_url"] = member.profile_url
                                        team_raw["primary_agent"] = cleaned.get("name", "")
                                        team_raw["primary_agent_url"] = url
                                        team_raw["designation_confidence"] = ""
                                        team_cleaned = _clean_record(team_raw)
                                        all_records.append(team_cleaned)
                                        seen_urls.add(member_id)
                                        entry["records_scraped"] += 1
                                        if on_record:
                                            on_record(suburb, team_cleaned)
                                    except Exception as team_exc:  # noqa: BLE001
                                        entry["profiles_failed"] += 1
                                        agency_complete = False
                                        logger.warning("Failed team member %s: %s", member.profile_url, team_exc)
                                completed_agencies[agency_key] = agency_complete
                            except Exception as agency_exc:  # noqa: BLE001
                                entry["profiles_failed"] += 1
                                completed_agencies[agency_key] = False
                                logger.warning("Could not read agency team for %s: %s", url, agency_exc)
                        elif deep_search and agency_url and agency_key in completed_agencies:
                            agency_complete = completed_agencies[agency_key]
                        if deep_search and agency_complete:
                            # Persist that this primary's company roster was
                            # fully examined. Resume can then skip its profile
                            # while retrying any agency crawl interrupted partway.
                            cleaned["_deep_search_complete"] = True
                            completed_index = existing_index
                            if completed_index is None:
                                completed_index = next(
                                    (
                                        index for index, existing in enumerate(all_records)
                                        if existing.get("_suburb_query") == suburb
                                        and _record_dedupe_key(existing) == key
                                    ),
                                    None,
                                )
                            if completed_index is not None:
                                all_records[completed_index]["_deep_search_complete"] = True
                            if on_record:
                                try:
                                    on_record(suburb, cleaned)
                                except Exception as exc:  # noqa: BLE001
                                    logger.error("Could not persist deep-search completion for %s: %s", url, exc)
                        if max_rows and sum(row.get("_suburb_query") == suburb for row in all_records) >= max_rows:
                            row_limit_reached = True
                        logger.info(
                            "Scraped: %s (%s / %s) — %s",
                            cleaned.get("name", "?"),
                            cleaned.get("suburb", suburb_name),
                            cleaned.get("postcode", postcode),
                            url,
                        )
                    except KeyboardInterrupt:
                        interrupted = True
                        logger.info("Ctrl+C detected.")
                        logger.info("Stopping scraper gracefully...")
                        break
                    except Exception as exc:  # noqa: BLE001
                        entry["profiles_failed"] += 1
                        logger.error("Failed to scrape %s: %s", url, exc, exc_info=True)
                    await _human_pause()
                    if row_limit_reached:
                        break

                if interrupted:
                    entry["status"] = "interrupted"
                    report_rows.append(entry)
                    checkpoint("keyboard_interrupt")
                    break

                if row_limit_reached:
                    entry["status"] = "partial"
                    entry["error"] = f"max_rows_reached:{max_rows}"
                else:
                    entry["status"] = "partial" if entry["profiles_failed"] or capped else "completed"

            except KeyboardInterrupt:
                interrupted = True
                entry["status"] = "interrupted"
                logger.info("Ctrl+C detected.")
                logger.info("Stopping scraper gracefully...")
                report_rows.append(entry)
                checkpoint("keyboard_interrupt")
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("Suburb '%s' failed: %s", suburb, exc, exc_info=True)
                entry["error"] = str(exc)
                entry["status"] = "failed"

            report_rows.append(entry)
            logger.info(
                "Finished suburb '%s': %d profile(s) found, %d record(s) scraped. Total records: %d",
                suburb,
                entry["profiles_found"],
                entry["records_scraped"],
                len(all_records),
            )
            checkpoint(f"suburb:{suburb_name}")
            await _human_pause()

    except KeyboardInterrupt:
        interrupted = True
        logger.info("Ctrl+C detected.")
        logger.info("Stopping scraper gracefully...")
        checkpoint("keyboard_interrupt")
    except Exception as exc:  # noqa: BLE001
        logger.critical("Browser pipeline failed: %s", exc, exc_info=True)
        processed_suburbs = {item["suburb"] for item in report_rows}
        for suburb in suburbs:
            if suburb not in processed_suburbs:
                report_rows.append(
                    {
                        "suburb": suburb,
                        "profiles_found": 0,
                        "records_scraped": 0,
                        "profiles_failed": 0,
                        "status": "failed",
                        "error": f"browser_error: {exc}",
                    }
                )
        checkpoint("browser_error")
    finally:
        if browser is not None:
            try:
                logger.info("Stopping nodriver browser...")
                result = browser.stop()
                if asyncio.iscoroutine(result):
                    await result
                logger.info("Nodriver browser stopped.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error while stopping browser: %s", exc)

    return all_records, report_rows


def scrape_suburbs(
    suburbs: list[str],
    headless: bool = False,
    *,
    records: list[dict] | None = None,
    report: list[dict] | None = None,
    on_checkpoint: CheckpointFn | None = None,
    on_record: RecordFn | None = None,
    max_agents: int | None = None,
    designation: str = "",
    deep_search: bool = False,
    use_location_search: bool = False,
    search_terms: dict[str, str] | None = None,
    fallback_terms: dict[str, str] | None = None,
    max_rows: int | None = 200,
) -> tuple[list[dict], list[dict]]:
    """
    Public synchronous entry point.

    `records` / `report` are filled in place so Ctrl+C cannot drop in-memory data
    even if asyncio.run() is interrupted.
    """
    records = records if records is not None else []
    report = report if report is not None else []
    try:
        return asyncio.run(
            _scrape_suburbs_async(
                suburbs,
                headless=headless,
                records=records,
                report=report,
                on_checkpoint=on_checkpoint,
                on_record=on_record,
                max_agents=max_agents,
                designation=designation,
                deep_search=deep_search,
                use_location_search=use_location_search,
                search_terms=search_terms,
                fallback_terms=fallback_terms,
                max_rows=max_rows,
            )
        )
    except KeyboardInterrupt:
        logger.info("Ctrl+C detected.")
        logger.info("Stopping scraper gracefully...")
        if on_checkpoint:
            try:
                on_checkpoint(records, report)
            except Exception as exc:  # noqa: BLE001
                logger.error("Final interrupt checkpoint failed: %s", exc, exc_info=True)
        return records, report


def _schema_columns() -> list[tuple[str, str]]:
    try:
        try:
            from formatter.config import SCHEMA
        except ImportError:
            from recruitment_formatter.formatter.config import SCHEMA
        return [(spec.key, spec.output_name) for spec in SCHEMA]
    except ImportError:
        return [
            ("name", "Name"),
            ("job_title", "job_title"),
            ("years_experience", "Years_experience"),
            ("agency_name", "Agency Name"),
            ("agent_email", "Email ID of the Agent"),
            ("suburb", "suburbs"),
            ("postcode", "Post code"),
            ("agency_address", "agency_address"),
            ("phone", "phone"),
            ("rating", "rating"),
            ("reviews", "Reviews"),
            ("properties_sold", "properties_sold"),
            ("median_sold_price", "median_sold_price"),
            ("median_days_advertised", "median_days_advertised"),
            ("profile_url", "profile_url"),
            ("agency_url", "agency_url"),
        ]


def _records_to_dataframe(records: list[dict]) -> pd.DataFrame:
    columns = _schema_columns()
    relationship_fields = (
        ("record_type", "Record type"),
        ("primary_agent", "Primary agent"),
        ("primary_agent_url", "Primary agent profile"),
        ("designation_confidence", "Designation confidence"),
    )
    output_columns = [output for _, output in columns] + [output for _, output in relationship_fields]
    if len(output_columns) != len(set(output_columns)):
        raise ValueError("The Excel output schema contains duplicate column names")
    rows = []
    for rec in records:
        row = {output: rec.get(key, "") for key, output in columns}
        row.update({output: rec.get(key, "") for key, output in relationship_fields})
        rows.append(row)
    return pd.DataFrame(rows, columns=output_columns)


def write_output(
    records: list[dict],
    destination: Path,
    mode: str,
    merge_filename: str = "scraped_data",
) -> Path:
    """
    Writes scraped records to the caller-supplied destination directory.

    Excel mode always writes a real .xlsx file (pandas/openpyxl). It does not
    silently switch to JSON. Missing fields become empty cells.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    stem = merge_filename or "scraped_data"

    if mode == "excel":
        out_path = destination / f"{stem}.xlsx"
        # Use a unique temporary workbook so stale/concurrent saves cannot
        # collide. Keep the .xlsx suffix for pandas and the shared formatter.
        descriptor, tmp_name = tempfile.mkstemp(prefix=f".{stem}.", suffix=".tmp.xlsx", dir=destination)
        os.close(descriptor)
        tmp_path = Path(tmp_name)
        try:
            df = _records_to_dataframe(records)
            has_relationship_data = any(record.get("record_type") for record in records)
            if has_relationship_data:
                with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False, sheet_name="Agents")
            else:
                try:
                    try:
                        from formatter.writers import write_excel
                    except ImportError:
                        from recruitment_formatter.formatter.writers import write_excel
                    write_excel(records, tmp_path)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Formatter Excel writer unavailable (%s); using pandas/openpyxl fallback", exc)
                    with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
                        df.to_excel(writer, index=False, sheet_name="Agents")
            try:
                tmp_path.replace(out_path)
            except PermissionError as exc:
                raise PermissionError(
                    f"Cannot update {out_path}: the workbook may be open in Excel or locked by another program. "
                    "Close it and run python main.py again; saved scrape checkpoints will be resumed."
                ) from exc
        finally:
            tmp_path.unlink(missing_ok=True)
        logger.info("Excel saved to: %s", out_path.resolve())
        return out_path

    out_path = destination / f"{stem}.json"
    try:
        try:
            from formatter.writers import write_json
        except ImportError:
            from recruitment_formatter.formatter.writers import write_json
        write_json(records, out_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Formatter JSON writer unavailable (%s); writing JSON directly", exc)
        out_path.write_text(
            json.dumps(records, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    logger.info("JSON saved to: %s", out_path.resolve())
    return out_path
