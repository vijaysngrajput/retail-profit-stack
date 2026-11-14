"""The investigation desk: a folder the AI investigator works in.

Implements LLD section 7 (The rulebook and the desk) and the scoring in section 8.

The desk holds copies. Nothing the investigator writes there is read by the pipeline, the
tools, or the analyst. Its reports are notes for a person.
"""

import json
import shutil
from pathlib import Path

import pandas as pd

from retail_profit_stack.config import EVALS_DIR, RULEBOOK_FILE, SOURCE_DIR, WAREHOUSE_DIR
from retail_profit_stack.lineage.runs import latest_run_id, run_folder
from retail_profit_stack.quality.checks import as_rows
from retail_profit_stack.transform.pipeline import load_sources

INVESTIGATION_CASES_FILE = EVALS_DIR / "m3_investigation_cases.json"

# The causes the rulebook lists for each check. A report must name one of these.
CAUSES = {
    "duplicate_records": ["batch_loaded_twice", "single_record_resent"],
    "missing_product_cost": ["monthly_cost_not_updated", "product_never_costed"],
    "event_out_of_order": ["order_recorded_late", "date_typed_wrong"],
    "refund_exceeds_line": ["whole_order_refunded_on_one_line", "amount_typed_wrong"],
    "totals_do_not_match": ["calculation_lost_records"],
}
ALL_CAUSES = [cause for causes in CAUSES.values() for cause in causes]
REPORT_FIELDS = ["finding_id", "likely_cause", "evidence", "suggested_action"]


def read_findings(warehouse_dir: Path = WAREHOUSE_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The two quality tables of the latest pipeline run: the findings and their records."""
    run_id = latest_run_id(warehouse_dir)
    if run_id is None:
        raise FileNotFoundError(f"There is no pipeline run in {warehouse_dir}")
    folder = run_folder(run_id, warehouse_dir)
    findings = pd.read_parquet(folder / "quality_findings.parquet")
    records = pd.read_parquet(folder / "finding_records.parquet")
    return findings, records


def related_records(bad_records: list[dict], product_id: str, sources: dict) -> dict:
    """The records a person would look up next: the orders, their lines, and the product's costs."""
    line_ids = {record.get("order_item_id") for record in bad_records} - {None}
    lines = [row for row in sources["order_items"] if row["order_item_id"] in line_ids]
    order_ids = {row["order_id"] for row in lines}
    related = {
        "orders": [row for row in sources["orders"] if row["order_id"] in order_ids],
        "all_lines_of_those_orders": unique_rows(
            [row for row in sources["order_items"] if row["order_id"] in order_ids]
        ),
        "product_costs_for_this_product": [
            row for row in sources["product_costs"] if row["product_id"] == product_id
        ],
    }
    return related


def unique_rows(rows: list[dict]) -> list[dict]:
    """The rows with exact repeats removed, in their original order."""
    seen, result = set(), []
    for row in rows:
        text = json.dumps(row, default=str, sort_keys=True)
        if text not in seen:
            seen.add(text)
            result.append(row)
    return result


def finding_file(finding: dict, records: pd.DataFrame, sources: dict) -> dict:
    """Everything the investigator needs for one finding, as one JSON document."""
    bad_records = [
        {"source_table": row["source_table"], "what_is_wrong": row["detail"],
         "record": json.loads(row["record"])}
        for row in as_rows(records)
        if row["finding_id"] == finding["finding_id"]
    ]  # fmt: skip
    product_names = {row["product_id"]: row["product_name"] for row in sources["products"]}
    return {
        "finding_id": finding["finding_id"],
        "check_name": finding["check_name"],
        "month": finding["month"],
        "product_id": finding["product_id"],
        "product_name": product_names[finding["product_id"]],
        "outcome": finding["outcome"],
        "description": finding["description"],
        "bad_records": bad_records,
        "related_records": related_records(
            [bad["record"] for bad in bad_records], finding["product_id"], sources
        ),
    }


def build_desk(
    folder: Path,
    max_findings: int | None = None,
    warehouse_dir: Path = WAREHOUSE_DIR,
    source_dir: Path = SOURCE_DIR,
) -> list[str]:
    """Make a fresh desk folder and return the ids of the findings put on it.

    max_findings caps how many findings go on the desk, so a trial run is cheap.
    """
    folder = Path(folder)
    if folder.exists() and not (folder / "rulebook.md").exists() and any(folder.iterdir()):
        raise ValueError(f"{folder} is not a desk folder, so it will not be replaced.")
    shutil.rmtree(folder, ignore_errors=True)
    (folder / "findings").mkdir(parents=True)
    (folder / "reports").mkdir()
    shutil.copy(RULEBOOK_FILE, folder / "rulebook.md")

    findings, records = read_findings(warehouse_dir)
    sources = {name: table.to_pylist() for name, table in load_sources(source_dir).items()}
    chosen = as_rows(findings)[:max_findings]
    for finding in chosen:
        content = finding_file(finding, records, sources)
        path = folder / "findings" / f"{finding['finding_id']}.json"
        path.write_text(json.dumps(content, indent=2, default=str), encoding="utf-8")
    return [finding["finding_id"] for finding in chosen]


def read_report(path: Path, finding_id: str) -> dict:
    """Read one report file. If it cannot be used, say why and leave the finding for a person."""
    row = {"finding_id": finding_id, "likely_cause": None, "evidence": None,
           "suggested_action": None, "status": "left for a person", "problem": ""}  # fmt: skip
    if not path.exists():
        row["problem"] = "No report was written."
        return row
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        row["problem"] = "The report is not valid JSON."
        return row
    if not isinstance(report, dict) or any(field not in report for field in REPORT_FIELDS):
        row["problem"] = f"The report must have the fields {REPORT_FIELDS}."
        return row
    if report["likely_cause"] not in ALL_CAUSES:
        row["problem"] = f"'{report['likely_cause']}' is not a cause in the rulebook."
        return row
    row.update({field: report[field] for field in REPORT_FIELDS if field != "finding_id"})
    row["status"] = "report read"
    return row


def read_reports(folder: Path) -> pd.DataFrame:
    """One row per finding on the desk: its report, or why it was left for a person."""
    folder = Path(folder)
    finding_ids = sorted(path.stem for path in (folder / "findings").glob("*.json"))
    rows = [read_report(folder / "reports" / f"{finding_id}.json", finding_id)
            for finding_id in finding_ids]  # fmt: skip
    return pd.DataFrame(rows)


def score_reports(reports: pd.DataFrame) -> pd.DataFrame:
    """Compare each report's cause with the cause we planted. Adds two columns."""
    cases = json.loads(INVESTIGATION_CASES_FILE.read_text(encoding="utf-8"))
    planted = {case["finding_id"]: case["planted_cause"] for case in cases}
    scored = reports.copy()
    scored["planted_cause"] = [planted.get(finding_id) for finding_id in scored["finding_id"]]
    results = []
    for row in as_rows(scored):
        if row["status"] != "report read":
            results.append("left for a person")
        elif row["likely_cause"] == row["planted_cause"]:
            results.append("right")
        else:
            results.append("wrong")
    scored["result"] = results
    return scored
