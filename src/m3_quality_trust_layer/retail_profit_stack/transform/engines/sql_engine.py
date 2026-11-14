"""The SQL engine, using DuckDB. Suited to medium data on one machine.

Implements LLD section 6 (Engines). An implementation is one SELECT statement that names its
input tables.
"""

import duckdb
import pyarrow as pa

from retail_profit_stack.transform.contracts import TransformationSpec
from retail_profit_stack.transform.engines.base import IMPLEMENTATIONS_DIR, Engine, Implementation


class SqlEngine(Engine):
    name = "sql"

    def __init__(self, allow_external_access: bool = True):
        # Drafts written by a model run with access to files and the network switched off.
        config: dict[str, str | bool | int | float | list[str]] = (
            {} if allow_external_access else {"enable_external_access": "false"}
        )
        self.db = duckdb.connect(":memory:", config=config)

    def register(self, name: str, table: pa.Table) -> None:
        self.db.register(name, table)

    def load_implementation(self, spec: TransformationSpec) -> Implementation:
        path = IMPLEMENTATIONS_DIR / "sql" / f"{spec.name}.sql"
        return Implementation(engine=self.name, name=spec.name, code=path.read_text("utf-8"))

    def execute(self, implementation: Implementation, spec: TransformationSpec) -> pa.Table:
        return self.db.sql(implementation.code).to_arrow_table()
