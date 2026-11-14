"""The five quality checks, and the code that runs them.

Implements LLD section 4 (The checks) and section 6 (The two new tables).

A check is one SQL query that returns the bad records, one row each. Code then applies the
check's outcome. No model is involved anywhere in this file.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa

from retail_profit_stack.config import EVALS_DIR
from retail_profit_stack.transform.contracts import table_from_rows
from retail_profit_stack.transform.specs import SOURCE_SCHEMAS

SQL_DIR = Path(__file__).resolve().parent / "sql"
CHECK_CASES_FILE = EVALS_DIR / "m3_check_cases.json"
BAD_RECORD_COLUMNS = ["check_name", "month", "product_id", "source_table", "row_number", "detail"]


@dataclass(frozen=True)
class Check:
    """One quality check: what it looks for, and what happens when it finds something."""

    name: str
    looks_for: str
    outcome: str  # "quarantine" or "needs_review"
    severity: str  # "high", "medium", or "low"
    affected_metrics: tuple[str, ...]
    finding_text: str  # the sentence used to describe a finding


SALES_TERMS = ("units_sold", "gross_sales", "net_sales", "gross_profit", "contribution_profit")

CHECKS = [
    Check(
        name="duplicate_records",
        looks_for="The same record appearing more than once.",
        outcome="quarantine",
        severity="low",
        affected_metrics=SALES_TERMS,
        finding_text=(
            "Records for {product} in {month} that appeared more than once: {count}. "
            "The extra copies were set aside and are not in the figures."
        ),
    ),
    Check(
        name="missing_product_cost",
        looks_for="A product sold in a month with no cost for that month.",
        outcome="needs_review",
        severity="high",
        affected_metrics=("product_cost", "gross_profit", "contribution_profit"),
        finding_text=(
            "No product cost is recorded for {product} in {month}, so its gross profit and "
            "contribution profit cannot be calculated. Its category total leaves it out."
        ),
    ),
    Check(
        name="event_out_of_order",
        looks_for="A refund or shipment dated before its order.",
        outcome="needs_review",
        severity="low",
        affected_metrics=("refunds", "shipping_cost", "fulfillment_cost"),
        finding_text=(
            "Records for {product} in {month} dated before their order: {count}. "
            "They are still counted, in the month of their own date."
        ),
    ),
    Check(
        name="refund_exceeds_line",
        looks_for="A refund larger than the order line it refunds.",
        outcome="needs_review",
        severity="medium",
        affected_metrics=("refunds", "net_sales", "gross_profit", "contribution_profit"),
        finding_text=(
            "Refunds for {product} in {month} that are larger than the order line they refund: "
            "{count}. They are still counted, so net sales may be understated."
        ),
    ),
    Check(
        name="totals_do_not_match",
        looks_for="A total in the profit table that differs from the kept records.",
        outcome="needs_review",
        severity="high",
        affected_metrics=SALES_TERMS,
        finding_text=(
            "Totals for {product} in {month} where the profit table differs from the records: "
            "{count}. These figures cannot be trusted until this is explained."
        ),
    ),
]
RECORD_CHECKS = CHECKS[:4]  # these run on the source records, before the calculation
TOTALS_CHECK = CHECKS[4]  # this one runs after the calculation
CHECK_BY_NAME = {check.name: check for check in CHECKS}


def number_rows(tables: dict[str, pa.Table]) -> dict[str, pa.Table]:
    """Give every row a row_number: 1 for the first row of its table, 2 for the second...

    Two identical rows cannot be told apart by their values. Their row numbers can.
    """
    numbered = {}
    for name, table in tables.items():
        numbers = pa.array(range(1, table.num_rows + 1), type=pa.int64())
        numbered[name] = table.append_column("row_number", numbers)
    return numbered


def run_check(check: Check, tables: dict[str, pa.Table]) -> pd.DataFrame:
    """Run one check's query on the tables. Returns its bad records, one row each."""
    db = duckdb.connect(":memory:")
    for name, table in tables.items():
        db.register(name, table)
    query = (SQL_DIR / f"{check.name}.sql").read_text(encoding="utf-8")
    found = db.execute(query).df()
    db.close()
    found.insert(0, "check_name", check.name)
    found["row_number"] = found["row_number"].astype("Int64")  # whole numbers, or missing
    return pd.DataFrame(found, columns=BAD_RECORD_COLUMNS)


def run_record_checks(numbered_sources: dict[str, pa.Table]) -> pd.DataFrame:
    """Run the four record checks on the source tables. The tables must have row numbers."""
    results = [run_check(check, numbered_sources) for check in RECORD_CHECKS]
    return pd.concat(results, ignore_index=True)


