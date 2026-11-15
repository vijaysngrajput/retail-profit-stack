"""Engines: interchangeable adapters that run a transformation's implementation.

Implements LLD section 6 (Engines).
"""

import os

from retail_profit_stack.transform.engines.base import Engine, Implementation
from retail_profit_stack.transform.engines.pandas_engine import PandasEngine
from retail_profit_stack.transform.engines.spark_engine import SparkEngine
from retail_profit_stack.transform.engines.sql_engine import SqlEngine

ENGINES: dict[str, type[Engine]] = {"sql": SqlEngine, "pandas": PandasEngine, "spark": SparkEngine}
DEFAULT_ENGINE = "sql"


def get_engine(name: str | None = None) -> Engine:
    """Return a fresh engine. With no name, use the TRANSFORM_ENGINE setting, or SQL."""
    name = name or os.getenv("TRANSFORM_ENGINE", DEFAULT_ENGINE)
    if name not in ENGINES:
        raise ValueError(f"Unknown engine '{name}'. Valid values: {', '.join(ENGINES)}")
    return ENGINES[name]()


__all__ = ["DEFAULT_ENGINE", "ENGINES", "Engine", "Implementation", "get_engine"]
