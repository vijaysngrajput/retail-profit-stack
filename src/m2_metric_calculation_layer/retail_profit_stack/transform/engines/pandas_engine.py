"""The pandas engine. Suited to small data that fits in memory.

Implements LLD section 6 (Engines). An implementation is a function
transform(inputs: dict[str, pd.DataFrame]) -> pd.DataFrame.
"""

import importlib

import pandas as pd
import pyarrow as pa

from retail_profit_stack.transform.contracts import TransformationSpec
from retail_profit_stack.transform.engines.base import Engine, Implementation

IMPLEMENTATIONS_PACKAGE = "retail_profit_stack.transform.implementations.pandas"


def to_frame(table: pa.Table) -> pd.DataFrame:
    """An Arrow table as a DataFrame. Dates become pandas datetimes, so .dt works on them."""
    return table.to_pandas(date_as_object=False)


class PandasEngine(Engine):
    name = "pandas"

    def __init__(self):
        self.tables: dict[str, pd.DataFrame] = {}

    def register(self, name: str, table: pa.Table) -> None:
        self.tables[name] = to_frame(table)

    def load_implementation(self, spec: TransformationSpec) -> Implementation:
        module = importlib.import_module(f"{IMPLEMENTATIONS_PACKAGE}.{spec.name}")
        return Implementation(engine=self.name, name=spec.name, function=module.transform)

    def execute(self, implementation: Implementation, spec: TransformationSpec) -> pa.Table:
        if implementation.function is None:
            raise ValueError("A pandas implementation needs a function")
        # Each implementation gets its own copies, so it cannot change another one's inputs.
        inputs = {name: self.tables[name].copy() for name in spec.inputs}
        result = implementation.function(inputs)
        if not isinstance(result, pd.DataFrame):
            raise TypeError(f"transform must return a DataFrame, got {type(result).__name__}")
        return pa.Table.from_pandas(result, preserve_index=False)
