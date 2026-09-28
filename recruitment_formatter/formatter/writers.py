"""
Output writers. Both writers use the canonical output column order/names
from config.SCHEMA, so downstream tools (including manual Zoho import)
always see the same shape.
"""
from __future__ import annotations
import json
from pathlib import Path

import pandas as pd

from .config import SCHEMA, FIELD_BY_KEY, OUTPUT_COLUMNS


def _records_to_output_df(records: list[dict]) -> pd.DataFrame:
    rows = []
    for rec in records:
        rows.append({spec.output_name: rec.get(spec.key, "") for spec in SCHEMA})
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def write_excel(records: list[dict], out_path: Path) -> None:
    df = _records_to_output_df(records)
    if "Post code" in df.columns:
        df["Post code"] = df["Post code"].map(lambda v: "" if v in ("", None) else str(v))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Agents")
        ws = writer.sheets["Agents"]
        for i, col in enumerate(df.columns, start=1):
            max_len = max([len(str(col))] + [len(str(v)) for v in df[col].astype(str)])
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(max_len + 2, 60)
            if col == "Post code":
                for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                    for cell in row:
                        if cell.value not in (None, ""):
                            cell.value = str(cell.value)
                            cell.number_format = "@"


def write_json(records: list[dict], out_path: Path) -> None:
    """
    Writes JSON keyed by canonical snake_case keys (CRM/API-friendly),
    as a list of flat objects — the shape Zoho's bulk APIs and most
    dashboard tools expect.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [{spec.key: rec.get(spec.key, "") for spec in SCHEMA} for rec in records]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def records_to_zoho_payload(records: list[dict]) -> list[dict]:
    """Maps canonical records to Zoho CRM field names (config.zoho_field)."""
    out = []
    for rec in records:
        zoho_rec = {}
        for spec in SCHEMA:
            if spec.zoho_field is None:
                continue
            value = rec.get(spec.key, "")
            if value == "":
                continue  # don't send empty strings over blank Zoho fields
            zoho_rec[spec.zoho_field] = value
        out.append(zoho_rec)
    return out