def run_totals_check(kept: dict[str, pa.Table], profit: pa.Table) -> pd.DataFrame:
    """Compare the profit table's totals with the kept records."""
    return run_check(TOTALS_CHECK, {**kept, "monthly_product_profit": profit})


def check_outcomes(bad_records: pd.DataFrame) -> dict[str, str]:
    """For each of the five checks: "pass", or its outcome if it found something."""
    found = set(bad_records["check_name"])
    return {check.name: check.outcome if check.name in found else "pass" for check in CHECKS}


def as_rows(frame: pd.DataFrame) -> list[dict]:
    """A table as a list of dictionaries, one per row. A missing row_number becomes None."""
    rows = []
    for row in frame.to_dict(orient="records"):
        if "row_number" in row:
            row["row_number"] = None if pd.isna(row["row_number"]) else int(row["row_number"])
        rows.append(row)
    return rows


def make_findings(
    bad_records: pd.DataFrame, numbered_sources: dict[str, pa.Table]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group the bad records into findings: one per check, month, and product.

    Returns two tables: quality_findings and finding_records (LLD section 6).
    """
    product_names = {
        row["product_id"]: row["product_name"] for row in numbered_sources["products"].to_pylist()
    }
    source_rows = {name: table.to_pylist() for name, table in numbered_sources.items()}
    check_order = {check.name: position for position, check in enumerate(CHECKS)}

    # Put the bad records in a fixed order, so the findings get the same ids on every run.
    bad_rows = as_rows(bad_records)
    bad_rows.sort(
        key=lambda row: (
            check_order[row["check_name"]], row["month"], row["product_id"],
            row["source_table"], row["row_number"] or 0,
        )
    )  # fmt: skip
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in bad_rows:
        groups.setdefault((row["check_name"], row["month"], row["product_id"]), []).append(row)

    findings, records = [], []
    for number, ((check_name, month, product_id), group) in enumerate(groups.items(), start=1):
        finding_id = f"QF-{number:03d}"
        check = CHECK_BY_NAME[check_name]
        # A missing cost has no bad row to point at, so its record count is 0.
        record_count = sum(row["row_number"] is not None for row in group)
        findings.append({
            "finding_id": finding_id, "check_name": check.name, "month": month,
            "product_id": product_id, "outcome": check.outcome, "severity": check.severity,
            "affected_metrics": ";".join(check.affected_metrics),
            "record_count": record_count,
            "description": check.finding_text.format(
                product=product_names[product_id], month=month, count=record_count or len(group)
            ),
        })  # fmt: skip
        for row in group:
            record = {}
            if row["row_number"] is not None:
                record = dict(source_rows[row["source_table"]][row["row_number"] - 1])
                record.pop("row_number")
            records.append({
                "finding_id": finding_id, "source_table": row["source_table"],
                "row_number": row["row_number"],
                "quarantined": check.outcome == "quarantine", "detail": row["detail"],
                "record": json.dumps(record, default=str),
            })  # fmt: skip

    finding_columns = [
        "finding_id", "check_name", "month", "product_id", "outcome", "severity",
        "affected_metrics", "record_count", "description",
    ]  # fmt: skip
    record_columns = ["finding_id", "source_table", "row_number", "quarantined", "detail", "record"]
    findings_table = pd.DataFrame(findings, columns=finding_columns)
    records_table = pd.DataFrame(records, columns=record_columns)
    records_table["row_number"] = records_table["row_number"].astype("Int64")
    return findings_table, records_table


# ---- Check cases: tiny tables that each check must pass or fail (LLD section 10) ----


def load_check_cases(check_name: str | None = None) -> list[dict]:
    """The check cases, for one check or for all of them."""
    cases = json.loads(CHECK_CASES_FILE.read_text(encoding="utf-8"))
    return [case for case in cases if check_name in (None, case["check"])]


def tables_for_case(case: dict) -> dict[str, pa.Table]:
    """Turn a case's few rows into numbered source tables. A table the case leaves out is empty."""
    tables = {}
    for name, schema in SOURCE_SCHEMAS.items():
        tables[name] = table_from_rows(case["inputs"].get(name, []), schema)
    return number_rows(tables)


def run_check_case(case: dict) -> tuple[bool, list[dict]]:
    """Run a case's check on its tables. Returns (found exactly what was expected, what it found)."""
    found = run_check(CHECK_BY_NAME[case["check"]], tables_for_case(case))
    actual = [
        {"source_table": row["source_table"], "row_number": row["row_number"]}
        for row in as_rows(found)
    ]

    def as_text(rows: list[dict]) -> list[str]:
        return sorted(f"{row['source_table']} {row['row_number']}" for row in rows)

    return as_text(actual) == as_text(case["expected"]), actual
