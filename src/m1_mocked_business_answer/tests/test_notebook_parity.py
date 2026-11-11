"""The production tools return what the lab notebooks' tools return.

The notebooks' tools are plain pandas functions in notebooks/lab_helpers.py. The production
tools in retail_profit_stack/tools.py were rebuilt from them. This test calls both with the
same arguments and compares every value.
"""

import sys

import pytest

from retail_profit_stack import tools
from retail_profit_stack.config import MILESTONE_DIR

sys.path.insert(0, str(MILESTONE_DIR / "notebooks"))
import lab_helpers

CALLS = [
    ("get_reporting_period", {}),
    ("get_metric_definition", {"metric": "contribution_profit"}),
    ("get_metric_definition", {"metric": "units_sold"}),
    ("query_profit", {"month": "2026-10", "group_by": "product"}),
    ("query_profit", {"month": "2026-10", "group_by": "category"}),
    ("query_profit", {"month": "2026-09", "group_by": "category", "metric": "net_sales"}),
    ("query_profit", {"month": "2026-10", "group_by": "product", "top_n": 3}),
    ("compare_profit", {"month": "2026-10", "previous_month": "2026-09", "group_by": "category"}),
    ("compare_profit", {"month": "2026-10", "previous_month": "2026-09", "group_by": "product"}),
    ("compare_profit", {"month": "2026-10", "previous_month": "2026-09", "group_by": "category",
                        "metric": "net_sales"}),
    ("get_evidence", {"month": "2026-10", "product_id": "P001"}),
    ("get_evidence", {"month": "2026-09", "product_id": "P011", "limit": 2}),
    ("get_quality_flags", {"month": "2026-10"}),
    ("get_quality_flags", {"month": "2026-10", "product_id": "P001"}),
    ("get_quality_flags", {"month": "2026-09", "category": "Hydration"}),
]  # fmt: skip


def assert_same(notebook, production, path):
    """Compare two JSON-like values, allowing a cent of difference in numbers."""
    if isinstance(notebook, dict):
        assert isinstance(production, dict) and notebook.keys() == production.keys(), path
        for key in notebook:
            assert_same(notebook[key], production[key], f"{path}.{key}")
    elif isinstance(notebook, list):
        assert isinstance(production, list) and len(notebook) == len(production), path
        for index, (left, right) in enumerate(zip(notebook, production, strict=True)):
            assert_same(left, right, f"{path}[{index}]")
    elif isinstance(notebook, float) or isinstance(production, float):
        assert production == pytest.approx(notebook, abs=0.005), path
    else:
        assert notebook == production, path


@pytest.mark.parametrize(("name", "arguments"), CALLS)
def test_production_tool_matches_notebook_tool(name, arguments):
    notebook_result = getattr(lab_helpers, name)(**arguments)
    production_result = getattr(tools, name)(**arguments).model_dump()
    assert_same(notebook_result, production_result, name)


def test_all_six_tools_are_compared():
    assert {name for name, _ in CALLS} == {
        "get_reporting_period", "get_metric_definition", "query_profit", "compare_profit",
        "get_evidence", "get_quality_flags",
    }  # fmt: skip


@pytest.mark.parametrize("name", ["query_profit", "get_quality_flags"])
def test_bad_input_is_rejected_the_same_way(name):
    with pytest.raises(lab_helpers.ToolInputError) as notebook_error:
        getattr(lab_helpers, name)(
            month="2026-12", **({"group_by": "product"} if name == "query_profit" else {})
        )
    with pytest.raises(tools.ToolInputError) as production_error:
        getattr(tools, name)(
            month="2026-12", **({"group_by": "product"} if name == "query_profit" else {})
        )
    assert str(notebook_error.value) == str(production_error.value)
