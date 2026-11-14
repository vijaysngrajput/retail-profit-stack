"""The pipeline: load the records, check them, calculate the figures, save the results.

Implements LLD section 2 (One pipeline run, step by step). The quality checks run around
milestone 2's transformations. The engine is still chosen by one setting.

Run it with:  uv run python -m retail_profit_stack.transform.pipeline [sql|pandas]
"""

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from retail_profit_stack.config import SOURCE_DIR, WAREHOUSE_DIR
from retail_profit_stack.quality.checks import (
    check_outcomes,
    make_findings,
    number_rows,
    run_record_checks,
    run_totals_check,
)
from retail_profit_stack.quality.quarantine import split_records
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
    # New in milestone 3: what the quality checks found.
    check_outcomes: dict[str, str] = field(default_factory=dict)  # check name -> pass or outcome
    findings: pd.DataFrame = field(default_factory=pd.DataFrame)
    finding_records: pd.DataFrame = field(default_factory=pd.DataFrame)
    quarantined_counts: dict[str, int] = field(default_factory=dict)  # table -> rows set aside


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

    # 1. Load the source tables and number their rows.
    sources = number_rows(load_sources(source_dir))
    # 2. Run the four record checks. Each returns its bad records.
    bad_records = run_record_checks(sources)
    # 3. Set the quarantined rows aside.
    kept, quarantined = split_records(sources, bad_records)
    # 4. Calculate the figures from the kept rows only.
    run.tables = run_transformations(engine, kept)
    # 5. Check that the profit table adds up to the kept rows.
    totals_problems = run_totals_check(kept, run.tables["monthly_product_profit"])
    bad_records = pd.concat([bad_records, totals_problems], ignore_index=True)
    # 6. Group the bad records into findings.
    run.findings, run.finding_records = make_findings(bad_records, sources)

    run.check_outcomes = check_outcomes(bad_records)
    run.quarantined_counts = {name: table.num_rows for name, table in quarantined.items()}
    run.row_counts = {name: table.num_rows for name, table in run.tables.items()}
    if warehouse_dir is not None:
        warehouse_dir.mkdir(parents=True, exist_ok=True)
        for name, table in run.tables.items():
            pq.write_table(table, warehouse_dir / f"{name}.parquet")
        run.findings.to_parquet(warehouse_dir / "quality_findings.parquet", index=False)
        run.finding_records.to_parquet(warehouse_dir / "finding_records.parquet", index=False)
    run.seconds = round(time.time() - start, 2)
    return run


if __name__ == "__main__":
    result = run_pipeline(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Ran on the {result.engine} engine in {result.seconds} seconds")
    for table_name, count in result.row_counts.items():
        print(f"  {table_name}: {count} rows")
    for check_name, outcome in result.check_outcomes.items():
        print(f"  check {check_name}: {outcome}")
    print(f"  findings: {len(result.findings)}")
    print(f"Saved to {WAREHOUSE_DIR}")
