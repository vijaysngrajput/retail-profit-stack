"""The pipeline: load the business's records, run the six transformations, save the results.

Implements LLD section 6 (Engines, Pipeline). The engine is chosen by one setting. Everything
else is the same whichever engine runs.

Run it with:  uv run python -m retail_profit_stack.transform.pipeline [sql|pandas]
"""

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from retail_profit_stack.config import SOURCE_DIR, WAREHOUSE_DIR
from retail_profit_stack.transform.contracts import TableSchema, conform
from retail_profit_stack.transform.engines import Engine, get_engine
from retail_profit_stack.transform.specs import SOURCE_SCHEMAS, ordered_specs


@dataclass
class PipelineRun:
    """What one run of the pipeline did."""

    engine: str
    tables: dict[str, pa.Table] = field(default_factory=dict)
    row_counts: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0


def read_source(schema: TableSchema, source_dir: Path = SOURCE_DIR) -> pa.Table:
    """Read one source CSV with the column types its schema declares."""
    path = source_dir / f"{schema.name}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing source table {path}. Generate the records with: "
            "uv run python -m retail_profit_stack.source_data"
        )
    options = pacsv.ConvertOptions(column_types=schema.arrow_schema(), strings_can_be_null=False)
    return conform(pacsv.read_csv(path, convert_options=options), schema)


def load_sources(source_dir: Path = SOURCE_DIR) -> dict[str, pa.Table]:
    """Every source table, checked against its schema."""
    return {name: read_source(schema, source_dir) for name, schema in SOURCE_SCHEMAS.items()}


def run_transformations(engine: Engine, sources: dict[str, pa.Table]) -> dict[str, pa.Table]:
    """Run the six transformations in order on one engine. Each output feeds the next."""
    for name, table in sources.items():
        engine.register(name, table)
    outputs = {}
    for spec in ordered_specs():
        outputs[spec.name] = engine.run(spec)
        engine.register(spec.name, outputs[spec.name])
    return outputs


def run_pipeline(
    engine_name: str | None = None,
    source_dir: Path = SOURCE_DIR,
    warehouse_dir: Path | None = WAREHOUSE_DIR,
) -> PipelineRun:
    """Calculate every table and save it as Parquet. Pass warehouse_dir=None to skip saving."""
    start = time.time()
    engine = get_engine(engine_name)
    run = PipelineRun(engine=engine.name)
    run.tables = run_transformations(engine, load_sources(source_dir))
    if warehouse_dir is not None:
        warehouse_dir.mkdir(parents=True, exist_ok=True)
        for name, table in run.tables.items():
            pq.write_table(table, warehouse_dir / f"{name}.parquet")
    run.row_counts = {name: table.num_rows for name, table in run.tables.items()}
    run.seconds = round(time.time() - start, 2)
    return run


if __name__ == "__main__":
    result = run_pipeline(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Ran on the {result.engine} engine in {result.seconds} seconds")
    for table_name, count in result.row_counts.items():
        print(f"  {table_name}: {count} rows")
    print(f"Saved to {WAREHOUSE_DIR}")
