"""Load the tables the tools read into DuckDB, and check them.

Implements LLD section 7 (Changes to the tools and the store). The profit table now comes
from data/warehouse/, where the pipeline writes it. The business's records come from
data/source/ and are used as evidence. The quality flags are still mocked.
"""

import json
import threading
from functools import lru_cache
from pathlib import Path

import duckdb

from retail_profit_stack.config import DEFINITIONS_FILE, MOCK_DIR, SOURCE_DIR, WAREHOUSE_DIR
from retail_profit_stack.transform.pipeline import load_sources

PROFIT_TABLE = "monthly_product_profit"
QUALITY_FLAG_COLUMNS = {
    "flag_id": "VARCHAR", "month": "VARCHAR", "product_id": "VARCHAR", "check_name": "VARCHAR",
    "severity": "VARCHAR", "affected_metrics": "VARCHAR", "description": "VARCHAR",
}  # fmt: skip


class DataContractError(Exception):
    """A table the tools need is missing or does not match what the tools expect."""


class Store:
    """The milestone's data in one DuckDB database, plus two small JSON files."""

    def __init__(
        self,
        mock_dir: Path = MOCK_DIR,
        definitions_file: Path = DEFINITIONS_FILE,
        source_dir: Path = SOURCE_DIR,
        warehouse_dir: Path = WAREHOUSE_DIR,
    ):
        self.db = duckdb.connect(":memory:")
        # An agent may call several tools at once, each on its own thread. A DuckDB connection
        # cannot run two queries at the same time, so queries take turns.
        self._lock = threading.Lock()

        profit_file = warehouse_dir / f"{PROFIT_TABLE}.parquet"
        if not profit_file.exists():
            raise DataContractError(
                f"The calculated profit table is missing ({profit_file}). Run the pipeline first: "
                "uv run python -m retail_profit_stack.transform.pipeline"
            )
        self.db.execute(
            f"CREATE TABLE {PROFIT_TABLE} AS SELECT * FROM read_parquet(?)", [str(profit_file)]
        )

        # The business's records: products for names and categories, the rest as evidence.
        try:
            sources = load_sources(source_dir)
        except FileNotFoundError as error:
            raise DataContractError(str(error)) from error
        for name, table in sources.items():
            self.db.register(f"arrow_{name}", table)
            self.db.execute(f"CREATE TABLE {name} AS SELECT * FROM arrow_{name}")
            self.db.unregister(f"arrow_{name}")

        flags_file = mock_dir / "quality_flags.csv"
        if not flags_file.exists():
            raise DataContractError(f"Missing mock table: {flags_file}")
        try:
            self.db.execute(
                "CREATE TABLE quality_flags AS SELECT * FROM read_csv(?, header=true, columns=?)",
                [str(flags_file), QUALITY_FLAG_COLUMNS],
            )
        except duckdb.Error as error:
            raise DataContractError(
                f"quality_flags.csv does not match its contract: {error}"
            ) from error

        self.reporting_period = json.loads((mock_dir / "reporting_period.json").read_text("utf-8"))
        self.definitions = json.loads(definitions_file.read_text("utf-8"))
        self._check_references()

    def _check_references(self) -> None:
        """Every product mentioned in the profit table or the flags must exist in products."""
        for table in (PROFIT_TABLE, "quality_flags"):
            unknown = self.db.execute(
                f"SELECT DISTINCT product_id FROM {table} "
                "WHERE product_id NOT IN (SELECT product_id FROM products)"
            ).fetchall()
            if unknown:
                raise DataContractError(f"{table} refers to unknown products: {unknown}")

    def rows(self, sql: str, params: list | None = None) -> list[dict]:
        """Run a query and return its rows as dictionaries."""
        with self._lock:
            cursor = self.db.execute(sql, params or [])
            names = [column[0] for column in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def months(self) -> list[str]:
        return [
            row["month"]
            for row in self.rows(f"SELECT DISTINCT month FROM {PROFIT_TABLE} ORDER BY month")
        ]

    def categories(self) -> list[str]:
        return [
            row["category"]
            for row in self.rows("SELECT DISTINCT category FROM products ORDER BY category")
        ]

    def product_ids(self) -> list[str]:
        return [
            row["product_id"]
            for row in self.rows("SELECT product_id FROM products ORDER BY product_id")
        ]


@lru_cache(maxsize=1)
def get_store() -> Store:
    """The shared store for this milestone's data."""
    return Store()
