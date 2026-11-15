"""Load the tables the tools read into DuckDB, and check them.

Implements LLD section 6 (The tools). The store reads one pipeline run: the latest one, unless
a run is named. The profit table, the findings, and the lineage come from that run's folder.
The business's records come from data/source/.
"""

import json
import threading
from functools import lru_cache
from pathlib import Path

import duckdb

from retail_profit_stack.config import (
    DEFINITIONS_FILE,
    MOCK_DIR,
    SOURCE_DIR,
    STATE_FILE,
    WAREHOUSE_DIR,
)
from retail_profit_stack.ingest import ledger
from retail_profit_stack.lineage.runs import latest_run_id, read_history, run_folder
from retail_profit_stack.quality.checks import number_rows
from retail_profit_stack.transform.pipeline import load_sources

PROFIT_TABLE = "monthly_product_profit"
FINDINGS_TABLE = "quality_findings"


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
        run_id: str | None = None,
        state_file: Path | None = STATE_FILE,
    ):
        self.db = duckdb.connect(":memory:")
        # An agent may call several tools at once, each on its own thread. A DuckDB connection
        # cannot run two queries at the same time, so queries take turns.
        self._lock = threading.Lock()

        # New in milestone 4: read one run. With no run named, read the latest.
        self.warehouse_dir = warehouse_dir
        chosen_run = run_id or latest_run_id(warehouse_dir)
        if chosen_run is None:
            raise DataContractError(
                f"There is no pipeline run in {warehouse_dir}. Make the first two runs with: "
                "uv run python -m retail_profit_stack.make_history"
            )
        self.run_id: str = chosen_run
        folder = run_folder(self.run_id, warehouse_dir)

        # The tables the tools read, all from that run's folder.
        tables = {
            PROFIT_TABLE: PROFIT_TABLE,
            "quality_flags": FINDINGS_TABLE,
            "finding_records": "finding_records",
            "figure_lineage": "figure_lineage",
            "lineage_steps": "lineage_steps",
        }
        for table, file_name in tables.items():
            file = folder / f"{file_name}.parquet"
            if not file.exists():
                raise DataContractError(f"A table of run {self.run_id} is missing ({file}).")
            self.db.execute(f"CREATE TABLE {table} AS SELECT * FROM read_parquet(?)", [str(file)])
        # The tools have always called a finding's id "flag_id". Keep that name.
        self.db.execute("ALTER TABLE quality_flags RENAME COLUMN finding_id TO flag_id")

        # The business's records: products for names and categories, the rest as evidence.
        try:
            # New in milestone 6: a run keeps the records it used, so read those. An older
            # run without them falls back to the records as they are now.
            snapshot = folder / "sources"
            sources = number_rows(load_sources(snapshot if snapshot.exists() else source_dir))
        except FileNotFoundError as error:
            raise DataContractError(str(error)) from error
        for name, table in sources.items():
            self.db.register(f"arrow_{name}", table)
            self.db.execute(f"CREATE TABLE {name} AS SELECT * FROM arrow_{name}")
            self.db.unregister(f"arrow_{name}")

        # New in milestone 6: the run before this one, and the load record, for missing files.
        run_ids = [record["run_id"] for record in read_history(warehouse_dir)]
        position = run_ids.index(self.run_id)
        self.previous_run_id: str | None = run_ids[position - 1] if position > 0 else None
        self.files_seen: list[dict] = []
        if state_file is not None and state_file.exists():
            self.files_seen = ledger.files_seen(state_file)

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
