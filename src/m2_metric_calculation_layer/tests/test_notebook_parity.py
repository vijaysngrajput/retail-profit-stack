"""The production transformations give what the lab's hand-written versions give.

In notebook 2 the learner writes the sales transformation by hand, in pandas and in SQL. Those
versions are kept in notebooks/lab_helpers.py. The production implementations were rebuilt
from them, and this test compares the two on the full data.
"""

import sys

import pyarrow as pa

from retail_profit_stack.config import MILESTONE_DIR
from retail_profit_stack.transform import drafting
from retail_profit_stack.transform.contracts import conform, tables_differ
from retail_profit_stack.transform.specs import ALL_IN_ONE, SPECS

sys.path.insert(0, str(MILESTONE_DIR / "notebooks"))
import lab_helpers


def production_sales(calculated_tables):
    return calculated_tables.tables["sales"]


def test_the_notebook_pandas_version_matches_production(calculated_tables):
    by_hand = lab_helpers.sales_pandas(lab_helpers.load_source_tables())
    table = conform(pa.Table.from_pandas(by_hand, preserve_index=False), SPECS["sales"].output)
    assert tables_differ(table, production_sales(calculated_tables)) is None


def test_the_notebook_sql_version_matches_production(calculated_tables):
    by_hand = lab_helpers.run_sql(lab_helpers.SALES_SQL, lab_helpers.load_source_tables())
    table = conform(pa.Table.from_pandas(by_hand, preserve_index=False), SPECS["sales"].output)
    assert tables_differ(table, production_sales(calculated_tables)) is None


def test_the_lab_broken_draft_fails_only_the_case_with_two_refunds():
    results = {
        r.case: r
        for r in drafting.run_draft(lab_helpers.broken_all_in_one_sql(), "sql", ALL_IN_ONE)
    }
    assert [name for name, result in results.items() if not result.passed] == ["everything at once"]
    assert "units_sold: expected 2, got 4" in results["everything at once"].message


def test_the_answer_key_matches_the_calculated_tables(calculated_tables):
    checked = lab_helpers.check_key_against_calculated(lab_helpers.load_result("answer_key"))
    assert len(checked) == 8 and set(checked["Same?"]) == {"yes"}
