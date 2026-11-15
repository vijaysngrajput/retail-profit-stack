"""The production code finds what the lab's hand-written code finds.

In the lab the learner writes small versions by hand: two checks (milestone 3), and a
fingerprint, lineage for order lines, a run comparison, and kappa (milestone 4). Those versions
are kept in notebooks/lab_helpers.py. Production was rebuilt from them, and these tests compare
the two.
"""

import sys

from retail_profit_stack.config import MILESTONE_DIR
from retail_profit_stack.quality.checks import CHECK_BY_NAME, number_rows, run_check
from retail_profit_stack.transform.pipeline import load_sources

sys.path.insert(0, str(MILESTONE_DIR / "notebooks"))
import lab_helpers

from retail_profit_stack.config import WAREHOUSE_DIR as WAREHOUSE


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


# ---- New in milestone 4: the lab's by-hand versions agree with production ----


def test_the_notebook_fingerprint_matches_production():
    from retail_profit_stack.config import LANDING_DIR
    from retail_profit_stack.lineage.runs import fingerprint

    file = LANDING_DIR / "product_costs_2026-09.csv"
    assert lab_helpers.fingerprint_by_hand(file) == fingerprint(file)


def test_the_notebook_order_line_lineage_matches_production(calculated_tables):
    from retail_profit_stack.config import WAREHOUSE_DIR

    kept = lab_helpers.kept_tables(calculated_tables.run_id, WAREHOUSE_DIR)
    by_hand = lab_helpers.run_sql(lab_helpers.ORDER_LINE_LINEAGE_SQL, kept)
    lineage = calculated_tables.lineage
    production = lineage[lineage["term"] == "gross_sales"]
    columns = ["month", "product_id", "row_number", "amount"]
    left = by_hand[columns].sort_values("row_number").reset_index(drop=True)
    right = production[columns].sort_values("row_number").reset_index(drop=True)
    assert len(left) == len(right) == 2518
    assert left["row_number"].tolist() == right["row_number"].tolist()
    assert (left["amount"] - right["amount"]).abs().max() < 0.005


def test_the_notebook_run_comparison_matches_production():
    from retail_profit_stack.lineage.compare import compare_runs

    earlier = lab_helpers.read_run_table("RUN-0001", "monthly_product_profit", WAREHOUSE)
    later = lab_helpers.read_run_table("RUN-0002", "monthly_product_profit", WAREHOUSE)
    by_hand = lab_helpers.changed_figures_by_hand(earlier, later).to_dict(orient="records")
    production = [
        {key: row[key] for key in ("month", "product_id", "earlier", "later", "change")}
        for row in compare_runs("RUN-0001", "RUN-0002")["figures_changed"]
        if row["metric"] == "contribution_profit"
    ]
    assert by_hand == production and len(by_hand) == 3


def test_the_notebook_kappa_and_costs_match_production():
    import pandas as pd

    from retail_profit_stack import scoring

    table = pd.DataFrame({
        "right_level": ["high", "high", "medium", "low", "declined", "low"],
        "level": ["high", "medium", "medium", "high", "declined", "declined"],
    })  # fmt: skip
    assert abs(lab_helpers.kappa_by_hand(table) - scoring.kappa(table)) < 1e-9
    assert lab_helpers.LEVELS == scoring.LEVELS
    costs = scoring.MISTAKE_COSTS
    assert lab_helpers.cost_by_hand("medium", "high") == costs["too_confident"]
    assert lab_helpers.cost_by_hand("medium", "low") == costs["not_confident_enough"]
    assert lab_helpers.cost_by_hand("declined", "low") == costs["answered_when_it_should_decline"]
    assert lab_helpers.cost_by_hand("high", "declined") == costs["no_answer"]
    assert lab_helpers.cost_by_hand("low", "low") == 0


def test_the_lineage_answer_key_matches_the_tools():
    from retail_profit_stack import tools

    key = lab_helpers.load_result("answer_key_lineage")
    evidence = tools.get_evidence(key["month"], key["product_id"])
    assert evidence.record_counts == key["record_counts"]
    assert evidence.total_records == key["total_records"]
    moved = tools.compare_runs(key["month"], key["product_id"]).figures_changed[0]
    assert (moved.earlier, moved.later, moved.change) == (
        key["earlier_contribution_profit"], key["contribution_profit"], key["change"],
    )  # fmt: skip


# ---- New in milestone 5: the rule chosen by hand in the lab equals production's ----


def test_the_notebook_rule_matches_production_for_every_landing_file():
    from retail_profit_stack.config import LANDING_DIR
    from retail_profit_stack.ingest.feeds import expected_columns, feed_of
    from retail_profit_stack.ingest.rules import inspect_file

    files = sorted(LANDING_DIR.glob("*.csv"))
    assert len(files) == 50
    for file in files:
        found = inspect_file(file, expected_columns(feed_of(file.name)), loaded={}, approved=[])
        by_hand = lab_helpers.rule_by_hand(found.missing, found.unknown)
        assert by_hand == (found.rule, found.outcome), file.name


def test_the_lab_reads_the_same_tables_as_production():
    in_lab = lab_helpers.load_source_tables()
    in_production = load_sources()
    for name, table in in_production.items():
        assert len(in_lab[name]) == table.num_rows, name
