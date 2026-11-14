"""The production checks find what the lab's hand-written checks find.

In notebook 2 the learner writes two checks by hand as SQL queries. Those versions are kept in
notebooks/lab_helpers.py. The production checks were rebuilt from them, and this test compares
the two on the full data.
"""

import sys

from retail_profit_stack.config import MILESTONE_DIR
from retail_profit_stack.quality.checks import CHECK_BY_NAME, number_rows, run_check
from retail_profit_stack.transform.pipeline import load_sources

sys.path.insert(0, str(MILESTONE_DIR / "notebooks"))
import lab_helpers


def by_hand(sql: str, table: str) -> list[int]:
    tables = lab_helpers.load_source_tables()
    numbered = {name: lab_helpers.add_row_numbers(frame) for name, frame in tables.items()}
    return sorted(int(number) for number in lab_helpers.run_sql(sql, numbered)["row_number"])


def production(check_name: str, table: str) -> list[int]:
    found = run_check(CHECK_BY_NAME[check_name], number_rows(load_sources()))
    return sorted(int(number) for number in found[found["source_table"] == table]["row_number"])


def test_the_notebook_duplicate_check_matches_production():
    rows = by_hand(lab_helpers.DUPLICATE_LINES_SQL, "order_items")
    assert len(rows) == 7 and rows == production("duplicate_records", "order_items")


def test_the_notebook_refund_check_matches_production():
    rows = by_hand(lab_helpers.REFUND_EXCEEDS_LINE_SQL, "refunds")
    assert len(rows) == 1 and rows == production("refund_exceeds_line", "refunds")


def test_the_lab_row_numbers_match_production_row_numbers():
    by_lab = lab_helpers.add_row_numbers(lab_helpers.load_source_tables()["refunds"])
    in_production = number_rows(load_sources())["refunds"].to_pandas()
    assert by_lab["row_number"].tolist() == in_production["row_number"].tolist()
    assert by_lab["refund_id"].tolist() == in_production["refund_id"].tolist()


def test_the_answer_key_matches_the_calculated_tables(calculated_tables):
    checked = lab_helpers.check_key_against_calculated(lab_helpers.load_result("answer_key"))
    assert len(checked) == 8 and set(checked["Same?"]) == {"yes"}


def test_the_new_answer_key_differs_from_milestone_2_only_where_the_bottle_counts():
    old = {
        line["what"]: line["value"]
        for line in lab_helpers.load_result("answer_key_milestone_2")["figures"]
    }
    new = {line["what"]: line["value"] for line in lab_helpers.load_result("answer_key")["figures"]}
    changed = {what: round(old[what] - new[what], 2) for what in old if old[what] != new[what]}
    assert changed == {
        "#1 product: Trail water bottle": 31.26,
        "Top category: Hydration": 31.26,
        "Hydration, change since the month before": 31.26,
    }
