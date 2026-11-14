"""Shared test setup: the calculated tables must exist before the tools are tested."""

import pytest

from retail_profit_stack.transform.pipeline import run_pipeline


@pytest.fixture(scope="session", autouse=True)
def calculated_tables():
    """Run the pipeline once, so data/warehouse/ holds the profit table the tools read."""
    return run_pipeline("sql")
