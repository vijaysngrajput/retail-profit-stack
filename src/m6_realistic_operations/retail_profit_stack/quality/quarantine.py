"""Split the records into kept and quarantined.

Implements LLD section 5 (Outcomes and quarantine). A row is quarantined when a check whose
outcome is "quarantine" listed it. Every other row is kept, including rows that need review.
"""

import pandas as pd
import pyarrow as pa

from retail_profit_stack.quality.checks import CHECK_BY_NAME, as_rows


def rows_to_quarantine(bad_records: pd.DataFrame) -> dict[str, set[int]]:
    """For each source table, the row numbers that must be set aside."""
    to_quarantine: dict[str, set[int]] = {}
    for bad_row in as_rows(bad_records):
        excluded = bad_row.get("decision") == "exclude"  # milestone 6: decided at the review desk
        if CHECK_BY_NAME[bad_row["check_name"]].outcome != "quarantine" and not excluded:
            continue  # a "needs review" row stays in the figures
        to_quarantine.setdefault(bad_row["source_table"], set()).add(bad_row["row_number"])
    return to_quarantine


def split_records(
    numbered_sources: dict[str, pa.Table], bad_records: pd.DataFrame, keep_row_numbers: bool = False
) -> tuple[dict[str, pa.Table], dict[str, pa.Table]]:
    """Return (kept tables, quarantined tables).

    For every table: kept rows + quarantined rows = source rows. Nothing is deleted.
    The row_number column is dropped, unless keep_row_numbers is true. Milestone 4's lineage
    needs the row numbers, so the pipeline keeps them.
    """
    to_quarantine = rows_to_quarantine(bad_records)
    kept, quarantined = {}, {}
    for name, table in numbered_sources.items():
        numbers = to_quarantine.get(name, set())
        set_aside = [number in numbers for number in table.column("row_number").to_pylist()]
        keep = [not flag for flag in set_aside]
        # The type is given so that an empty table (a feed with no files yet) also works.
        kept[name] = table.filter(pa.array(keep, type=pa.bool_()))
        quarantined[name] = table.filter(pa.array(set_aside, type=pa.bool_()))
    if not keep_row_numbers:
        kept = without_row_numbers(kept)
        quarantined = without_row_numbers(quarantined)
    return kept, quarantined


def without_row_numbers(tables: dict[str, pa.Table]) -> dict[str, pa.Table]:
    """The same tables with the row_number column removed."""
    return {name: table.drop_columns(["row_number"]) for name, table in tables.items()}
