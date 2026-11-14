"""Compare two runs: what changed, and which figures moved.

Implements LLD section 5 (Comparing two runs). Everything here is subtraction and set
difference on saved tables. No model is involved, so a model never works out a change.
"""

from pathlib import Path

import pandas as pd

from retail_profit_stack.config import WAREHOUSE_DIR
from retail_profit_stack.lineage.runs import read_run_record, run_folder
from retail_profit_stack.schemas import ALL_TERMS

KEY = ["month", "product_id"]


def changed_values(earlier: dict, later: dict) -> list[dict]:
    """Every key whose value differs between two dictionaries."""
    changes = []
    for name in sorted(set(earlier) | set(later)):
        if earlier.get(name) != later.get(name):
            changes.append({"name": name, "earlier": earlier.get(name), "later": later.get(name)})
    return changes


def changed_figures(earlier_profit: pd.DataFrame, later_profit: pd.DataFrame) -> list[dict]:
    """One row per month, product, and metric whose value differs between the two runs."""
    both = earlier_profit.merge(later_profit, on=KEY, how="outer", suffixes=("_earlier", "_later"))
    rows = []
    for row in both.to_dict(orient="records"):
        for metric in ALL_TERMS:
            earlier = _number(row[f"{metric}_earlier"])
            later = _number(row[f"{metric}_later"])
            if earlier == later:
                continue
            # A change needs a value on both sides. Unavailable to available has no amount.
            change = None
            if earlier is not None and later is not None:
                change = round(later - earlier, 2)
            rows.append({
                "month": row["month"], "product_id": row["product_id"], "metric": metric,
                "earlier": earlier, "later": later, "change": change,
            })  # fmt: skip
    return rows


def _number(value) -> float | None:
    """A table value as a rounded number, or None when it is missing."""
    return None if pd.isna(value) else round(float(value), 2)


def record_keys(lineage: pd.DataFrame) -> set[tuple]:
    """The records in a lineage table, each as (month, product_id, source_table, row_number)."""
    keys = set()
    for row in lineage.to_dict(orient="records"):
        keys.add((row["month"], row["product_id"], row["source_table"], int(row["row_number"])))
    return keys


def changed_records(earlier_lineage: pd.DataFrame, later_lineage: pd.DataFrame) -> list[dict]:
    """For each month, product, and source table: records in only one of the two runs."""
    earlier = record_keys(earlier_lineage)
    later = record_keys(later_lineage)
    # Count the records found on one side only, grouped by month, product, and source table.
    counts: dict[tuple, dict[str, int]] = {}
    for month, product_id, source_table, _ in earlier - later:
        group = counts.setdefault((month, product_id, source_table), {"earlier": 0, "later": 0})
        group["earlier"] += 1
    for month, product_id, source_table, _ in later - earlier:
        group = counts.setdefault((month, product_id, source_table), {"earlier": 0, "later": 0})
        group["later"] += 1
    rows = []
    for (month, product_id, source_table), group in sorted(counts.items()):
        rows.append({
            "month": month, "product_id": product_id, "source_table": source_table,
            "only_in_earlier": group["earlier"], "only_in_later": group["later"],
        })  # fmt: skip
    return rows


def compare_runs(earlier_id: str, later_id: str, warehouse_dir: Path = WAREHOUSE_DIR) -> dict:
    """Everything that differs between two runs. Each part is a plain list of rows."""
    earlier_record = read_run_record(earlier_id, warehouse_dir)
    later_record = read_run_record(later_id, warehouse_dir)
    earlier_folder = run_folder(earlier_id, warehouse_dir)
    later_folder = run_folder(later_id, warehouse_dir)

    figures = changed_figures(
        pd.read_parquet(earlier_folder / "monthly_product_profit.parquet"),
        pd.read_parquet(later_folder / "monthly_product_profit.parquet"),
    )
    records = changed_records(
        pd.read_parquet(earlier_folder / "figure_lineage.parquet"),
        pd.read_parquet(later_folder / "figure_lineage.parquet"),
    )

    # The findings for the months and products whose figures moved, in each run.
    moved = {(row["month"], row["product_id"]) for row in figures}
    findings = []
    for which, folder in (("earlier", earlier_folder), ("later", later_folder)):
        table = pd.read_parquet(folder / "quality_findings.parquet")
        for row in table.to_dict(orient="records"):
            if (row["month"], row["product_id"]) in moved:
                findings.append({
                    "run": which, "finding_id": row["finding_id"],
                    "check_name": row["check_name"], "month": row["month"],
                    "product_id": row["product_id"], "outcome": row["outcome"],
                    "record_count": int(row["record_count"]), "description": row["description"],
                })  # fmt: skip

    inputs_earlier = {name: item["fingerprint"] for name, item in earlier_record["inputs"].items()}
    inputs_later = {name: item["fingerprint"] for name, item in later_record["inputs"].items()}
    return {
        "earlier_run": earlier_id,
        "later_run": later_id,
        "earlier_note": earlier_record["note"],
        "later_note": later_record["note"],
        "settings_changed": changed_values(earlier_record["settings"], later_record["settings"]),
        "inputs_changed": changed_values(inputs_earlier, inputs_later),
        "code_changed": changed_values(earlier_record["code"], later_record["code"]),
        "checks_changed": changed_values(
            earlier_record["check_outcomes"], later_record["check_outcomes"]
        ),
        "figures_changed": figures,
        "records_changed": records,
        "findings": findings,
    }
