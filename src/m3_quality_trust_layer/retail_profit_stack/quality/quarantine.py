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
        if CHECK_BY_NAME[bad_row["check_name"]].outcome != "quarantine":
            continue  # a "needs review" row stays in the figures
        to_quarantine.setdefault(bad_row["source_table"], set()).add(bad_row["row_number"])
    return to_quarantine


def split_records(
    numbered_sources: dict[str, pa.Table], bad_records: pd.DataFrame
) -> tuple[dict[str, pa.Table], dict[str, pa.Table]]:
    """Return (kept tables, quarantined tables). Neither has the row_number column.

    For every table: kept rows + quarantined rows = source rows. Nothing is deleted.
    """
    to_quarantine = rows_to_quarantine(bad_records)
    kept, quarantined = {}, {}
    for name, table in numbered_sources.items():
        numbers = to_quarantine.get(name, set())
        set_aside = [number in numbers for number in table.column("row_number").to_pylist()]
        keep = [not flag for flag in set_aside]
        kept[name] = table.filter(pa.array(keep)).drop_columns(["row_number"])
        quarantined[name] = table.filter(pa.array(set_aside)).drop_columns(["row_number"])
    return kept, quarantined
