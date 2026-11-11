"""LLD section 4: ranking, missing values, category sums, comparison, confidence, bad input."""

import pytest

from retail_profit_stack import tools


def test_reporting_period_fixes_last_month():
    period = tools.get_reporting_period()
    assert (period.current_month, period.previous_month) == ("2026-10", "2026-09")
    assert period.available_months == ["2026-09", "2026-10"]


def test_products_are_ranked_highest_first():
    rows = tools.query_profit("2026-10", "product").rows
    assert [(row.entity_id, row.rank) for row in rows[:3]] == [
        ("P001", 1),
        ("P008", 2),
        ("P009", 3),
    ]
    assert rows[0].contribution_profit == 5188.20


def test_missing_value_is_unranked_and_listed_last():
    last = tools.query_profit("2026-10", "product").rows[-1]
    assert last.entity_id == "P007"
    assert last.contribution_profit is None and last.rank is None and not last.is_complete
    assert last.net_sales == 10013.00  # terms that can be calculated are still reported


def test_top_n_keeps_only_the_top_rows():
    assert len(tools.query_profit("2026-10", "product", top_n=3).rows) == 3


def test_ranking_follows_the_chosen_metric():
    top = tools.query_profit("2026-10", "product", metric="net_sales").rows[0]
    assert top.entity_id == "P001" and top.net_sales == 18252.00


def test_category_rows_are_summed_from_products():
    rows = {row.entity_id: row for row in tools.query_profit("2026-09", "category").rows}
    products = tools.query_profit("2026-09", "product").rows
    hydration = sum(row.net_sales for row in products if row.category == "Hydration")
    assert rows["Hydration"].net_sales == pytest.approx(hydration, abs=0.005) == 40190.50
    assert all(row.is_complete for row in rows.values())


def test_category_with_a_missing_product_is_incomplete():
    rows = {row.entity_id: row for row in tools.query_profit("2026-10", "category").rows}
    assert not rows["Camp"].is_complete
    assert rows["Camp"].contribution_profit == 9366.26  # the three products that have a value
    assert rows["Hydration"].is_complete and rows["Hydration"].rank == 1


def test_comparison_change_and_percentage():
    rows = {
        row.entity_id: row for row in tools.compare_profit("2026-10", "2026-09", "category").rows
    }
    assert rows["Apparel"].change == -5914.87
    assert rows["Apparel"].pct_change == -37.8
    assert rows["Hydration"].change == 376.06


def test_comparison_is_empty_when_a_month_is_incomplete():
    by_category = {
        row.entity_id: row for row in tools.compare_profit("2026-10", "2026-09", "category").rows
    }
    by_product = {
        row.entity_id: row for row in tools.compare_profit("2026-10", "2026-09", "product").rows
    }
    for row in (by_category["Camp"], by_product["P007"]):
        assert row.change is None and row.pct_change is None and not row.is_complete


def test_comparison_sorts_biggest_fall_first_and_unknown_last():
    rows = tools.compare_profit("2026-10", "2026-09", "category").rows
    assert [row.entity_id for row in rows] == ["Apparel", "Hydration", "Camp"]


def test_confidence_follows_the_worst_flag():
    assert tools.get_quality_flags("2026-10").confidence_level == "low"  # high severity
    assert tools.get_quality_flags("2026-10", product_id="P001").confidence_level == "medium"
    assert tools.get_quality_flags("2026-09").confidence_level == "high"  # low severity
    clean = tools.get_quality_flags("2026-09", category="Hydration")
    assert clean.flags == [] and clean.confidence_level == "high"


def test_quality_flags_can_be_narrowed_by_category():
    flags = tools.get_quality_flags("2026-10", category="Camp").flags
    assert [flag.flag_id for flag in flags] == ["QF-001"]
    assert flags[0].affected_metrics == ["product_cost", "gross_profit", "contribution_profit"]


def test_evidence_is_marked_as_a_sample():
    evidence = tools.get_evidence("2026-10", "P001", limit=2)
    assert evidence.is_sample and len(evidence.records) == 2
    assert all(record.product_id == "P001" for record in evidence.records)


def test_every_result_names_its_sources():
    results = [
        tools.get_reporting_period(),
        tools.get_metric_definition("net_sales"),
        tools.query_profit("2026-10", "product"),
        tools.compare_profit("2026-10", "2026-09", "product"),
        tools.get_evidence("2026-10", "P001"),
        tools.get_quality_flags("2026-10"),
    ]
    assert all(result.sources for result in results)


@pytest.mark.parametrize(
    "call",
    [
        lambda: tools.query_profit("2026-11", "product"),
        lambda: tools.query_profit("2026-10", "channel"),
        lambda: tools.query_profit("2026-10", "product", metric="ebitda"),
        lambda: tools.compare_profit("2026-10", "2025-10", "product"),
        lambda: tools.get_evidence("2026-10", "P999"),
        lambda: tools.get_quality_flags("2026-10", category="Footwear"),
    ],
)
def test_bad_input_raises_with_valid_values(call):
    with pytest.raises(tools.ToolInputError, match="Valid values"):
        call()
