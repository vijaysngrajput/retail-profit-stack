"""Lineage: which records made each figure, and the proof that they add up.

Implements LLD section 4 (Lineage). Lineage has two levels. The steps say which table was made
from which. The records say which source records count toward one product's figures in one
month, and how much each adds. No model is involved anywhere in this file.
"""

from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa

from retail_profit_stack.transform.specs import ordered_specs

LINEAGE_SQL_FILE = Path(__file__).resolve().parent / "sql" / "figure_lineage.sql"
LINEAGE_COLUMNS = [
    "month", "product_id", "term", "source_table", "row_number", "record_id", "amount",
]  # fmt: skip

# The terms that come straight from records. The proof below checks each of them.
RECORD_TERMS = [
    "units_sold", "gross_sales", "discounts", "refunds", "return_cost",
    "fulfillment_cost", "shipping_cost", "payment_fees", "product_cost",
]  # fmt: skip

# A metric is made of terms, each added (+1) or taken away (-1).
METRIC_TERMS = {
    "net_sales": {"gross_sales": +1, "discounts": -1, "refunds": -1},
    "gross_profit": {"net_sales": +1, "product_cost": -1},
    "contribution_profit": {
        "gross_profit": +1,
        "fulfillment_cost": -1,
        "shipping_cost": -1,
        "payment_fees": -1,
        "return_cost": -1,
    },
}


def lineage_steps(code: dict[str, str]) -> pd.DataFrame:
    """One row for each input of each transformation: which table was made from which.

    code maps a transformation's name to the fingerprint of the file that ran it.
    """
    rows = []
    for spec in ordered_specs():
        for input_table in spec.inputs:
            rows.append({
                "output_table": spec.name,
                "input_table": input_table,
                "code_fingerprint": code.get(spec.name, ""),
            })  # fmt: skip
    return pd.DataFrame(rows, columns=["output_table", "input_table", "code_fingerprint"])


def build_lineage(kept_numbered: dict[str, pa.Table]) -> pd.DataFrame:
    """Run the lineage query on the kept records. The tables must have row numbers."""
    db = duckdb.connect(":memory:")
    for name, table in kept_numbered.items():
        db.register(name, table)
    query = LINEAGE_SQL_FILE.read_text(encoding="utf-8")
    lineage = db.execute(query).df()
    db.close()
    return pd.DataFrame(lineage, columns=LINEAGE_COLUMNS)


def lineage_differences(lineage: pd.DataFrame, profit: pd.DataFrame) -> pd.DataFrame:
    """The proof. Add up the lineage for each figure and compare it with the profit table.

    Returns one row for each total that differs by more than half a cent. An empty table
    means the lineage adds up.
    """
    # 1. Add up the lineage: one total per month, product, and term.
    lineage_totals: dict[tuple, float] = {}
    for row in lineage.to_dict(orient="records"):
        key = (row["month"], row["product_id"], row["term"])
        lineage_totals[key] = lineage_totals.get(key, 0.0) + float(row["amount"])

    # 2. Read the same totals from the profit table. A missing value counts as zero.
    profit_totals: dict[tuple, float] = {}
    for row in profit.to_dict(orient="records"):
        for term in RECORD_TERMS:
            value = row[term]
            key = (row["month"], row["product_id"], term)
            profit_totals[key] = 0.0 if pd.isna(value) else float(value)

    # 3. Keep only the totals that differ.
    differences = []
    for key in sorted(set(lineage_totals) | set(profit_totals)):
        profit_total = profit_totals.get(key, 0.0)
        lineage_total = lineage_totals.get(key, 0.0)
        if abs(profit_total - lineage_total) > 0.005:
            month, product_id, term = key
            differences.append({
                "month": month, "product_id": product_id, "term": term,
                "profit_total": round(profit_total, 2), "lineage_total": round(lineage_total, 2),
            })  # fmt: skip
    columns = ["month", "product_id", "term", "profit_total", "lineage_total"]
    return pd.DataFrame(differences, columns=columns)


def record_counts(lineage: pd.DataFrame, month: str, product_id: str) -> dict[str, int]:
    """How many records are behind one product's figures in one month, by source table."""
    records = set()
    for row in lineage.to_dict(orient="records"):
        if row["month"] == month and row["product_id"] == product_id:
            records.add((row["source_table"], int(row["row_number"])))
    counts: dict[str, int] = {}
    for source_table, _ in sorted(records):
        counts[source_table] = counts.get(source_table, 0) + 1
    return counts
