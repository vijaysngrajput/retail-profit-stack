"""Shared test setup: the run history must exist before the tools are tested."""

import pytest

from retail_profit_stack.make_history import make_history
from retail_profit_stack.store import get_store


@pytest.fixture(scope="session", autouse=True)
def calculated_tables():
    """Rebuild the two runs the milestone starts with, so the tools read RUN-0002.

    Returns the second run, which is the one the tools read.
    """
    runs = make_history()
    get_store.cache_clear()
    return runs[1]
