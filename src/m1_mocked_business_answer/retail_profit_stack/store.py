"""Load the mock tables into DuckDB and check them against their contract.

Implements LLD section 3 (Mock tables). The tools in tools.py read data only
through the connection this module returns.
"""

import json
from functools import lru_cache
from pathlib import Path

import duckdb

from retail_profit_stack.config import DEFINITIONS_FILE, MOCK_DIR
from retail_profit_stack.schemas import MONEY_TERMS

TABLE_COLUMNS = {
    "products": {"product_id": "VARCHAR", "product_name": "VARCHAR", "category": "VARCHAR"},
    "monthly_product_profit": {
        "month": "VARCHAR",
        "product_id": "VARCHAR",
        "units_sold": "INTEGER",
        **{term: "DOUBLE" for term in MONEY_TERMS},
        "metric_version": "VARCHAR",
    },
    "evidence_records": {
        "evidence_id": "VARCHAR",
        "month": "VARCHAR",
        "product_id": "VARCHAR",
        "record_type": "VARCHAR",
        "source_table": "VARCHAR",
        "source_record_id": "VARCHAR",
        "amount": "DOUBLE",
        "description": "VARCHAR",
    },
    "quality_flags": {
        "flag_id": "VARCHAR",
        "month": "VARCHAR",
        "product_id": "VARCHAR",
        "check_name": "VARCHAR",
        "severity": "VARCHAR",
        "affected_metrics": "VARCHAR",
        "description": "VARCHAR",
    },
}


class DataContractError(Exception):
    """A mock table does not match the contract in LLD section 3."""


class Store:
    """The milestone's data: four tables in DuckDB, plus two small JSON files."""

    def __init__(self, mock_dir: Path = MOCK_DIR, definitions_file: Path = DEFINITIONS_FILE):
        self.db = duckdb.connect(":memory:")
        for table, columns in TABLE_COLUMNS.items():
            path = mock_dir / f"{table}.csv"
            if not path.exists():
                raise DataContractError(f"Missing mock table: {path}")
            try:
                self.db.execute(
                    f"CREATE TABLE {table} AS SELECT * FROM read_csv(?, header=true, columns=?)",
                    [str(path), columns],
                )
            except duckdb.Error as error:
                raise DataContractError(
                    f"{table}.csv does not match its contract: {error}"
                ) from error
        self.reporting_period = json.loads((mock_dir / "reporting_period.json").read_text("utf-8"))
        self.definitions = json.loads(definitions_file.read_text("utf-8"))
        self._check_references()

    def _check_references(self) -> None:
        """Every product mentioned in another table must exist in products."""
        for table in ("monthly_product_profit", "evidence_records", "quality_flags"):
            unknown = self.db.execute(
                f"SELECT DISTINCT product_id FROM {table} "
                "WHERE product_id NOT IN (SELECT product_id FROM products)"
            ).fetchall()
            if unknown:
                raise DataContractError(f"{table} refers to unknown products: {unknown}")

    def rows(self, sql: str, params: list | None = None) -> list[dict]:
        """Run a query and return its rows as dictionaries."""
        cursor = self.db.execute(sql, params or [])
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    def months(self) -> list[str]:
        return [
            row["month"]
            for row in self.rows("SELECT DISTINCT month FROM monthly_product_profit ORDER BY month")
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
    """The shared store for this milestone's mock data."""
    return Store()
