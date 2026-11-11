"""The production tools return what the notebook's tools returned.

The notebook saves a few of its tool outputs to notebooks/m1_key_outputs.json. This test
replays the same calls against the production tools and compares every value.
"""

import json

import pytest

from retail_profit_stack import tools
from retail_profit_stack.config import MILESTONE_DIR

KEY_OUTPUTS = MILESTONE_DIR / "notebooks" / "m1_key_outputs.json"

PRODUCTION_CALLS = {
    "reporting_period": lambda: tools.get_reporting_period(),
    "query_product": lambda: tools.query_profit("2026-10", "product"),
    "query_category": lambda: tools.query_profit("2026-10", "category"),
    "query_category_previous_net_sales": lambda: tools.query_profit(
        "2026-09", "category", metric="net_sales"
    ),
    "compare_category": lambda: tools.compare_profit("2026-10", "2026-09", "category"),
    "compare_product": lambda: tools.compare_profit("2026-10", "2026-09", "product"),
    "quality_month": lambda: tools.get_quality_flags("2026-10"),
    "quality_product": lambda: tools.get_quality_flags("2026-10", product_id="P001"),
    "quality_clean": lambda: tools.get_quality_flags("2026-09", category="Hydration"),
    "evidence": lambda: tools.get_evidence("2026-10", "P001"),
}


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


@pytest.mark.parametrize("name", list(PRODUCTION_CALLS))
def test_production_matches_notebook(name):
    recorded = json.loads(KEY_OUTPUTS.read_text("utf-8"))
    assert_same(recorded[name], PRODUCTION_CALLS[name]().model_dump(), name)


def test_every_recorded_output_is_checked():
    assert set(json.loads(KEY_OUTPUTS.read_text("utf-8"))) == set(PRODUCTION_CALLS)
