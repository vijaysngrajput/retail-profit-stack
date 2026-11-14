"""LLD section 2: the metric definitions file is complete and consistent."""

import pytest

from retail_profit_stack import tools
from retail_profit_stack.schemas import ALL_TERMS, APPROVED_METRICS
from retail_profit_stack.store import get_store


def test_every_term_is_defined_once_with_the_current_version():
    metrics = get_store().definitions["metrics"]
    assert [metric["name"] for metric in metrics] == ALL_TERMS
    assert {metric["version"] for metric in metrics} == {"1.0.0"}


def test_components_refer_to_defined_terms():
    for metric in get_store().definitions["metrics"]:
        assert set(metric["components"]) <= set(ALL_TERMS)


def test_approved_metrics_are_marked():
    approved = [m["name"] for m in get_store().definitions["metrics"] if m["approved"]]
    assert approved == APPROVED_METRICS


def test_get_metric_definition_returns_formula_and_source():
    definition = tools.get_metric_definition("contribution_profit")
    assert definition.formula == (
        "gross_profit - fulfillment_cost - shipping_cost - payment_fees - return_cost"
    )
    assert definition.sources[0].table == "metric_definitions"


def test_unknown_metric_lists_valid_values():
    with pytest.raises(tools.ToolInputError, match="contribution_profit"):
        tools.get_metric_definition("ebitda")
