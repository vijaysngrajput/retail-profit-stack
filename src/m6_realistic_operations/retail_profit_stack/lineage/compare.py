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


def record_amounts(lineage: pd.DataFrame) -> dict[tuple, tuple]:
    """Each record in a lineage table, with the amounts it adds, as (term, amount) pairs.

    The key is (month, product_id, source_table, row_number).
    """
    amounts: dict[tuple, list] = {}
    for row in lineage.to_dict(orient="records"):
        key = (row["month"], row["product_id"], row["source_table"], int(row["row_number"]))
        amounts.setdefault(key, []).append((row["term"], round(float(row["amount"]), 2)))
    return {key: tuple(sorted(values)) for key, values in amounts.items()}


def changed_records(earlier_lineage: pd.DataFrame, later_lineage: pd.DataFrame) -> list[dict]:
    """For each month, product, and source table: records that came, went, or changed amount.

    "changed" is new in milestone 6: a record in both runs whose amount differs, which is
    what a corrected file produces.
    """
    earlier = record_amounts(earlier_lineage)
    later = record_amounts(later_lineage)
    counts: dict[tuple, dict[str, int]] = {}

    def count(key: tuple, what: str) -> None:
        month, product_id, source_table, _ = key
        group = counts.setdefault(
            (month, product_id, source_table), {"earlier": 0, "later": 0, "changed": 0}
        )
        group[what] += 1

    for key in earlier:
        if key not in later:
            count(key, "earlier")
        # A cost row's amount is the unit cost times the units sold, so it moves whenever
        # sales move. Only a record's own amounts count as a correction.
        elif earlier[key] != later[key] and key[2] != "product_costs":
            count(key, "changed")
    for key in later:
        if key not in earlier:
            count(key, "later")
    rows = []
    for (month, product_id, source_table), group in sorted(counts.items()):
        rows.append({
            "month": month, "product_id": product_id, "source_table": source_table,
            "only_in_earlier": group["earlier"], "only_in_later": group["later"],
            "changed": group["changed"],
        })  # fmt: skip
    return rows


def changed_files(earlier_inputs: dict, later_inputs: dict) -> tuple[list[str], list[str]]:
    """New in milestone 6: the files that were added, and the files that were corrected.

    A run records the fingerprint of every file behind each table. A file only in the later
    run was added. A file in both, with a different fingerprint, was corrected.
    """
    added, corrected = [], []
    for table, later in later_inputs.items():
        before = earlier_inputs.get(table, {}).get("pieces", {})
        for piece, print_ in later.get("pieces", {}).items():
            file_name = piece.replace(".parquet", ".csv")
            if piece not in before:
                added.append(file_name)
            elif before[piece] != print_:
                corrected.append(file_name)
    return sorted(added), sorted(corrected)


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

    files_added, files_corrected = changed_files(earlier_record["inputs"], later_record["inputs"])
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
        "files_added": files_added,
        "files_corrected": files_corrected,
        "figures_changed": figures,
        "records_changed": records,
        "findings": findings,
    }
