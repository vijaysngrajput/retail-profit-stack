"""LLD sections 4 to 6 and 10: the checks, the quarantine, and the findings."""

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from retail_profit_stack.config import WAREHOUSE_DIR
from retail_profit_stack.lineage.runs import run_folder
from retail_profit_stack.quality.checks import (
    CHECKS,
    RECORD_CHECKS,
    load_check_cases,
    number_rows,
    run_check_case,
    run_record_checks,
    run_totals_check,
)
from retail_profit_stack.quality.quarantine import split_records
from retail_profit_stack.transform.pipeline import load_sources, run_pipeline

# check, month, product, outcome, records: the seven planted problems (LLD section 3)
EXPECTED_FINDINGS = [
    ("QF-001", "duplicate_records", "2026-09", "P005", "quarantine", 1),
    ("QF-002", "duplicate_records", "2026-10", "P001", "quarantine", 9),
    ("QF-003", "duplicate_records", "2026-10", "P002", "quarantine", 12),
    ("QF-004", "missing_product_cost", "2026-10", "P007", "needs_review", 0),
    ("QF-005", "event_out_of_order", "2026-09", "P009", "needs_review", 1),
    ("QF-006", "event_out_of_order", "2026-10", "P003", "needs_review", 1),
    ("QF-007", "refund_exceeds_line", "2026-09", "P011", "needs_review", 1),
]


def test_five_checks_each_with_a_query_and_an_outcome():
    assert [check.name for check in CHECKS] == [
        "duplicate_records", "missing_product_cost", "event_out_of_order",
        "refund_exceeds_line", "totals_do_not_match",
    ]  # fmt: skip
    assert {check.outcome for check in CHECKS} == {"quarantine", "needs_review"}
    assert [check.outcome for check in CHECKS].count("quarantine") == 1  # only certain errors


@pytest.mark.parametrize("case", load_check_cases(), ids=lambda case: case["name"])
def test_every_check_case(case):
    passed, found = run_check_case(case)
    assert passed, f"expected {case['expected']}, found {found}"


def test_every_record_check_has_a_clean_case_and_a_defect_case():
    for check in RECORD_CHECKS:
        cases = load_check_cases(check.name)
        assert any(not case["expected"] for case in cases), check.name
        assert any(case["expected"] for case in cases), check.name


def test_each_planted_problem_produces_its_finding(calculated_tables):
    findings = calculated_tables.findings
    actual = list(
        findings[
            ["finding_id", "check_name", "month", "product_id", "outcome", "record_count"]
        ].itertuples(index=False, name=None)
    )
    assert actual == EXPECTED_FINDINGS
    assert calculated_tables.check_outcomes == {
        "duplicate_records": "quarantine", "missing_product_cost": "needs_review",
        "event_out_of_order": "needs_review", "refund_exceeds_line": "needs_review",
        "totals_do_not_match": "pass",
    }  # fmt: skip


def test_kept_plus_quarantined_equals_the_source_for_every_table():
    sources = number_rows(load_sources())
    kept, quarantined = split_records(sources, run_record_checks(sources))
    for name, table in sources.items():
        assert kept[name].num_rows + quarantined[name].num_rows == table.num_rows, name
    assert {name: table.num_rows for name, table in quarantined.items() if table.num_rows} == {
        "order_items": 7, "shipments": 7, "payment_fees": 7, "refunds": 1,
    }  # fmt: skip


def test_a_record_that_needs_review_is_kept():
    sources = number_rows(load_sources())
    kept, _ = split_records(sources, run_record_checks(sources))
    refunds = kept["refunds"].to_pylist()
    assert any(row["refund_amount"] == 60.0 for row in refunds)  # the oversized refund stays
    assert sum(row["refund_id"] == "REF-0014" for row in refunds) == 1  # one copy of the duplicate


def test_no_duplicates_remain_in_the_kept_records():
    sources = number_rows(load_sources())
    kept, _ = split_records(sources, run_record_checks(sources))
    assert run_record_checks(number_rows(kept)).query("check_name == 'duplicate_records'").empty


def test_quarantined_records_can_be_inspected(calculated_tables):
    records = calculated_tables.finding_records
    set_aside = records[records["quarantined"]]
    assert len(set_aside) == 22
    assert set(set_aside["finding_id"]) == {"QF-001", "QF-002", "QF-003"}
    assert all('"order_item_id"' in record for record in set_aside["record"])
    folder = run_folder(calculated_tables.run_id, WAREHOUSE_DIR)
    saved = pq.read_table(folder / "finding_records.parquet").to_pandas()
    assert len(saved) == len(records)


def kept_and_profit(calculated_tables):
    sources = number_rows(load_sources())
    kept, _ = split_records(sources, run_record_checks(sources))
    return kept, calculated_tables.tables["monthly_product_profit"]


def test_totals_check_passes_a_correct_profit_table(calculated_tables):
    kept, profit = kept_and_profit(calculated_tables)
    assert run_totals_check(kept, profit).empty


def test_totals_check_finds_a_removed_row(calculated_tables):
    kept, profit = kept_and_profit(calculated_tables)
    found = run_totals_check(kept, profit.slice(1))  # the first row is missing
    assert set(found["product_id"]) == {profit.column("product_id")[0].as_py()}
    assert len(found) == 8  # every one of the eight terms differs


def test_totals_check_finds_a_changed_amount(calculated_tables):
    kept, profit = kept_and_profit(calculated_tables)
    frame = profit.to_pandas()
    frame.loc[3, "refunds"] += 10.0
    found = run_totals_check(kept, pa.Table.from_pandas(frame, preserve_index=False))
    assert len(found) == 1 and found["detail"].iloc[0].startswith("refunds:")


def test_totals_check_would_catch_counting_the_duplicates(calculated_tables):
    """If the calculation ran on all the records, the totals would not match the kept ones."""
    kept, _ = kept_and_profit(calculated_tables)
    unchecked = run_pipeline_without_checks()
    found = run_totals_check(kept, unchecked)
    assert set(found["product_id"]) == {"P001", "P002", "P005"}


def run_pipeline_without_checks() -> pa.Table:
    from retail_profit_stack.transform.engines import get_engine
    from retail_profit_stack.transform.pipeline import run_transformations

    return run_transformations(get_engine("sql"), load_sources())["monthly_product_profit"]


def test_running_twice_gives_the_same_findings():
    first, second = (
        run_pipeline("sql", warehouse_dir=None),
        run_pipeline("pandas", warehouse_dir=None),
    )
    pd.testing.assert_frame_equal(first.findings, second.findings)
    pd.testing.assert_frame_equal(first.finding_records, second.finding_records)
